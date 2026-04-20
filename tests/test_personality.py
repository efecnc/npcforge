"""Tests for v0.18.0 OCEAN personality."""

from __future__ import annotations

from pathlib import Path

import pytest

from npcforge.prompts import (
    _OCEAN_PROSE,
    _render_personality,
    build_npc_respondent_prompt,
)
from npcforge.schemas import NpcSheet, Personality, load_npcs


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class TestPersonalitySchema:
    def test_defaults_are_neutral(self):
        p = Personality()
        assert p.openness == 0.5
        assert p.neuroticism == 0.5

    def test_values_clamp_at_zero_and_one(self):
        with pytest.raises(Exception):
            Personality(openness=-0.1)
        with pytest.raises(Exception):
            Personality(extraversion=1.5)

    def test_axis_returns_value_for_valid_name(self):
        p = Personality(extraversion=0.8)
        assert p.axis("extraversion") == 0.8

    def test_axis_returns_neutral_for_unknown_name(self):
        p = Personality()
        assert p.axis("not_a_real_axis") == 0.5


# ---------------------------------------------------------------------------
# Dominant axes
# ---------------------------------------------------------------------------


class TestDominantAxes:
    def test_neutral_profile_has_no_dominant_axes(self):
        p = Personality()  # all 0.5
        assert p.dominant_axes() == []

    def test_high_and_low_axes_return_direction(self):
        p = Personality(
            openness=0.9,          # high
            conscientiousness=0.5, # neutral
            extraversion=0.1,      # low
            agreeableness=0.55,    # inside band
            neuroticism=0.5,
        )
        dom = p.dominant_axes(top_n=5, band=0.2)
        # Sorted by absolute distance from 0.5: O=0.4, E=0.4
        names = [a for a, d in dom]
        dirs = dict(dom)
        assert set(names) == {"openness", "extraversion"}
        assert dirs["openness"] == "high"
        assert dirs["extraversion"] == "low"

    def test_band_filter_excludes_near_neutral(self):
        p = Personality(agreeableness=0.6)  # |0.1| < default band 0.25
        assert p.dominant_axes() == []

    def test_top_n_caps_output(self):
        p = Personality(
            openness=0.9, conscientiousness=0.9,
            extraversion=0.9, agreeableness=0.9, neuroticism=0.9,
        )
        assert len(p.dominant_axes(top_n=2)) == 2


# ---------------------------------------------------------------------------
# Prompt block rendering
# ---------------------------------------------------------------------------


class TestRenderPersonality:
    def test_none_returns_empty(self):
        assert _render_personality(None) == ""

    def test_neutral_profile_returns_empty(self):
        assert _render_personality(Personality()) == ""

    def test_distinctive_profile_renders_block(self):
        p = Personality(extraversion=0.15, neuroticism=0.85)
        block = _render_personality(p)
        assert "Personality profile" in block
        assert "extraversion (low" in block
        assert "neuroticism (high" in block

    def test_prose_hints_present_for_high_and_low(self):
        # Make sure every declared axis has prose for both directions.
        axes = ["openness", "conscientiousness", "extraversion",
                "agreeableness", "neuroticism"]
        for axis in axes:
            assert (axis, "high") in _OCEAN_PROSE
            assert (axis, "low") in _OCEAN_PROSE


# ---------------------------------------------------------------------------
# Prompt wiring
# ---------------------------------------------------------------------------


class TestPromptWiring:
    def test_npc_without_personality_omits_block(self):
        npc = NpcSheet(id="x", name="X", role="r", voice="v")
        prompt = build_npc_respondent_prompt(npc)
        # Rule 17 references "Personality profile" in its own text —
        # check for a render-only token instead (the OCEAN axis-name
        # format shows up only in the rendered block).
        assert "openness (high" not in prompt
        assert "extraversion (low" not in prompt

    def test_npc_with_distinctive_personality_renders_block(self):
        npc = NpcSheet(
            id="x", name="X", role="r", voice="v",
            personality=Personality(extraversion=0.1, neuroticism=0.9),
        )
        prompt = build_npc_respondent_prompt(npc)
        assert "Personality profile" in prompt
        assert "extraversion (low" in prompt

    def test_rule_17_present(self):
        npc = NpcSheet(id="x", name="X", role="r", voice="v")
        prompt = build_npc_respondent_prompt(npc)
        assert "17. If a 'Personality profile' block" in prompt


# ---------------------------------------------------------------------------
# Rusted Lantern OCEAN coverage
# ---------------------------------------------------------------------------


class TestRustedLanternOcean:
    def test_all_five_cast_members_have_distinctive_profiles(self):
        root = Path(__file__).resolve().parent.parent / "examples/rusted_lantern"
        for npc in load_npcs(root / "characters.yaml"):
            assert npc.personality is not None, f"{npc.id} missing personality"
            dom = npc.personality.dominant_axes()
            # Every Rusted Lantern NPC should have at least one
            # distinctive axis — otherwise the OCEAN investment adds
            # zero prompt value for them.
            assert len(dom) >= 1, (
                f"{npc.id} has a personality but no axis outside the "
                f"neutral band — pick a more distinctive profile."
            )

    def test_mira_is_conscientious_and_introverted(self):
        root = Path(__file__).resolve().parent.parent / "examples/rusted_lantern"
        mira = next(n for n in load_npcs(root / "characters.yaml")
                    if n.id == "mira_vesser")
        dom = dict(mira.personality.dominant_axes())
        assert dom.get("conscientiousness") == "high"
        assert dom.get("extraversion") == "low"

    def test_ulrik_is_introverted_and_low_neuroticism(self):
        root = Path(__file__).resolve().parent.parent / "examples/rusted_lantern"
        ulrik = next(n for n in load_npcs(root / "characters.yaml")
                     if n.id == "ulrik_the_old_man")
        dom = dict(ulrik.personality.dominant_axes())
        assert dom.get("extraversion") == "low"
        assert dom.get("neuroticism") == "low"

    def test_kess_is_extraverted_and_open(self):
        root = Path(__file__).resolve().parent.parent / "examples/rusted_lantern"
        kess = next(n for n in load_npcs(root / "characters.yaml")
                    if n.id == "kess_the_knife")
        dom = dict(kess.personality.dominant_axes())
        assert dom.get("extraversion") == "high"
        assert dom.get("openness") == "high"
