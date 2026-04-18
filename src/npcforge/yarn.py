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


def render_world_start_node(
    npcs: list[NpcSheet],
    declare_lines: list[str] | None = None,
) -> str:
    """Master ``Start`` node with one option per NPC.

    When ``declare_lines`` is provided (from :func:`npcforge.state.yarn_declare_block`)
    each line is emitted at the top of the node body — Yarn Spinner requires
    ``<<declare>>`` statements before any dialogue lines.
    """
    out: list[str] = [f"{_YARN_TITLE}Start", _YARN_TAGS + "start", "---"]
    if declare_lines:
        out.extend(declare_lines)
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
# State-aware greeting node (v0.6.0)
# ---------------------------------------------------------------------------


def greeting_node_title(npc_id: str, variable_id: str) -> str:
    """Deterministic Yarn title for an NPC's state-variant greeting node."""
    return yarn_safe_title(f"{npc_id}_Greet_{variable_id}")


def repeat_greeting_node_title(npc_id: str) -> str:
    """Deterministic Yarn title for an NPC's visit-counter greeting node."""
    return yarn_safe_title(f"{npc_id}_RepeatGreet")


def render_repeat_greeting_node(
    npc: NpcSheet,
    variants: list[str],
) -> str:
    """Render a Yarn node that plays one greeting per visit count.

    ``variants`` is ordered: index 0 is visit #0 (stranger), index 1 is
    visit #1, and the final entry is the ``else`` fallback played on every
    subsequent visit.

    Output shape (for three variants):

    ::

        title: mira_vesser_RepeatGreet
        tags: repeat_greeting,npc:mira_vesser
        ---
        <<if visited_count("mira_vesser_RepeatGreet") == 0>>
            Mira Vesser: First time I've seen that face. Drink?
        <<elseif visited_count("mira_vesser_RepeatGreet") == 1>>
            Mira Vesser: Back already, friend?
        <<else>>
            Mira Vesser: The Lantern remembers you now.
        <<endif>>
        ===
    """
    title = repeat_greeting_node_title(npc.id)
    lines: list[str] = [
        f"{_YARN_TITLE}{title}",
        _YARN_TAGS + f"repeat_greeting,npc:{npc.id}",
        "---",
        f"// Repeat-greeting variants keyed on visited_count(\"{title}\").",
    ]
    if not variants:
        lines.extend([f"{npc.name}: ...", _YARN_SEP])
        return "\n".join(lines) + "\n"

    total = len(variants)
    for idx, text in enumerate(variants):
        body = yarn_escape_line(text)
        if total == 1:
            lines.append(f"{npc.name}: {body}")
            break
        if idx == total - 1:
            # Final variant is the else-fallback played on every later visit.
            lines.append("<<else>>")
            lines.append(f"    {npc.name}: {body}")
            lines.append("<<endif>>")
            break
        if idx == 0:
            lines.append(f'<<if visited_count("{title}") == 0>>')
        else:
            lines.append(f'<<elseif visited_count("{title}") == {idx}>>')
        lines.append(f"    {npc.name}: {body}")

    lines.append(_YARN_SEP)
    return "\n".join(lines) + "\n"


def render_greetings_node(
    npc: NpcSheet,
    variable_id: str,
    variants: list[tuple[str, str]],
) -> str:
    """Render a Yarn node that emits one line per value of a project variable.

    ``variants`` is an ordered list of ``(value, greeting_text)`` pairs.
    Output shape (for ``variable_id='time_of_day'``):

    ::

        title: mira_vesser_Greet_time_of_day
        tags: greeting,variable:time_of_day,npc:mira_vesser
        ---
        <<if $time_of_day == "dawn">>
            Mira Vesser: Early, friend. Ale or coffee?
        <<elseif $time_of_day == "morning">>
            Mira Vesser: Morning. Fire's lit.
        <<elseif $time_of_day == "night">>
            Mira Vesser: Late. Kitchen's closed.
        <<else>>
            Mira Vesser: (nods)
        <<endif>>
        ===
    """
    title = greeting_node_title(npc.id, variable_id)
    lines: list[str] = [
        f"{_YARN_TITLE}{title}",
        _YARN_TAGS + f"greeting,variable:{variable_id},npc:{npc.id}",
        "---",
        f"// Greeting variants keyed on ${variable_id}.",
    ]
    if not variants:
        lines.extend([f"{npc.name}: ...", _YARN_SEP])
        return "\n".join(lines) + "\n"

    total = len(variants)
    for idx, (value, text) in enumerate(variants):
        literal = yarn_escape_line(value)
        body = yarn_escape_line(text)
        if idx == 0:
            lines.append(f'<<if ${variable_id} == "{literal}">>')
        elif idx == total - 1:
            lines.append(f'<<elseif ${variable_id} == "{literal}">>')
            lines.append(f"    {npc.name}: {body}")
            lines.append("<<else>>")
            lines.append(f"    {npc.name}: ...")
            lines.append("<<endif>>")
            lines.append(_YARN_SEP)
            return "\n".join(lines) + "\n"
        else:
            lines.append(f'<<elseif ${variable_id} == "{literal}">>')
        lines.append(f"    {npc.name}: {body}")
    # With a single variant we never hit the final branch above.
    lines.append("<<else>>")
    lines.append(f"    {npc.name}: ...")
    lines.append("<<endif>>")
    lines.append(_YARN_SEP)
    return "\n".join(lines) + "\n"


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
