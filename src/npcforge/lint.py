"""Voice-ceiling lint: scan generated text for forbidden-word hits.

Runs in-process after generation and produces a structured report a writer
can scan. Does not make network calls.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from .schemas import BarkLine, NpcSheet


@dataclass
class ForbiddenHit:
    """A single forbidden-word match found in generated text."""

    npc_id: str
    word: str  # the forbidden-word template (not the matched substring)
    snippet: str  # ~60 chars of context around the match
    location: str  # "walk_up:<intent_id>:turn_<n>" or "bark:<trigger_id>:<n>"


@dataclass
class LintReport:
    """Aggregated lint output for a whole run."""

    hits: list[ForbiddenHit] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.hits)

    def by_npc(self) -> dict[str, list[ForbiddenHit]]:
        grouped: dict[str, list[ForbiddenHit]] = {}
        for hit in self.hits:
            grouped.setdefault(hit.npc_id, []).append(hit)
        return grouped

    def format_markdown(self) -> str:
        """Writer-facing Markdown summary."""
        if not self.hits:
            return "## Voice-Ceiling Lint\n\nNo forbidden-word hits. Clean run.\n"
        lines = ["## Voice-Ceiling Lint", ""]
        lines.append(f"**Total hits:** {self.total}")
        lines.append("")
        for npc_id, group in self.by_npc().items():
            lines.append(f"### {npc_id}  ({len(group)} hit{'s' if len(group) != 1 else ''})")
            lines.append("")
            for hit in group:
                lines.append(
                    f"- `{hit.word}` in **{hit.location}** — "
                    f"`{hit.snippet.strip()}`"
                )
            lines.append("")
        return "\n".join(lines) + "\n"


def _compile_forbidden_regex(words: Iterable[str]) -> re.Pattern | None:
    """Compile a case-insensitive whole-word alternation for the forbidden list.

    Matches the stem as a whole word plus common English inflections
    (``-s``, ``-es``, ``-ed``, ``-ing``). Returns ``None`` for empty input.
    """
    cleaned = [w.strip() for w in words if w.strip()]
    if not cleaned:
        return None
    stems = "|".join(re.escape(w) for w in cleaned)
    # Common English inflections. ``d`` catches past tense of stems ending in
    # ``e`` (``fascinate`` → ``fascinated``); the rest handle plural / verb
    # conjugation / gerund forms.
    pattern = rf"\b(?:{stems})(?:s|es|d|ed|ing)?\b"
    return re.compile(pattern, re.IGNORECASE)


def _snippet(text: str, start: int, end: int, pad: int = 30) -> str:
    s = max(0, start - pad)
    e = min(len(text), end + pad)
    prefix = "..." if s > 0 else ""
    suffix = "..." if e < len(text) else ""
    return f"{prefix}{text[s:e]}{suffix}"


def lint_text(
    npc: NpcSheet,
    text: str,
    location: str,
) -> list[ForbiddenHit]:
    """Scan one blob of text for forbidden-word hits by ``npc``."""
    pattern = _compile_forbidden_regex(npc.forbidden_words)
    if pattern is None or not text:
        return []
    hits: list[ForbiddenHit] = []
    seen: set[str] = set()
    for match in pattern.finditer(text):
        key = f"{match.start()}:{match.group(0).lower()}"
        if key in seen:
            continue
        seen.add(key)
        hits.append(
            ForbiddenHit(
                npc_id=npc.id,
                word=match.group(0),
                snippet=_snippet(text, match.start(), match.end()),
                location=location,
            )
        )
    return hits


def lint_walk_up_branches(
    npc: NpcSheet,
    branches: list[tuple[object, list[dict]]],
) -> list[ForbiddenHit]:
    """Lint every assistant turn across every intent branch for this NPC."""
    hits: list[ForbiddenHit] = []
    for intent, turns in branches:
        intent_id = getattr(intent, "id", "unknown")
        for idx, turn in enumerate(turns):
            if turn.get("role") != "assistant":
                continue
            hits.extend(
                lint_text(
                    npc,
                    turn.get("content", ""),
                    location=f"walk_up:{intent_id}:turn_{idx}",
                )
            )
    return hits


def lint_barks(
    npc: NpcSheet,
    trigger_id: str,
    barks: list[BarkLine],
) -> list[ForbiddenHit]:
    """Lint every bark variant for a given trigger."""
    hits: list[ForbiddenHit] = []
    for idx, bark in enumerate(barks):
        hits.extend(
            lint_text(npc, bark.text, location=f"bark:{trigger_id}:{idx}")
        )
    return hits
