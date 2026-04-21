"""narrative_preset loading and validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from npcforge.narrative_preset import (
    load_effective_narrative_preset,
    load_narrative_preset_file,
    npc_generation_addon,
)


def test_load_file_returns_none_when_missing(tmp_path: Path):
    assert load_narrative_preset_file(tmp_path) is None


def test_load_file_reads_yaml(tmp_path: Path):
    (tmp_path / "npcforge_project.yaml").write_text(
        "narrative_preset: indie_minimal\n", encoding="utf-8"
    )
    assert load_narrative_preset_file(tmp_path) == "indie_minimal"


def test_effective_default_when_no_file(tmp_path: Path):
    assert load_effective_narrative_preset(tmp_path, None) == "rpg_standard"


def test_effective_override_wins(tmp_path: Path):
    (tmp_path / "npcforge_project.yaml").write_text(
        "narrative_preset: cinematic_rpg\n", encoding="utf-8"
    )
    assert load_effective_narrative_preset(tmp_path, "indie_minimal") == "indie_minimal"


def test_effective_invalid_override(tmp_path: Path):
    with pytest.raises(ValueError, match="Unknown narrative_preset"):
        load_effective_narrative_preset(tmp_path, "fps_shooter")


def test_addon_contains_preset_name():
    assert "indie_minimal" in npc_generation_addon("indie_minimal")
    assert "cinematic_rpg" in npc_generation_addon("cinematic_rpg")
