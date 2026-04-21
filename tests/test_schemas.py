"""Tests for YAML loaders, schema validation, and intent resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from npcforge.schemas import (
    NpcSheet,
    PlayerIntent,
    load_barks_config,
    load_intents,
    load_npcs,
    load_world_bible,
    resolve_intents_for_npc,
)


_FIXTURE_DIR = Path(__file__).parent.parent / "examples" / "rusted_lantern"


def test_load_npcs_returns_typed_objects_with_voice_ceiling_fields():
    npcs = load_npcs(_FIXTURE_DIR / "characters.yaml")
    assert len(npcs) == 5
    assert all(isinstance(n, NpcSheet) for n in npcs)
    mira = next(n for n in npcs if n.id == "mira_vesser")
    assert mira.role.startswith("Tavernkeeper")
    assert "place_rusted_lantern" in mira.scope_tags
    assert mira.motivations, "Mira must have at least one motivation"
    assert mira.secret, "Mira must have a secret"
    assert mira.vocabulary_ceiling == "grade_8"
    assert "intriguing" in mira.forbidden_words
    assert mira.allowed_intents, "Mira must declare allowed intents"


def test_load_intents_returns_typed_objects():
    intents = load_intents(_FIXTURE_DIR / "player_intents.yaml")
    assert len(intents) >= 10, "Demo should ship a reasonable intent catalog"
    assert all(isinstance(i, PlayerIntent) for i in intents)
    ids = {i.id for i in intents}
    assert "ask_about_locket" in ids
    assert "farewell" in ids


def test_load_world_bible_concatenates_markdown():
    bible = load_world_bible(_FIXTURE_DIR / "lore")
    assert "Emberfall" in bible
    assert "Rusted Lantern" in bible
    assert len(bible) > 500


def test_load_barks_config_parses_nested_triggers():
    cfg = load_barks_config(_FIXTURE_DIR / "barks.yaml")
    assert cfg.barks, "Demo barks config should not be empty"
    mira_entry = next(e for e in cfg.barks if e.npc == "mira_vesser")
    assert any(t.id == "greet_patron" for t in mira_entry.triggers)
    greet = next(t for t in mira_entry.triggers if t.id == "greet_patron")
    assert greet.n >= 1


def test_resolve_intents_respects_allowed_whitelist():
    npcs = load_npcs(_FIXTURE_DIR / "characters.yaml")
    intents = load_intents(_FIXTURE_DIR / "player_intents.yaml")
    gereth = next(n for n in npcs if n.id == "gereth_blackstone")
    resolved = resolve_intents_for_npc(gereth, intents)
    resolved_ids = {i.id for i in resolved}
    # Gereth should NOT be available for merchant interactions.
    assert "barter_wares" not in resolved_ids
    assert "flirt" not in resolved_ids
    # But should include ones his sheet whitelists.
    assert "ask_about_locket" in resolved_ids
    assert "farewell" in resolved_ids


def test_resolve_intents_empty_whitelist_allows_all():
    npc = NpcSheet(id="x", name="X", role="r", voice="v")  # no allowed_intents
    intents = [
        PlayerIntent(id="a", name="A", description="d"),
        PlayerIntent(id="b", name="B", description="d"),
    ]
    resolved = resolve_intents_for_npc(npc, intents)
    assert len(resolved) == 2


def test_load_npcs_raises_on_missing_key(tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("wrong_key: []\n")
    with pytest.raises(ValueError, match="npcs"):
        load_npcs(bad)


def test_load_intents_raises_on_missing_key(tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("wrong_key: []\n")
    with pytest.raises(ValueError, match="intents"):
        load_intents(bad)


def test_load_world_bible_raises_on_empty_dir(tmp_path: Path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValueError):
        load_world_bible(empty)


def test_load_barks_config_returns_empty_when_missing(tmp_path: Path):
    cfg = load_barks_config(tmp_path / "nonexistent.yaml")
    assert cfg.barks == []
