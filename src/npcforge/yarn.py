"""Yarn Spinner 2.0 exporter.

Emits:
    - one node per NPC with one ``-> [intent]`` option per player intent
    - per-NPC end nodes
    - a master ``Start`` node routing to every NPC
    - per-(NPC, trigger) bark nodes with visited-counter variant selection

The exporter is pure — no filesystem access. Callers write strings wherever
they want.
"""

from __future__ import annotations

import re
from typing import Iterable

from .schemas import BarkLine, BarkTrigger, NpcSheet, PlayerIntent


# A "turn" is a lightweight dict because it is the shape afterimage hands back:
# ``{"role": "assistant" | "user", "content": str}``.
DialogTurn = dict
Branch = tuple[PlayerIntent, list[DialogTurn]]


_YARN_SEP = "==="
_YARN_TITLE = "title: "
_YARN_TAGS = "tags: "
_WHITESPACE_RE = re.compile(r"\s+")
_INVALID_TITLE_RE = re.compile(r"[^0-9a-zA-Z_]+")


def yarn_safe_title(name: str) -> str:
    """Yarn node titles must be ``[a-zA-Z0-9_]`` and may not start with a digit."""
    cleaned = _INVALID_TITLE_RE.sub("_", name).strip("_") or "Untitled"
    if cleaned[0].isdigit():
        cleaned = "N" + cleaned
    return cleaned


def yarn_escape_line(line: str) -> str:
    """Collapse whitespace so one logical Yarn line stays on one physical line."""
    return _WHITESPACE_RE.sub(" ", line).strip()


# ---------------------------------------------------------------------------
# Walk-up dialogue
# ---------------------------------------------------------------------------


def render_yarn_branch(
    intent: PlayerIntent,
    npc_name: str,
    turns: Iterable[DialogTurn],
    end_title: str,
) -> list[str]:
    """One Yarn option block for ``intent`` × ``npc_name``."""
    label = intent.name.replace("\n", " ")
    lines: list[str] = [f"-> [{label}]"]
    for turn in turns:
        content = yarn_escape_line(turn.get("content", ""))
        if not content:
            continue
        speaker = npc_name if turn.get("role") == "assistant" else "Player"
        lines.append(f"    {speaker}: {content}")
    lines.append(f"    <<jump {end_title}>>")
    return lines


def render_yarn_node_for_npc(npc: NpcSheet, branches: list[Branch]) -> str:
    """Full Yarn node (intent options + end node) for one NPC.

    No synthetic "shared greeting" is emitted because each intent provokes a
    different reply — the NPC's first line lives inside each branch.
    """
    title = yarn_safe_title(npc.id)
    end_title = f"{title}_End"

    out: list[str] = [f"{_YARN_TITLE}{title}", _YARN_TAGS + "walk_up", "---"]
    out.append(f"{npc.name} waits. How do you approach them?")

    for intent, turns in branches:
        out.extend(render_yarn_branch(intent, npc.name, turns, end_title))

    out.append(_YARN_SEP)
    out.extend(
        [
            f"{_YARN_TITLE}{end_title}",
            _YARN_TAGS + "walk_up,end",
            "---",
            f"{npc.name}: (returns to their work)",
            _YARN_SEP,
        ]
    )
    return "\n".join(out) + "\n"


def render_world_start_node(npcs: list[NpcSheet]) -> str:
    """Master ``Start`` node with one option per NPC."""
    out: list[str] = [f"{_YARN_TITLE}Start", _YARN_TAGS + "start", "---"]
    out.append(
        "You step inside. Firelight, low voices, a hush that settles when you arrive."
    )
    out.append("Someone you came to speak with is here. Who do you approach?")
    for npc in npcs:
        out.append(f"-> {npc.name} — {npc.role}")
        out.append(f"    <<jump {yarn_safe_title(npc.id)}>>")
    out.append(_YARN_SEP)
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# Barks
# ---------------------------------------------------------------------------


def bark_node_title(npc_id: str, trigger_id: str) -> str:
    """Deterministic Yarn title for a bark library node."""
    return yarn_safe_title(f"{npc_id}_Bark_{trigger_id}")


def render_bark_node(
    npc: NpcSheet,
    trigger: BarkTrigger,
    barks: list[BarkLine],
) -> str:
    """Yarn 2.0 bark library node.

    Uses the ``visited()`` counter pattern so each visit plays the next variant
    and wraps around. Tags identify it as a bark for runtime selectors.

    Game runtimes typically call something like ``<<jump NpcId_Bark_Trigger>>``
    from a combat system, ambient system, witness system, etc.
    """
    title = bark_node_title(npc.id, trigger.id)
    out: list[str] = [
        f"{_YARN_TITLE}{title}",
        _YARN_TAGS + f"bark,trigger:{trigger.id},npc:{npc.id}",
        "---",
        f"// Bark library: {len(barks)} variants for trigger '{trigger.id}'",
        f"// Trigger context: {yarn_escape_line(trigger.description)}",
    ]

    total = max(len(barks), 1)
    for idx, bark in enumerate(barks):
        text = yarn_escape_line(bark.text)
        # Deterministic rotation via visited() counter. Final branch uses `else`
        # to keep the node valid if someone adds barks later without updating.
        if idx == 0:
            out.append(f"<<if visited_count(\"{title}\") % {total} == 0>>")
        elif idx == total - 1:
            out.append("<<else>>")
        else:
            out.append(f"<<elseif visited_count(\"{title}\") % {total} == {idx}>>")
        out.append(
            f"    {npc.name}: {text}  // emotion={bark.emotion} intensity={bark.intensity}"
        )
    if barks:
        out.append("<<endif>>")

    out.append(_YARN_SEP)
    return "\n".join(out) + "\n"
