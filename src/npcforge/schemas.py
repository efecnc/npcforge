"""Input schemas and YAML/markdown loaders for npcforge.

Every public function raises a :class:`ValueError` or :class:`FileNotFoundError`
on malformed input so CLI callers can surface clean error messages.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class NpcSheet(BaseModel):
    """A single NPC entry from ``characters.yaml``.

    Required fields: ``id``, ``name``, ``role``, ``voice``. Everything else
    has a sensible default so authors can sketch NPCs incrementally.
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


class PlayerArchetype(BaseModel):
    """A single entry from ``player_archetypes.yaml``.

    Each archetype becomes one ``-> [archetype]`` option in every NPC's Yarn
    node, and seeds the Correspondent side of the afterimage two-agent loop.
    """

    id: str
    name: str
    description: str
    opening_intent: str = ""


def load_npcs(path: Path) -> list[NpcSheet]:
    """Load a list of :class:`NpcSheet` from a YAML file with ``npcs:`` at root."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "npcs" not in data:
        raise ValueError(f"{path} must define a top-level 'npcs:' key")
    items = data["npcs"]
    if not isinstance(items, list) or not items:
        raise ValueError(f"{path} -> 'npcs' must be a non-empty list")
    return [NpcSheet(**item) for item in items]


def load_archetypes(path: Path) -> list[PlayerArchetype]:
    """Load a list of :class:`PlayerArchetype` from a YAML file with ``archetypes:`` at root."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "archetypes" not in data:
        raise ValueError(f"{path} must define a top-level 'archetypes:' key")
    items = data["archetypes"]
    if not isinstance(items, list) or not items:
        raise ValueError(f"{path} -> 'archetypes' must be a non-empty list")
    return [PlayerArchetype(**item) for item in items]


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
