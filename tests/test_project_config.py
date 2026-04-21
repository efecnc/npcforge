"""project_config: topology, depth, legacy narrative_preset mapping."""

from __future__ import annotations

from pathlib import Path

import pytest

from npcforge.narrative_preset import load_effective_narrative_preset
from npcforge.project_config import (
    load_project_config,
    npc_generation_prompt_suffix,
)


def test_defaults_when_no_project_file(tmp_path: Path) -> None:
    cfg = load_project_config(tmp_path)
    assert cfg.topology == "quest_rpg"
    assert cfg.depth == "standard"
    assert cfg.legacy_narrative_preset_id() == "rpg_standard"


def test_legacy_narrative_preset_yaml_maps_topology_depth(tmp_path: Path) -> None:
    (tmp_path / "npcforge_project.yaml").write_text(
        "narrative_preset: indie_minimal\n", encoding="utf-8"
    )
    cfg = load_project_config(tmp_path)
    assert cfg.topology == "ambient_indie"
    assert cfg.depth == "lean"
    assert cfg.legacy_narrative_preset_id() == "indie_minimal"


def test_explicit_topology_depth_in_yaml(tmp_path: Path) -> None:
    (tmp_path / "npcforge_project.yaml").write_text(
        "topology: social_sim\ndepth: cinematic\n", encoding="utf-8"
    )
    cfg = load_project_config(tmp_path)
    assert cfg.topology == "social_sim"
    assert cfg.depth == "cinematic"
    assert cfg.legacy_narrative_preset_id() == "cinematic_rpg"


def test_cli_topology_override(tmp_path: Path) -> None:
    (tmp_path / "npcforge_project.yaml").write_text(
        "topology: quest_rpg\ndepth: lean\n", encoding="utf-8"
    )
    cfg = load_project_config(tmp_path, topology_override="immersive_sim")
    assert cfg.topology == "immersive_sim"
    assert cfg.depth == "lean"


def test_invalid_topology_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unknown topology"):
        load_project_config(tmp_path, topology_override="not_a_topology")


def test_load_effective_still_honours_yaml_preset(tmp_path: Path) -> None:
    (tmp_path / "npcforge_project.yaml").write_text(
        "narrative_preset: cinematic_rpg\n", encoding="utf-8"
    )
    assert load_effective_narrative_preset(tmp_path, None) == "cinematic_rpg"


def test_npc_generation_suffix_includes_topology(tmp_path: Path) -> None:
    (tmp_path / "npcforge_project.yaml").write_text(
        "topology: immersive_sim\ndepth: standard\n", encoding="utf-8"
    )
    cfg = load_project_config(tmp_path)
    s = npc_generation_prompt_suffix(cfg)
    assert "immersive_sim" in s
    assert "DEPTH: standard" in s
