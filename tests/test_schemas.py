"""Tests for YAML loaders and schema validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from npcforge.schemas import (
    NpcSheet,
    PlayerArchetype,
    load_archetypes,
    load_npcs,
    load_world_bible,
)


_FIXTURE_DIR = Path(__file__).parent.parent / "examples" / "rusted_lantern"


def test_load_npcs_returns_typed_objects():
    npcs = load_npcs(_FIXTURE_DIR / "characters.yaml")
    assert len(npcs) == 5
    assert all(isinstance(n, NpcSheet) for n in npcs)
    mira = next(n for n in npcs if n.id == "mira_vesser")
    assert mira.role.startswith("Tavernkeeper")
    assert mira.motivations, "Mira must have at least one motivation"
    assert mira.secret, "Mira must have a secret"


def test_load_archetypes_returns_typed_objects():
    archs = load_archetypes(_FIXTURE_DIR / "player_archetypes.yaml")
    assert len(archs) == 3
    assert all(isinstance(a, PlayerArchetype) for a in archs)
    ids = {a.id for a in archs}
    assert ids == {"curious_scholar", "hostile_mercenary", "deceptive_trader"}


def test_load_world_bible_concatenates_markdown():
    bible = load_world_bible(_FIXTURE_DIR / "lore")
    assert "Emberfall" in bible
    assert "Rusted Lantern" in bible
    assert len(bible) > 500


def test_load_npcs_raises_on_missing_key(tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("wrong_key: []\n")
    with pytest.raises(ValueError, match="npcs"):
        load_npcs(bad)


def test_load_world_bible_raises_on_empty_dir(tmp_path: Path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValueError):
        load_world_bible(empty)
