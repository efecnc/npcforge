"""Tests for the tools layer and MCP binding — pure, no LLM calls."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from npcforge.schemas import NpcSheet
from npcforge.tools import (
    ListNpcsInput,
    ShowWorldProfileInput,
    TOOL_REGISTRY,
    list_npcs,
    list_tool_specs,
    show_world_profile,
)
from npcforge.world_profile import CanonicalTerm, WorldProfile, save_profile


_RUSTED_LANTERN = Path(__file__).parent.parent / "examples" / "rusted_lantern"


def test_tool_registry_has_expected_tools():
    names = set(TOOL_REGISTRY.keys())
    assert {
        "infer_world_profile",
        "show_world_profile",
        "list_npcs",
        "gen_npcs",
        "build_pipeline",
    }.issubset(names)


def test_list_tool_specs_json_schema_shape():
    specs = list_tool_specs()
    for spec in specs:
        assert spec.name
        assert spec.description
        # Each schema must be a proper JSON Schema object.
        assert spec.input_schema.get("type") == "object"
        assert "properties" in spec.input_schema
        assert "properties" in spec.output_schema


def test_list_npcs_returns_rusted_lantern_cast():
    result = asyncio.run(list_npcs(ListNpcsInput(demo_dir=_RUSTED_LANTERN)))
    assert result.count == 5
    assert all(isinstance(n, NpcSheet) for n in result.npcs)
    ids = {n.id for n in result.npcs}
    assert "mira_vesser" in ids


def test_list_npcs_empty_demo_returns_zero(tmp_path: Path):
    result = asyncio.run(list_npcs(ListNpcsInput(demo_dir=tmp_path)))
    assert result.count == 0
    assert result.npcs == []


def test_show_world_profile_roundtrip(tmp_path: Path):
    # No cache yet.
    empty = asyncio.run(show_world_profile(ShowWorldProfileInput(demo_dir=tmp_path)))
    assert empty.exists is False
    assert empty.profile is None

    # Write a cache by hand, then the tool should return it verbatim.
    wp = WorldProfile(
        genre="cyberpunk_noir",
        era="2077",
        tone="kinetic",
        likely_rating="M",
        register_default="high_school",
        canonical_terms=[CanonicalTerm(category="currency", term="eddies")],
        anachronism_blocklist=["doth", "verily"],
        notes="inferred for tests",
        inferred_from=["lore/test.md"],
    )
    save_profile(tmp_path, wp)

    loaded = asyncio.run(show_world_profile(ShowWorldProfileInput(demo_dir=tmp_path)))
    assert loaded.exists is True
    assert loaded.profile is not None
    assert loaded.profile.genre == "cyberpunk_noir"
    assert [(t.category, t.term) for t in loaded.profile.canonical_terms] == [
        ("currency", "eddies")
    ]


def test_tool_input_schemas_include_api_key_for_llm_tools():
    """Any tool that calls the LLM should surface api_key in its schema."""
    for name in ("infer_world_profile", "gen_npcs", "build_pipeline"):
        _, input_model, _, _ = TOOL_REGISTRY[name]
        props = input_model.model_json_schema().get("properties", {})
        assert "api_key" in props, f"{name} must expose api_key in input schema"


def test_tool_input_schemas_exclude_api_key_for_readonly_tools():
    """Read-only tools must not ask for credentials."""
    for name in ("show_world_profile", "list_npcs"):
        _, input_model, _, _ = TOOL_REGISTRY[name]
        props = input_model.model_json_schema().get("properties", {})
        assert "api_key" not in props, f"{name} should not require api_key"
