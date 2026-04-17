"""Tests for the NPC generator's IO layer — append semantics, id uniqueness.

No LLM calls — these exercise pure Python around YAML round-trips and id
allocation.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from npcforge.generation import (
    _ensure_unique_id,
    _read_existing_yaml,
    _slugify,
    append_npcs_to_yaml,
)
from npcforge.schemas import NpcSheet, load_npcs


def _sheet(**kw) -> NpcSheet:
    base = dict(id="someone", name="Someone", role="fixer", voice="laconic")
    base.update(kw)
    return NpcSheet(**base)


def test_slugify_lowercases_punctuates_collapses():
    assert _slugify("Mira Vesser") == "mira_vesser"
    assert _slugify("!!!") == "npc"
    assert _slugify("123 foo") == "n123_foo"
    assert _slugify("M'ira O'Brien") == "m_ira_o_brien"


def test_ensure_unique_id_appends_numeric_suffix():
    assert _ensure_unique_id("foo", set()) == "foo"
    assert _ensure_unique_id("foo", {"foo"}) == "foo_2"
    assert _ensure_unique_id("foo", {"foo", "foo_2"}) == "foo_3"


def test_append_npcs_to_empty_file(tmp_path: Path):
    yaml_path = tmp_path / "characters.yaml"
    new = [_sheet(id="a", name="Alpha"), _sheet(id="b", name="Beta")]
    append_npcs_to_yaml(yaml_path, new)

    assert yaml_path.exists()
    loaded = load_npcs(yaml_path)
    assert [n.id for n in loaded] == ["a", "b"]


def test_append_npcs_preserves_existing_entries(tmp_path: Path):
    yaml_path = tmp_path / "characters.yaml"
    yaml_path.write_text(
        yaml.safe_dump(
            {
                "world": "Testing",
                "npcs": [
                    {
                        "id": "preexisting",
                        "name": "Preexisting",
                        "role": "original",
                        "voice": "stable",
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    append_npcs_to_yaml(yaml_path, [_sheet(id="fresh", name="Fresh Arrival")])

    loaded = load_npcs(yaml_path)
    ids = [n.id for n in loaded]
    assert ids == ["preexisting", "fresh"]
    # Top-level keys beyond `npcs:` survive the roundtrip.
    reparsed = _read_existing_yaml(yaml_path)
    assert reparsed.get("world") == "Testing"


def test_append_npcs_strips_empty_fields(tmp_path: Path):
    yaml_path = tmp_path / "characters.yaml"
    npc = _sheet(
        id="x",
        name="X",
        role="r",
        voice="v",
        motivations=[],  # empty — should be pruned
        speech_quirks=[],
        background="",  # empty — should be pruned
    )
    append_npcs_to_yaml(yaml_path, [npc])
    raw = yaml_path.read_text(encoding="utf-8")
    # Empty collections should not appear in the serialised output.
    assert "motivations:" not in raw
    assert "speech_quirks:" not in raw
    assert "background:" not in raw
    # Required fields are still there.
    assert "id: x" in raw
    assert "voice: v" in raw
