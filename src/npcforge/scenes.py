"""Multi-NPC scenes (v0.9.0 — social graph).

A *scene* is a short generated exchange between two or more NPCs,
optionally with player-interjection points. Unlike walk-up dialogue
(player × one NPC) or barks (one-shot reactive utterances), a scene
lets the social graph breathe: two NPCs who have a declared
relationship or a faction rivalry talk to each other while the player
listens or chimes in.

Generation flow:

1. :func:`build_scene_system_prompt` assembles the scene brief into a
   single system prompt that includes every participating NPC's
   character sheet, their faction affiliations, and the (optional)
   memory summary for each.
2. The afterimage adapter produces a :class:`SceneDialogue` via
   structured output — a list of lines plus any number of
   player-interjection blocks.
3. :func:`render_scene_yarn` flattens the structured result into a
   Yarn Spinner node the runtime can execute verbatim.

We deliberately keep the schema tight: 6–10 main lines, 0–3
player-interjection points. Longer scenes trend toward the LLM losing
voice consistency across all participants; shorter scenes have no
social dynamics worth modelling.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from .memory import MemoryStore, summarize_for_npc
from .narrative_scope import LayersConfig
from .prompts import render_character_sheet
from .schemas import FactionsConfig, NpcSheet


# ---------------------------------------------------------------------------
# Scene definition (what the writer / CLI specifies)
# ---------------------------------------------------------------------------


class Scene(BaseModel):
    """Writer-supplied scene brief.

    ``participants`` must contain at least two NPC ids. The first one is
    treated as the "focus" NPC (the one the player would nominally
    approach); others are secondary voices in the room.

    ``setup`` is the situational beat — the single sentence that answers
    "what's just happened in this room that makes this conversation
    worth witnessing". It's the most important field.
    """

    id: str = Field(..., description="Unique scene id (lower_snake_case).")
    location: str = Field(..., description="One-phrase location label.")
    participants: list[str] = Field(..., min_length=2)
    setup: str = Field(
        ...,
        description=(
            "One sentence capturing the pre-conditions: 'A Guild inspector "
            "has just walked into the common room' or 'Gereth has shown up "
            "drunk for the first time in two years'."
        ),
    )
    player_present: bool = Field(
        default=True,
        description=(
            "If true, generated output may include 1–3 player-interjection "
            "branches; if false, the NPCs speak among themselves and the "
            "player is expected to listen only."
        ),
    )
    max_lines: int = Field(
        default=8,
        ge=4,
        le=14,
        description=(
            "Target length for the main exchange. LLM treats this as soft "
            "guidance; the structured schema lets it vary within ±2."
        ),
    )


# ---------------------------------------------------------------------------
# Structured output (what the LLM returns)
# ---------------------------------------------------------------------------


Speaker = str  # Constrained at validation time to npc_id|"Player" per scene.


class SceneLine(BaseModel):
    speaker: Speaker = Field(
        ...,
        description=(
            "Either one of the participant NPC ids or the literal string "
            "'Player'. Any other value is rejected at post-processing."
        ),
    )
    text: str = Field(..., description="One-sentence utterance in character.")
    # Optional inter-character beat — an emotion hint the runtime can use
    # for camera work / SFX. NOT audio cues — just dramatic tagging.
    beat: Literal[
        "neutral", "tense", "warm", "cold", "amused",
        "cautious", "resigned", "urgent",
    ] = "neutral"


class ScenePlayerChoice(BaseModel):
    """Optional branch triggered by the player interjecting.

    The LLM places 0–3 of these inside the main exchange. When the
    player picks one, the listed ``lines`` play, then the scene
    resumes (we jump back into the main exchange after).
    """

    label: str = Field(
        ...,
        description=(
            "Short action phrase: 'Clear your throat', 'Step between them', "
            "'Say nothing'. This is what the player picks, not what they say."
        ),
    )
    lines: list[SceneLine] = Field(default_factory=list, max_length=4)


class SceneDialogue(BaseModel):
    """Structured LLM output for one scene."""

    main: list[SceneLine] = Field(..., min_length=4, max_length=14)
    choices: list[ScenePlayerChoice] = Field(default_factory=list, max_length=3)


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


def build_scene_system_prompt(
    scene: Scene,
    cast: list[NpcSheet],
    factions: FactionsConfig | None = None,
    memory_store: MemoryStore | None = None,
    layers: LayersConfig | None = None,
) -> str:
    """System prompt for generating a scene.

    Includes every participant's character sheet (with faction context)
    and their memory summary. The rules section is scene-specific: it
    instructs the LLM to honour speech quirks per speaker, respect
    faction allies/rivals, and stop after ~max_lines turns.
    """
    by_id: dict[str, NpcSheet] = {n.id: n for n in cast}
    participants = [by_id[p] for p in scene.participants if p in by_id]
    if len(participants) < 2:
        raise ValueError(
            f"Scene '{scene.id}' must reference at least two NPCs that "
            f"exist in the cast. Got: {scene.participants}"
        )

    sheets: list[str] = []
    for npc in participants:
        sheet = render_character_sheet(npc, cast=cast, factions=factions, layers=layers)
        mem = ""
        if memory_store is not None:
            mem = summarize_for_npc(npc, memory_store)
        if mem:
            sheet = sheet.rstrip() + "\n\n" + mem + "\n"
        sheets.append(sheet)

    joined_sheets = "\n\n---\n\n".join(sheets)
    participant_ids = ", ".join(p.id for p in participants)

    head = (
        "You are the omniscient scene-dialogue generator for a narrative "
        "game. Your job is to script a short exchange between the "
        "NPCs below, in their own voices, reacting to the situation.\n\n"
        f"LOCATION: {scene.location}\n"
        f"PARTICIPANTS: {participant_ids}\n"
        f"SETUP: {scene.setup.strip()}\n"
        f"PLAYER IS PRESENT: {'yes' if scene.player_present else 'no'}\n"
        f"TARGET MAIN-LINE COUNT: {scene.max_lines} (±2 acceptable)\n"
    )

    rules = (
        "Rules for the scripted exchange:\n"
        "1. Every line must be in the voice of the speaker named. Honour\n"
        "   their vocabulary ceiling, forbidden words, speech quirks.\n"
        "2. If two NPCs have a declared relationship, let it surface in\n"
        "   tone (protective → they cover for each other; distrust → one\n"
        "   deflects what the other says).\n"
        "3. Faction affiliation shapes register. An ally in the room\n"
        "   softens the voice; a rival sharpens it. Never narrate the\n"
        "   shift — let it come through in the words chosen.\n"
        "4. Dialogue only. No stage directions, no parentheticals, no\n"
        "   narration. No 'suddenly' 'quietly' 'with a glare' — the line\n"
        "   must do the work on its own.\n"
        "5. Speakers should alternate naturally. The same speaker may have\n"
        "   two lines in a row only when the drama demands it.\n"
        "6. If the player is present and you include player-interjection\n"
        "   choices, each label is a short ACTION ('Clear your throat',\n"
        "   'Step between them') — never a full sentence the player says\n"
        "   aloud. The player's voice inside the branch may be one line\n"
        "   max, phrased naturally.\n"
        "7. Stop at target length ±2 lines. Do not wrap the scene with\n"
        "   exposition.\n"
        "8. If a 'Memory of past encounters' block appears in any NPC's\n"
        "   section, weave one relevant callback into the scene when it\n"
        "   fits naturally. Do not list events.\n"
    )

    return "\n\n".join([head, rules.rstrip(), joined_sheets]) + "\n"


def validate_scene_output(
    scene: Scene, dialogue: SceneDialogue
) -> list[str]:
    """Return a list of human-readable warnings about the scene output.

    Does NOT raise — scene generation is best-effort and we'd rather
    surface the warnings to the writer than force another LLM round-trip.
    """
    allowed_speakers = set(scene.participants)
    if scene.player_present:
        allowed_speakers.add("Player")

    warnings: list[str] = []
    for i, line in enumerate(dialogue.main):
        if line.speaker not in allowed_speakers:
            warnings.append(
                f"main[{i}] speaker '{line.speaker}' not in "
                f"{sorted(allowed_speakers)}"
            )
    for ci, choice in enumerate(dialogue.choices):
        for li, line in enumerate(choice.lines):
            if line.speaker not in allowed_speakers:
                warnings.append(
                    f"choices[{ci}].lines[{li}] speaker "
                    f"'{line.speaker}' not in {sorted(allowed_speakers)}"
                )
    if dialogue.choices and not scene.player_present:
        warnings.append(
            "player_present=False but dialogue contains player-interjection "
            "choices — they will be omitted from the Yarn output"
        )
    return warnings


# ---------------------------------------------------------------------------
# Yarn rendering
# ---------------------------------------------------------------------------


_INVALID_TITLE = re.compile(r"[^0-9a-zA-Z_]+")


def _yarn_title(name: str) -> str:
    cleaned = _INVALID_TITLE.sub("_", name).strip("_") or "Untitled"
    if cleaned[0].isdigit():
        cleaned = "N" + cleaned
    return cleaned


def _display_name_for(speaker: str, cast: list[NpcSheet]) -> str:
    """Resolve 'Player' or an NPC id to the Yarn-line display name."""
    if speaker == "Player":
        return "Player"
    for n in cast:
        if n.id == speaker:
            # Use the first word of the NPC's name (Mira Vesser → "Mira")
            # so Yarn lines read cleanly. Falls back to the full name.
            first = n.name.split()[0] if n.name.strip() else n.id
            return first
    return speaker


def render_scene_yarn(
    scene: Scene,
    dialogue: SceneDialogue,
    cast: list[NpcSheet],
    *,
    end_node: str | None = None,
) -> str:
    """Flatten a :class:`SceneDialogue` into a Yarn Spinner node.

    Output shape::

        title: scene_<id>
        tags: scene
        ---
        Mira: ...
        Gereth: ...
        -> [Clear your throat]
            Player: ...
            Mira: ...
        -> [Say nothing]
            Mira: ...
        Gereth: ...
        <<jump Start>>
        ===

    ``end_node`` is the title the scene jumps to after the last line. If
    None, we fall through (no jump) — the runtime's DialogueRunner stops
    cleanly at end-of-node.
    """
    title = _yarn_title(f"scene_{scene.id}")
    lines: list[str] = [f"title: {title}", "tags: scene"]
    if scene.location:
        # Location isn't a Yarn tag (no spaces allowed) — put it in a
        # header comment so writers can see it in the file.
        lines.append(f"# location: {scene.location}")
    lines.append("---")

    # Main exchange
    for sl in dialogue.main:
        speaker = _display_name_for(sl.speaker, cast)
        lines.append(f"{speaker}: {sl.text.strip()}")

    # Player-interjection branches
    if scene.player_present and dialogue.choices:
        for choice in dialogue.choices:
            lines.append(f"-> [{choice.label.strip()}]")
            for sl in choice.lines:
                speaker = _display_name_for(sl.speaker, cast)
                lines.append(f"    {speaker}: {sl.text.strip()}")

    if end_node:
        lines.append(f"<<jump {_yarn_title(end_node)}>>")
    lines.append("===")
    return "\n".join(lines) + "\n"
