"""Tests for optional layers.yaml + NpcSheet.scope_tags."""

from __future__ import annotations

from pathlib import Path

import pytest

from npcforge.narrative_scope import (
    LayersConfig,
    WorldLayer,
    filter_npcs_by_scope_tags,
    format_layers_catalog_block,
    format_npc_scope_section,
    layer_lineage,
    load_layers_config,
)
from npcforge.schemas import NpcSheet


def _npc(nid: str, tags: list[str]) -> NpcSheet:
    return NpcSheet(
        id=nid,
        name=nid.replace("_", " ").title(),
        role="Test role",
        voice="Terse.",
        scope_tags=tags,
    )


def test_filter_npcs_by_scope_tags_intersection():
    npcs = [
        _npc("a", ["inn", "town"]),
        _npc("b", ["dock"]),
        _npc("c", []),
    ]
    out = filter_npcs_by_scope_tags(npcs, ["inn"], include_unscoped=False)
    assert [n.id for n in out] == ["a"]


def test_filter_include_unscoped():
    npcs = [_npc("a", ["x"]), _npc("b", [])]
    out = filter_npcs_by_scope_tags(npcs, ["y"], include_unscoped=True)
    assert {n.id for n in out} == {"b"}
    out2 = filter_npcs_by_scope_tags(npcs, ["y"], include_unscoped=False)
    assert out2 == []


def test_layer_lineage_root_to_leaf():
    cfg = LayersConfig(
        layers=[
            WorldLayer(id="w", parent=None, name="World", summary="root"),
            WorldLayer(id="t", parent="w", name="Town", summary="mid"),
            WorldLayer(id="p", parent="t", name="Place", summary="leaf"),
        ]
    )
    chain = layer_lineage("p", cfg)
    assert [L.id for L in chain] == ["w", "t", "p"]


def test_format_npc_scope_section_unknown_tag():
    npc = NpcSheet(
        id="x",
        name="X",
        role="r",
        voice="v",
        scope_tags=["custom_slice"],
        narrative_scope_note="Only the warehouse roof.",
    )
    text = format_npc_scope_section(npc, LayersConfig())
    assert "custom_slice" in text
    assert "warehouse" in text


def test_load_layers_example_fixture():
    path = Path(__file__).parent.parent / "examples" / "rusted_lantern" / "layers.yaml"
    cfg = load_layers_config(path)
    ids = {L.id for L in cfg.layers}
    assert "place_rusted_lantern" in ids
    assert "town_grindholt" in ids


def test_format_layers_catalog_nonempty(tmp_path: Path):
    p = tmp_path / "layers.yaml"
    p.write_text(
        "layers:\n"
        "  - id: a\n"
        "    parent: null\n"
        "    name: A\n"
        "    summary: sa\n",
        encoding="utf-8",
    )
    cfg = load_layers_config(p)
    block = format_layers_catalog_block(cfg)
    assert "a" in block
    assert "### World layers" in block


def test_duplicate_layer_id_errors():
    with pytest.raises(ValueError, match="Duplicate"):
        LayersConfig(
            layers=[
                WorldLayer(id="dup", parent=None, name="1", summary=""),
                WorldLayer(id="dup", parent=None, name="2", summary=""),
            ]
        )
