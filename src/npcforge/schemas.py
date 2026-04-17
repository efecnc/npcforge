"""Input schemas and YAML/markdown loaders for npcforge.

v0.2.0 adds player *intents* (finer-grained than archetypes), voice-ceiling
fields on NpcSheet, and bark generation config.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


VocabularyCeiling = Literal[
    "grade_3",
    "grade_5",
    "grade_8",
    "high_school",
    "college",
    "academic",
]


class NpcSheet(BaseModel):
    """A single NPC entry from ``characters.yaml``.

    Required: ``id``, ``name``, ``role``, ``voice``. Everything else is optional.

    Voice-ceiling fields (``forbidden_words``, ``vocabulary_ceiling``,
    ``accent_markers``) are injected into the respondent system prompt and
    also used by :mod:`npcforge.lint` to flag violations in generated text.

    ``allowed_intents`` is an opt-in whitelist of intent ids. When empty, the
    NPC is considered to respond to every intent defined in
    ``player_intents.yaml``.
    """

    id: str
    name: str
    role: str
    voice: str
    background: str = ""
    motivations: list[str] = Field(default_factory=list)
    secret: str = ""
    speech_quirks: list[str] = Field(default_factory=list)
    sample_lines: list[str] = Field(default_factory=list)

    # Voice ceiling (v0.2.0)
    forbidden_words: list[str] = Field(default_factory=list)
    vocabulary_ceiling: VocabularyCeiling | None = None
    accent_markers: list[str] = Field(default_factory=list)

    # Per-NPC intent whitelist (v0.2.0). Empty = all intents allowed.
    allowed_intents: list[str] = Field(default_factory=list)


class NpcStub(BaseModel):
    """A placeholder entry in ``characters.yaml`` that ``resolve_stubs`` fills in.

    Authors write a stub when they want ``gen_npcs``'s style expansion but with
    a stronger seed than a free-text brief — e.g. "here's the id and a
    one-line voice hint; you pick everything else." Loaders keep stubs
    separate from :class:`NpcSheet`; the pipeline ignores stubs entirely.

    Set ``_generate: true`` to opt in. Any of ``name``, ``role``,
    ``voice_hint``, ``role_hint`` are treated as generator seeds.
    """

    id: str
    generate: bool = Field(default=True, alias="_generate")
    name: str = ""
    role: str = ""
    role_hint: str = ""
    voice_hint: str = ""

    model_config = {"populate_by_name": True, "extra": "ignore"}


class PlayerIntent(BaseModel):
    """A single entry from ``player_intents.yaml``.

    Intents describe *what the player is trying to do this turn* (barter,
    intimidate, flirt, ask_for_directions). They are finer-grained than
    "archetypes" (who the player is) — a barter intent will work for any
    class, but a hostile NPC may decline it.
    """

    id: str
    name: str
    description: str
    opening_intent: str = ""


class BarkTrigger(BaseModel):
    """A single bark trigger for one NPC.

    ``id`` becomes the Yarn node title suffix. ``n`` is how many unique
    variants to generate. ``description`` becomes the in-context prompt
    ("the NPC has just witnessed X"), so it should read as a situational
    cue, not a command.
    """

    id: str
    description: str
    n: int = 10


class NpcBarkConfig(BaseModel):
    """Bark config for a single NPC: id + list of triggers."""

    npc: str
    triggers: list[BarkTrigger]


class BarksConfig(BaseModel):
    """Top-level ``barks.yaml`` schema."""

    barks: list[NpcBarkConfig] = Field(default_factory=list)


class BarkLine(BaseModel):
    """One generated bark — structured-output target for the LLM."""

    text: str = Field(
        ...,
        description="The bark utterance. One short sentence. In character.",
    )
    emotion: Literal[
        "neutral",
        "angry",
        "scared",
        "happy",
        "sad",
        "surprised",
        "disgusted",
        "confused",
        "sarcastic",
        "threatening",
        "pleading",
    ] = "neutral"
    intensity: Literal["low", "medium", "high"] = "medium"


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def _load_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be a YAML mapping")
    return data


def _is_stub_entry(item: dict) -> bool:
    return bool(item.get("_generate")) or bool(item.get("generate"))


def load_npcs(path: Path) -> list[NpcSheet]:
    """Load fully-authored NPCs from ``characters.yaml``.

    Stub entries (``_generate: true``) are skipped silently — they are not
    ready for the pipeline yet. Use :func:`load_npcs_with_stubs` to see both.
    """
    data = _load_yaml(path)
    if "npcs" not in data:
        raise ValueError(f"{path} must define a top-level 'npcs:' key")
    items = data["npcs"]
    if not isinstance(items, list) or not items:
        raise ValueError(f"{path} -> 'npcs' must be a non-empty list")
    return [NpcSheet(**item) for item in items if not _is_stub_entry(item)]


def load_npcs_with_stubs(path: Path) -> tuple[list[NpcSheet], list[NpcStub]]:
    """Load both full NPC sheets and stub placeholders from ``characters.yaml``.

    Useful for :func:`npcforge.generation.resolve_stubs` and for read-only
    tools that need to surface stubs to writers / agents.
    """
    data = _load_yaml(path)
    if "npcs" not in data:
        raise ValueError(f"{path} must define a top-level 'npcs:' key")
    items = data["npcs"]
    if not isinstance(items, list):
        raise ValueError(f"{path} -> 'npcs' must be a list")
    full: list[NpcSheet] = []
    stubs: list[NpcStub] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError(f"{path} npc entry must be a mapping, got: {item!r}")
        if _is_stub_entry(item):
            stubs.append(NpcStub(**item))
        else:
            full.append(NpcSheet(**item))
    return full, stubs


def load_intents(path: Path) -> list[PlayerIntent]:
    """Load player intents from ``player_intents.yaml`` (top-level ``intents:`` key)."""
    data = _load_yaml(path)
    if "intents" not in data:
        raise ValueError(f"{path} must define a top-level 'intents:' key")
    items = data["intents"]
    if not isinstance(items, list) or not items:
        raise ValueError(f"{path} -> 'intents' must be a non-empty list")
    return [PlayerIntent(**item) for item in items]


def load_barks_config(path: Path) -> BarksConfig:
    """Load ``barks.yaml`` if present. Returns an empty config if missing."""
    if not path.exists():
        return BarksConfig()
    data = _load_yaml(path)
    return BarksConfig(**data)


def load_world_bible(lore_dir: Path) -> str:
    """Concatenate every ``*.md`` file under ``lore_dir`` (lexicographic order)."""
    if not lore_dir.is_dir():
        raise FileNotFoundError(f"Lore directory not found: {lore_dir}")
    chunks: list[str] = [
        p.read_text(encoding="utf-8").strip() for p in sorted(lore_dir.glob("*.md"))
    ]
    if not chunks:
        raise ValueError(f"No markdown lore files found in {lore_dir}")
    return "\n\n".join(chunks)


def resolve_intents_for_npc(
    npc: NpcSheet,
    all_intents: list[PlayerIntent],
) -> list[PlayerIntent]:
    """Intersect an NPC's ``allowed_intents`` with the project-wide intent list.

    Empty whitelist → all intents. Preserves the order given in
    ``player_intents.yaml``. Intent ids listed in ``allowed_intents`` that
    are not defined project-wide are silently ignored (the loader should
    already have caught typos).
    """
    if not npc.allowed_intents:
        return list(all_intents)
    allow = set(npc.allowed_intents)
    return [intent for intent in all_intents if intent.id in allow]
