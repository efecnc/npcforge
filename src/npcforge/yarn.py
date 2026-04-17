"""Yarn Spinner 2.0 exporter.

Produces one node per NPC with one ``-> [archetype]`` option per player stance,
plus a shared end node. A separate :func:`render_world_start_node` emits a
master ``Start`` node that routes to each NPC.

The exporter is pure — it does not touch the filesystem. Callers write the
returned strings wherever they want.
"""

from __future__ import annotations

import re
from typing import Iterable

from .schemas import NpcSheet, PlayerArchetype


# A "turn" is a lightweight dict because it is the shape afterimage hands back:
# ``{"role": "assistant" | "user", "content": str}``. We keep it ``dict``-shaped
# here so callers don't have to build an npcforge-specific wrapper.
DialogTurn = dict
Branch = tuple[PlayerArchetype, list[DialogTurn]]


_YARN_SEP = "==="
_YARN_TITLE = "title: "
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


def render_yarn_branch(
    archetype: PlayerArchetype,
    npc_name: str,
    turns: Iterable[DialogTurn],
    end_title: str,
) -> list[str]:
    """Render one Yarn option block for ``archetype`` × ``npc_name``.

    Emits alternating ``Player: ...`` and ``<npc_name>: ...`` lines inside an
    option body, then a ``<<jump end_title>>``.
    """
    label = archetype.name.replace("\n", " ")
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
    """Render the full Yarn node (options + end node) for one NPC.

    No synthetic "shared greeting" is emitted because each archetype provokes
    a different reply — the NPC's first line lives inside each branch.
    """
    title = yarn_safe_title(npc.id)
    end_title = f"{title}_End"

    out: list[str] = [f"{_YARN_TITLE}{title}", "---"]
    out.append(f"{npc.name} waits. How do you approach them?")

    for archetype, turns in branches:
        out.extend(render_yarn_branch(archetype, npc.name, turns, end_title))

    out.append(_YARN_SEP)
    out.extend(
        [
            f"{_YARN_TITLE}{end_title}",
            "---",
            f"{npc.name}: (returns to their work)",
            _YARN_SEP,
        ]
    )
    return "\n".join(out) + "\n"


def render_world_start_node(npcs: list[NpcSheet]) -> str:
    """Emit a master ``Start`` node with one option per NPC."""
    out: list[str] = [f"{_YARN_TITLE}Start", "---"]
    out.append(
        "You step inside. Firelight, low voices, a hush that settles when you arrive."
    )
    out.append("Someone you came to speak with is here. Who do you approach?")
    for npc in npcs:
        title = yarn_safe_title(npc.id)
        out.append(f"-> {npc.name} — {npc.role}")
        out.append(f"    <<jump {title}>>")
    out.append(_YARN_SEP)
    return "\n".join(out) + "\n"
