"""Generation pipeline — walk-up dialogue + bark libraries.

Walk-up:
    One afterimage ``ConversationGenerator`` run per ``(NPC, intent)`` with a
    single-intent persona pool, so coverage is deterministic (no reliance on
    persona cycling across concurrent calls).

Barks:
    One ``LLMFactory.agenerate_structured`` call per bark variant, parallel
    via ``asyncio.gather`` with a per-NPC semaphore. Returns Pydantic
    ``BarkLine`` objects directly.

Both modes share ``run_all``, which writes Yarn files + a ``manifest.json``
with content hashes so downstream diffing is cheap.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Literal

from afterimage import (
    ConversationGenerator,
    InMemoryDocumentProvider,
    PersonaInstructionGeneratorCallback,
)
from afterimage.common import default_model_name as _AFTERIMAGE_DEFAULT_MODEL
from afterimage.providers import LLMFactory
from afterimage.storage import JSONLStorage
from afterimage.types import PersonaEntry

logger = logging.getLogger(__name__)

from .lint import LintReport, lint_barks, lint_walk_up_branches
from .manifest import (
    BarkTriggerEntry,
    LintSummary,
    Manifest,
    NpcEntry,
    NpcWalkUpEntry,
    WorldEntry,
)
from .prompts import (
    build_bark_respondent_prompt,
    build_npc_respondent_prompt,
    render_character_sheet,
    render_player_intent,
)
from .schemas import (
    BarkLine,
    BarksConfig,
    BarkTrigger,
    NpcBarkConfig,
    NpcSheet,
    PlayerIntent,
    resolve_intents_for_npc,
)
from .state import ProjectVariable, yarn_declare_block
from .voice_score import score_voice_consistency
from .yarn import (
    Branch,
    DialogTurn,
    bark_node_title,
    render_bark_node,
    render_world_start_node,
    render_yarn_node_for_npc,
)


Mode = Literal["walk_up", "barks", "all"]


# ---------------------------------------------------------------------------
# Walk-up dialogue
# ---------------------------------------------------------------------------


def _build_provider(
    world_bible: str,
    npc: NpcSheet,
    intent: PlayerIntent,
) -> InMemoryDocumentProvider:
    """Single-document provider seeded with exactly one intent persona."""
    doc_text = f"{world_bible}\n\n---\n\n{render_character_sheet(npc)}"
    provider = InMemoryDocumentProvider([doc_text])
    doc = provider.get_all()[0]
    doc.personas = [
        PersonaEntry(
            descriptions=[render_player_intent(intent)],
            metadata={"generation_depth": 0},
        )
    ]
    return provider


async def generate_branch(
    *,
    npc: NpcSheet,
    intent: PlayerIntent,
    world_bible: str,
    api_key: str,
    model_name: str | None,
    model_provider_name: str,
    max_turns: int,
    out_path: Path,
) -> Branch:
    """Run one Correspondent↔Respondent loop for (NPC, intent) and return the branch."""
    provider = _build_provider(world_bible, npc, intent)

    instruction_cb = PersonaInstructionGeneratorCallback(
        api_key=api_key,
        documents=provider,
        model_name=model_name,
        model_provider_name=model_provider_name,
        num_random_contexts=1,
        n_instructions=1,
    )
    storage = JSONLStorage(conversations_path=str(out_path))
    generator = ConversationGenerator(
        respondent_prompt=build_npc_respondent_prompt(npc),
        api_key=api_key,
        model_name=model_name,
        model_provider_name=model_provider_name,
        instruction_generator_callback=instruction_cb,
        storage=storage,
    )
    await generator.generate(num_dialogs=1, max_turns=max_turns, max_concurrency=1)

    conversations = generator.load_conversations()
    turns: list[DialogTurn] = []
    for conv in reversed(conversations):
        persona_text = (getattr(conv, "persona", "") or "").lower()
        if intent.id.lower() in persona_text or intent.name.lower() in persona_text:
            turns = [{"role": t.role, "content": t.content} for t in conv.conversations]
            break
    return intent, turns


async def generate_for_npc(
    *,
    npc: NpcSheet,
    intents: list[PlayerIntent],
    world_bible: str,
    api_key: str,
    model_name: str | None,
    model_provider_name: str,
    max_turns: int,
    max_concurrency: int,
    out_path: Path,
) -> list[Branch]:
    """Generate one branch per resolved intent for this NPC (parallel, bounded)."""
    out_path.unlink(missing_ok=True)
    resolved = resolve_intents_for_npc(npc, intents)
    if not resolved:
        return []

    semaphore = asyncio.Semaphore(max(max_concurrency, 1))

    async def _bounded(intent: PlayerIntent) -> Branch:
        async with semaphore:
            return await generate_branch(
                npc=npc,
                intent=intent,
                world_bible=world_bible,
                api_key=api_key,
                model_name=model_name,
                model_provider_name=model_provider_name,
                max_turns=max_turns,
                out_path=out_path,
            )

    results = await asyncio.gather(*(_bounded(i) for i in resolved))
    return [r for r in results if r[1]]


# ---------------------------------------------------------------------------
# Barks
# ---------------------------------------------------------------------------


_BARK_USER_PROMPT = (
    "Produce one bark for the trigger above. Return JSON matching the schema.\n"
    "Be surprising but consistent with this specific character — not a generic NPC."
)


async def _generate_one_bark(
    *,
    npc: NpcSheet,
    trigger: BarkTrigger,
    api_key: str,
    model_name: str | None,
    model_provider_name: str,
    temperature: float,
) -> BarkLine | None:
    """Single LLM call for one bark variant.

    Returns ``None`` on any failure after logging the error so callers can
    trace it. We fall back to ``afterimage.common.default_model_name`` when
    the caller did not specify a model — matching what ``ConversationGenerator``
    does internally — because provider classes ship with older defaults.
    """
    effective_model = model_name or _AFTERIMAGE_DEFAULT_MODEL
    llm = LLMFactory.create(
        provider=model_provider_name,
        model_name=effective_model,
        api_key=api_key,
        system_instruction=build_bark_respondent_prompt(npc, trigger),
    )
    try:
        response = await llm.agenerate_structured(
            prompt=_BARK_USER_PROMPT,
            schema=BarkLine,
            temperature=temperature,
        )
    except Exception as exc:
        logger.warning(
            "bark generation failed for %s/%s: %s", npc.id, trigger.id, exc
        )
        return None
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, BarkLine):
        return parsed
    # Fallback: some providers return the JSON text only.
    try:
        return BarkLine.model_validate_json(response.text)
    except Exception as exc:
        logger.warning(
            "bark JSON parse failed for %s/%s: %s", npc.id, trigger.id, exc
        )
        return None


async def generate_barks_for_npc_trigger(
    *,
    npc: NpcSheet,
    trigger: BarkTrigger,
    api_key: str,
    model_name: str | None,
    model_provider_name: str,
    max_concurrency: int = 4,
    temperature: float = 0.95,
) -> list[BarkLine]:
    """Generate ``trigger.n`` unique-ish barks in parallel.

    Deduplicates on exact lowercase text so the caller receives a clean set.
    Returns fewer than requested if dedup / failures reduce yield.
    """
    semaphore = asyncio.Semaphore(max(max_concurrency, 1))

    async def _bounded() -> BarkLine | None:
        async with semaphore:
            return await _generate_one_bark(
                npc=npc,
                trigger=trigger,
                api_key=api_key,
                model_name=model_name,
                model_provider_name=model_provider_name,
                temperature=temperature,
            )

    raw = await asyncio.gather(*(_bounded() for _ in range(trigger.n)))
    seen: set[str] = set()
    out: list[BarkLine] = []
    for bark in raw:
        if bark is None:
            continue
        key = bark.text.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(bark)
    return out


# ---------------------------------------------------------------------------
# Top-level driver (used by CLI; importable from notebooks / tests)
# ---------------------------------------------------------------------------


def _sheet_hash(npc: NpcSheet) -> str:
    blob = npc.model_dump_json(exclude_none=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _filter_npcs(npcs: list[NpcSheet], only: Iterable[str] | None) -> list[NpcSheet]:
    if not only:
        return npcs
    allow = {n.strip() for n in only if n.strip()}
    return [n for n in npcs if n.id in allow]


def _bark_triggers_for(
    barks_cfg: BarksConfig, npc_id: str
) -> list[BarkTrigger]:
    for entry in barks_cfg.barks:
        if entry.npc == npc_id:
            return entry.triggers
    return []


async def run_all(
    *,
    npcs: list[NpcSheet],
    intents: list[PlayerIntent],
    world_bible: str,
    api_key: str,
    out_dir: Path,
    barks_config: BarksConfig | None = None,
    variables: list[ProjectVariable] | None = None,
    mode: Mode = "walk_up",
    only_npcs: Iterable[str] | None = None,
    model_provider_name: str = "gemini",
    model_name: str | None = None,
    max_turns: int = 3,
    intent_concurrency: int = 3,
    bark_concurrency: int = 4,
    score_voice: bool = False,
    progress: bool = True,
) -> Manifest:
    """End-to-end driver for walk-up dialogue and/or bark libraries.

    Returns a typed :class:`Manifest` (also written to
    ``out_dir / "manifest.json"``). When ``score_voice`` is true, every
    walk-up NPC gets per-intent voice-consistency scores computed via
    :func:`npcforge.voice_score.score_voice_consistency` and surfaced in
    the manifest.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    selected = _filter_npcs(npcs, only_npcs)
    if not selected:
        raise ValueError(
            "No NPCs to process. Check --only-npcs / characters.yaml."
        )

    do_walk = mode in ("walk_up", "all")
    do_barks = mode in ("barks", "all")
    barks_cfg = barks_config or BarksConfig()

    started_at = datetime.now(timezone.utc).isoformat()
    start_perf = time.perf_counter()
    lint_report = LintReport()
    npc_entries: dict[str, NpcEntry] = {}
    world_entry: WorldEntry | None = None

    for npc in selected:
        entry = NpcEntry(sheet_hash=_sheet_hash(npc))

        if do_walk:
            jsonl_path = out_dir / f"{npc.id}.jsonl"
            yarn_path = out_dir / f"{npc.id}.yarn"
            if progress:
                resolved = resolve_intents_for_npc(npc, intents)
                print(f"[{npc.id}] walk_up: {len(resolved)} intents ...")
            branches = await generate_for_npc(
                npc=npc,
                intents=intents,
                world_bible=world_bible,
                api_key=api_key,
                model_name=model_name,
                model_provider_name=model_provider_name,
                max_turns=max_turns,
                max_concurrency=intent_concurrency,
                out_path=jsonl_path,
            )
            if branches:
                yarn_path.write_text(
                    render_yarn_node_for_npc(npc, branches), encoding="utf-8"
                )
                lint_report.hits.extend(lint_walk_up_branches(npc, branches))
                voice_scores: dict[str, float] = {}
                if score_voice:
                    voice_scores = await score_voice_consistency(
                        npc=npc,
                        branches=branches,
                        api_key=api_key,
                        provider=model_provider_name,
                    )
                entry.walk_up = NpcWalkUpEntry(
                    yarn=yarn_path.name,
                    yarn_hash=_file_hash(yarn_path),
                    intents=[intent.id for intent, _ in branches],
                    branch_count=len(branches),
                    voice_scores=voice_scores,
                )
                if progress:
                    score_note = ""
                    if voice_scores:
                        avg = sum(voice_scores.values()) / len(voice_scores)
                        score_note = f"  voice~{avg:.2f}"
                    print(
                        f"[{npc.id}] walk_up wrote {yarn_path.name} "
                        f"({len(branches)} branches){score_note}"
                    )
            elif progress:
                print(f"[{npc.id}] walk_up: no branches produced; skipping .yarn")

        if do_barks:
            triggers = _bark_triggers_for(barks_cfg, npc.id)
            for trigger in triggers:
                if progress:
                    print(
                        f"[{npc.id}] barks '{trigger.id}': target {trigger.n} ..."
                    )
                barks = await generate_barks_for_npc_trigger(
                    npc=npc,
                    trigger=trigger,
                    api_key=api_key,
                    model_name=model_name,
                    model_provider_name=model_provider_name,
                    max_concurrency=bark_concurrency,
                )
                if not barks:
                    if progress:
                        print(f"[{npc.id}] barks '{trigger.id}': none produced")
                    continue

                bark_yarn_path = out_dir / f"{npc.id}_bark_{trigger.id}.yarn"
                bark_yarn_path.write_text(
                    render_bark_node(npc, trigger, barks), encoding="utf-8"
                )
                bark_json_path = out_dir / f"{npc.id}_bark_{trigger.id}.json"
                bark_json_path.write_text(
                    json.dumps(
                        {
                            "npc": npc.id,
                            "trigger": trigger.id,
                            "node_title": bark_node_title(npc.id, trigger.id),
                            "barks": [b.model_dump() for b in barks],
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                lint_report.hits.extend(lint_barks(npc, trigger.id, barks))
                entry.barks.append(
                    BarkTriggerEntry(
                        trigger=trigger.id,
                        requested=trigger.n,
                        produced=len(barks),
                        yarn=bark_yarn_path.name,
                        yarn_hash=_file_hash(bark_yarn_path),
                        json_path=bark_json_path.name,
                    )
                )
                if progress:
                    print(
                        f"[{npc.id}] barks '{trigger.id}': {len(barks)}/"
                        f"{trigger.n} unique"
                    )

        npc_entries[npc.id] = entry

    if do_walk and not only_npcs:
        world_path = out_dir / "world.yarn"
        declares = yarn_declare_block(variables or [])
        world_path.write_text(
            render_world_start_node(selected, declare_lines=declares),
            encoding="utf-8",
        )
        world_entry = WorldEntry(
            yarn=world_path.name, yarn_hash=_file_hash(world_path)
        )
        if progress:
            print(f"Wrote {world_path.name}")

    lint_md = out_dir / "lint.md"
    lint_md.write_text(lint_report.format_markdown(), encoding="utf-8")

    manifest = Manifest(
        version="0.5.0",
        generated_at=started_at,
        provider=model_provider_name,
        model=model_name,
        mode=mode,
        npcs=npc_entries,
        world=world_entry,
        lint=LintSummary(markdown=lint_md.name, total_hits=lint_report.total),
        elapsed_seconds=round(time.perf_counter() - start_perf, 2),
        voice_scoring_enabled=score_voice,
    )

    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    if progress:
        print(
            f"Manifest: {manifest_path.name}  "
            f"(lint hits: {lint_report.total}, "
            f"elapsed: {manifest.elapsed_seconds}s)"
        )
    return manifest
