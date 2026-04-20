"""Evaluation harness for dialogue quality (v0.22.0).

Karpathy move: "don't grow without measuring." Every feature we've
shipped between v0.2.0 and v0.21.0 adds prompt tokens or runtime
complexity. Without an eval harness we can only argue about whether
output quality is rising. This module turns the argument into a
number.

Design:

- **Case**: one (npc, prompt) pair + expectations (max length, word
  caps, forbidden phrases). Curated by writers — this is your golden
  set.
- **Rubric**: four cheap dimensions that run per generated line:
  1. Voice consistency (embedding cosine against ``sample_lines``)
  2. Lint hits (forbidden-word matches + stage-direction markers)
  3. Length compliance (sentence count below the cap)
  4. Register cleanliness (no meta-phrases — "as an AI", "as an NPC",
     parenthetical stage directions like "(quietly)")
- **Runner**: executes each case through ``improv_query`` and scores
  the reply. Writes a markdown report + JSON sidecar.
- **Gating**: an overall pass/fail threshold, so this can land in CI.

Not covered here: semantic factual grounding (did the reply honour
the lore?), dialogue flow (does it feel natural across turns?). Both
are genuinely harder; out of scope for the first eval pass.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from .improv import ImprovReply, improv_query
from .schemas import (
    FactionsConfig,
    NpcSheet,
    load_factions,
    load_npcs,
    load_world_bible,
)
from .voice_score import _cosine, _normalise  # reuse the normaliser

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Case + result schemas
# ---------------------------------------------------------------------------


class EvalCase(BaseModel):
    """One scored prompt targeting one NPC."""

    id: str = Field(..., description="Unique case id.")
    npc_id: str
    prompt: str
    max_sentences: int = Field(
        default=3,
        description="Hard cap on sentence count before length fails.",
    )
    max_words: int = Field(
        default=60,
        description="Hard cap on word count before length fails.",
    )
    forbid_phrases: list[str] = Field(
        default_factory=list,
        description=(
            "Case-specific forbidden phrases, lower-cased for matching. "
            "Per-NPC forbidden_words from the character sheet are checked "
            "separately."
        ),
    )


class CaseResult(BaseModel):
    """Scored outcome for a single case."""

    case_id: str
    npc_id: str
    prompt: str
    text: str = ""
    generated_ok: bool = True
    voice_score: float = Field(
        default=0.0,
        description="Cosine sim vs. sample_lines in [0, 1]; 0 if unavailable.",
    )
    lint_hits: int = 0
    lint_notes: list[str] = Field(default_factory=list)
    length_ok: bool = True
    register_ok: bool = True
    overall_pass: bool = False
    elapsed_ms: float = 0.0


class EvalReport(BaseModel):
    """Aggregate report across every case."""

    provider: str
    model: str
    total: int = 0
    passed: int = 0
    voice_avg: float = 0.0
    lint_total: int = 0
    length_failures: int = 0
    register_failures: int = 0
    results: list[CaseResult] = Field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        return 0.0 if self.total == 0 else self.passed / self.total


# ---------------------------------------------------------------------------
# Scoring helpers (pure, fast)
# ---------------------------------------------------------------------------


_SENTENCE_END = re.compile(r"[.!?]+")

# Dead-giveaway meta phrases. The register-clean check fails hard on
# any of these — they're the reliable "LLM broke character" tells.
_META_PHRASES = (
    "as an ai", "as a language model", "as an assistant",
    "i cannot", "i'm just a", "i can't help with",
    "(quietly)", "(softly)", "(warmly)", "(angrily)", "(sadly)",
    "*nods*", "*smiles*", "*laughs*",
    "[narrator]", "narrator:",
)


def count_sentences(text: str) -> int:
    """Rough sentence count via end-punctuation. Accurate enough for
    line-level dialogue; off by one is fine."""
    if not text.strip():
        return 0
    # Split on end-of-sentence punctuation; drop empties.
    parts = [p for p in _SENTENCE_END.split(text) if p.strip()]
    return max(1, len(parts))


def count_words(text: str) -> int:
    return len(text.split())


def check_lint(
    text: str, npc: NpcSheet, extra_forbidden: list[str] | None = None,
) -> tuple[int, list[str]]:
    """Count forbidden-word + ceiling-cue hits; return (count, notes)."""
    notes: list[str] = []
    lower = text.lower()
    forbidden = [w.lower() for w in npc.forbidden_words]
    if extra_forbidden:
        forbidden.extend(w.lower() for w in extra_forbidden)

    hits = 0
    for word in forbidden:
        if not word:
            continue
        # Word-boundary match so "deep" doesn't false-positive on "deepness"
        # unless a later tester wants the looser behavior. Err on strict.
        if re.search(rf"\b{re.escape(word)}\b", lower):
            hits += 1
            notes.append(f"forbidden word used: '{word}'")
    return hits, notes


def check_register(text: str) -> tuple[bool, list[str]]:
    """Return (ok, notes). Fails on any _META_PHRASES hit."""
    notes: list[str] = []
    lower = text.lower()
    for phrase in _META_PHRASES:
        if phrase in lower:
            notes.append(f"meta phrase leaked: '{phrase}'")
    return (len(notes) == 0), notes


# ---------------------------------------------------------------------------
# Voice score (per reply; uses the same embedding backend as voice_score.py)
# ---------------------------------------------------------------------------


async def voice_score_for_reply(
    *,
    npc: NpcSheet,
    text: str,
    api_key: str,
    provider: str,
) -> float:
    """Cosine similarity of ``text`` against the NPC's sample lines.

    Returns 0.0 when the NPC has no sample_lines or the embedding
    provider fails — same graceful degradation as the walk-up scorer.
    """
    samples = [s.strip() for s in npc.sample_lines if s and s.strip()]
    if not samples or not text.strip():
        return 0.0

    from afterimage.evaluator import default_embedding_provider_config
    from afterimage.key_management import SmartKeyPool
    from afterimage.providers.embedding_providers import EmbeddingProviderFactory

    cfg = default_embedding_provider_config(provider)
    key_pool = SmartKeyPool.from_single_key(api_key)
    embedder = EmbeddingProviderFactory.create(cfg, key_pool=key_pool)
    try:
        vectors = await embedder.embed(samples + [text])
    except Exception as exc:
        logger.warning("eval voice-score embedding failed: %s", exc)
        try:
            await embedder.aclose()
        except Exception:
            pass
        return 0.0
    try:
        await embedder.aclose()
    except Exception:
        pass

    if len(vectors) != len(samples) + 1:
        return 0.0
    reply_vec = vectors[-1]
    sample_vecs = vectors[:-1]
    sims = [_cosine(reply_vec, s) for s in sample_vecs]
    return _normalise(max(sims) if sims else 0.0)


# ---------------------------------------------------------------------------
# Case runner
# ---------------------------------------------------------------------------


async def run_case(
    case: EvalCase,
    *,
    npcs_by_id: dict[str, NpcSheet],
    world_bible: str,
    factions: Optional[FactionsConfig],
    api_key: str,
    provider: str,
    model: Optional[str],
) -> CaseResult:
    """Execute one case end-to-end and score the reply."""
    import time

    result = CaseResult(
        case_id=case.id, npc_id=case.npc_id, prompt=case.prompt,
    )
    npc = npcs_by_id.get(case.npc_id)
    if npc is None:
        result.generated_ok = False
        result.lint_notes.append(f"unknown npc '{case.npc_id}'")
        return result

    start = time.perf_counter()
    reply: ImprovReply | None = await improv_query(
        npc=npc,
        query=case.prompt,
        world_bible=world_bible,
        factions=factions,
        memory_store=None,  # evals run against the static sheet, no memory
        api_key=api_key,
        model_name=model,
        model_provider_name=provider,
        temperature=0.8,
    )
    result.elapsed_ms = (time.perf_counter() - start) * 1000.0

    if reply is None or not reply.text.strip():
        result.generated_ok = False
        result.lint_notes.append("empty / failed generation")
        return result

    result.text = reply.text.strip()

    # Length.
    sent = count_sentences(result.text)
    words = count_words(result.text)
    if sent > case.max_sentences or words > case.max_words:
        result.length_ok = False
        result.lint_notes.append(
            f"length: {sent} sentences / {words} words "
            f"(max {case.max_sentences}/{case.max_words})"
        )

    # Lint.
    hits, notes = check_lint(
        result.text, npc, extra_forbidden=case.forbid_phrases,
    )
    result.lint_hits = hits
    result.lint_notes.extend(notes)

    # Register.
    register_ok, reg_notes = check_register(result.text)
    result.register_ok = register_ok
    result.lint_notes.extend(reg_notes)

    # Voice score (embedding call).
    result.voice_score = await voice_score_for_reply(
        npc=npc, text=result.text, api_key=api_key, provider=provider,
    )

    # Overall: pass requires generation succeeded + no lint/register
    # hits + length within caps + voice score above a soft floor.
    result.overall_pass = (
        result.generated_ok
        and result.lint_hits == 0
        and result.length_ok
        and result.register_ok
        and result.voice_score >= 0.3
    )
    return result


async def run_suite(
    cases: list[EvalCase],
    *,
    demo_dir: Path,
    api_key: str,
    provider: str,
    model: Optional[str],
) -> EvalReport:
    """Run every case in sequence (intentionally — LLM rate limits)."""
    npcs = {n.id: n for n in load_npcs(demo_dir / "characters.yaml")}
    factions = load_factions(demo_dir / "factions.yaml")
    world_bible = load_world_bible(demo_dir / "lore")

    report = EvalReport(
        provider=provider,
        model=model or "(provider default)",
        total=len(cases),
    )
    voice_sum = 0.0
    voice_counted = 0
    for c in cases:
        r = await run_case(
            c,
            npcs_by_id=npcs,
            world_bible=world_bible,
            factions=factions,
            api_key=api_key,
            provider=provider,
            model=model,
        )
        report.results.append(r)
        if r.overall_pass:
            report.passed += 1
        report.lint_total += r.lint_hits
        if not r.length_ok:
            report.length_failures += 1
        if not r.register_ok:
            report.register_failures += 1
        if r.voice_score > 0:
            voice_sum += r.voice_score
            voice_counted += 1
    report.voice_avg = voice_sum / voice_counted if voice_counted else 0.0
    return report


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------


def render_markdown_report(report: EvalReport) -> str:
    """Markdown table report suitable for committing to out/."""
    lines: list[str] = []
    lines.append(f"# npcforge eval report")
    lines.append("")
    lines.append(f"- provider: `{report.provider}`")
    lines.append(f"- model: `{report.model}`")
    lines.append(f"- cases: {report.total}")
    lines.append(
        f"- **passed: {report.passed} / {report.total} "
        f"({report.pass_rate * 100:.0f}%)**"
    )
    lines.append(f"- voice-consistency avg: {report.voice_avg:.3f}")
    lines.append(f"- total lint hits: {report.lint_total}")
    lines.append(f"- length failures: {report.length_failures}")
    lines.append(f"- register failures: {report.register_failures}")
    lines.append("")
    lines.append("| case | npc | pass | voice | lint | len | reg | elapsed |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in report.results:
        pass_mark = "✓" if r.overall_pass else "✗"
        len_mark = "✓" if r.length_ok else "✗"
        reg_mark = "✓" if r.register_ok else "✗"
        lines.append(
            f"| `{r.case_id}` | `{r.npc_id}` | {pass_mark} | "
            f"{r.voice_score:.2f} | {r.lint_hits} | {len_mark} | "
            f"{reg_mark} | {r.elapsed_ms:.0f}ms |"
        )
    # Per-case diagnostics
    lines.append("")
    for r in report.results:
        lines.append(f"### `{r.case_id}` — {r.npc_id}")
        lines.append("")
        lines.append(f"**prompt:** {r.prompt}")
        lines.append("")
        if r.text:
            lines.append(f"**reply:** {r.text}")
        else:
            lines.append("**reply:** _(no output)_")
        if r.lint_notes:
            lines.append("")
            lines.append("**notes:**")
            for note in r.lint_notes:
                lines.append(f"- {note}")
        lines.append("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Canonical suite for Rusted Lantern
# ---------------------------------------------------------------------------


def default_rusted_lantern_cases() -> list[EvalCase]:
    """20-case golden suite exercising voice, relationships, knowledge
    gates, and context-neutral probes across the five cast members."""
    return [
        # Mira (pragmatic tavernkeeper)
        EvalCase(id="mira_greet", npc_id="mira_vesser",
                 prompt="Evening. Pour me a drink."),
        EvalCase(id="mira_ask_deep", npc_id="mira_vesser",
                 prompt="Tell me about the deep."),
        EvalCase(id="mira_flirt", npc_id="mira_vesser",
                 prompt="You've got a kind face, you know."),
        EvalCase(id="mira_nonsense", npc_id="mira_vesser",
                 prompt="What's the square root of a pigeon?",
                 forbid_phrases=["square root"]),

        # Gereth (traumatised miner)
        EvalCase(id="gereth_greet", npc_id="gereth_blackstone",
                 prompt="Good evening."),
        EvalCase(id="gereth_crew", npc_id="gereth_blackstone",
                 prompt="How many came out of the mine with you?"),
        EvalCase(id="gereth_locket", npc_id="gereth_blackstone",
                 prompt="What's the locket for?"),

        # Adelie (cleric)
        EvalCase(id="adelie_greet", npc_id="sister_adelie",
                 prompt="Good evening, sister."),
        EvalCase(id="adelie_order", npc_id="sister_adelie",
                 prompt="What's the Moon Court want with Emberfall?"),
        EvalCase(id="adelie_lie", npc_id="sister_adelie",
                 prompt="I've never set foot in the mines.",
                 forbid_phrases=["liar"]),

        # Kess (con-artist)
        EvalCase(id="kess_price", npc_id="kess_the_knife",
                 prompt="What's your price for a Hawksreach silk?"),
        EvalCase(id="kess_name", npc_id="kess_the_knife",
                 prompt="What's your real name?"),
        EvalCase(id="kess_trust", npc_id="kess_the_knife",
                 prompt="Can I trust you?"),

        # Ulrik (observer)
        EvalCase(id="ulrik_greet", npc_id="ulrik_the_old_man",
                 prompt="You're quiet tonight."),
        EvalCase(id="ulrik_stars", npc_id="ulrik_the_old_man",
                 prompt="What do you see in those star-maps?"),
        EvalCase(id="ulrik_player", npc_id="ulrik_the_old_man",
                 prompt="Tell me what you think of me."),

        # Cross-NPC world probes
        EvalCase(id="mira_moon_court", npc_id="mira_vesser",
                 prompt="What can you tell me about the Moon Court?"),
        EvalCase(id="gereth_mira", npc_id="gereth_blackstone",
                 prompt="Do you trust Mira?"),
        EvalCase(id="adelie_deep", npc_id="sister_adelie",
                 prompt="What did you see in the deep?"),
        EvalCase(id="kess_adelie", npc_id="kess_the_knife",
                 prompt="You ever cross a Silent Order cleric?"),
    ]
