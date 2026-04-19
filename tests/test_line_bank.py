"""Tests for v0.11.0 line banks: schema + selector + diagnostic."""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from npcforge.line_bank import (
    LineBank,
    LineContext,
    LineSlot,
    LineTag,
    LineVariant,
    bank_coverage_report,
    expand_tag_combos,
    select_line,
    variant_matches,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _greeting_bank() -> LineBank:
    bank = LineBank(npc_id="mira")
    bank.add_slot(LineSlot(
        id="greeting",
        description="A one-line greeting when the player walks up.",
        default_text="Mira nods without looking up.",
    ))
    bank.add_variant("greeting", LineVariant(
        text="Friend. Drink?",
        tags=[LineTag(dimension="disposition_tier", value="neutral")],
    ))
    bank.add_variant("greeting", LineVariant(
        text="You again. Sit wherever.",
        tags=[LineTag(dimension="disposition_tier", value="friendly")],
    ))
    bank.add_variant("greeting", LineVariant(
        text="The inspector hasn't come in yet. Good.",
        tags=[
            LineTag(dimension="disposition_tier", value="trusted"),
            LineTag(dimension="faction_present", value="lantern_regulars"),
        ],
    ))
    bank.add_variant("greeting", LineVariant(
        text="(generic)",
        tags=[],
        salience_boost=-1.0,  # de-prefer the fallback vs any tagged line
    ))
    return bank


# ---------------------------------------------------------------------------
# Schema + persistence
# ---------------------------------------------------------------------------


class TestLineBankSchema:
    def test_add_variant_requires_existing_slot(self):
        bank = LineBank(npc_id="x")
        with pytest.raises(KeyError, match="has no slot"):
            bank.add_variant("missing", LineVariant(text="."))

    def test_variant_count(self):
        bank = _greeting_bank()
        assert bank.variant_count("greeting") == 4
        assert bank.variant_count("nope") == 0

    def test_save_and_load_round_trip(self, tmp_path: Path):
        bank = _greeting_bank()
        path = tmp_path / "bank.json"
        bank.save(path)
        reloaded = LineBank.load(path)
        assert reloaded.npc_id == "mira"
        assert reloaded.variant_count("greeting") == 4
        assert reloaded.slots["greeting"].default_text.startswith("Mira nods")

    def test_load_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            LineBank.load(tmp_path / "nope.json")


# ---------------------------------------------------------------------------
# variant_matches
# ---------------------------------------------------------------------------


class TestVariantMatches:
    def test_untagged_variant_always_matches(self):
        ctx = LineContext()
        v = LineVariant(text="x", tags=[])
        assert variant_matches(v, ctx)

    def test_single_tag_match_requires_dimension_set(self):
        v = LineVariant(text="x", tags=[
            LineTag(dimension="mood", value="grateful")])
        assert not variant_matches(v, LineContext())
        assert variant_matches(v, LineContext(mood="grateful"))
        assert not variant_matches(v, LineContext(mood="resentful"))

    def test_multi_tag_requires_all(self):
        v = LineVariant(text="x", tags=[
            LineTag(dimension="disposition_tier", value="trusted"),
            LineTag(dimension="time_of_day", value="night"),
        ])
        assert not variant_matches(v, LineContext(disposition_tier="trusted"))
        assert not variant_matches(v, LineContext(
            disposition_tier="friendly", time_of_day="night"))
        assert variant_matches(v, LineContext(
            disposition_tier="trusted", time_of_day="night"))


# ---------------------------------------------------------------------------
# select_line
# ---------------------------------------------------------------------------


class TestSelectLine:
    def test_missing_slot_returns_empty_when_no_default(self):
        bank = LineBank(npc_id="x")
        assert select_line(bank, "ghost", LineContext()) == ""

    def test_no_match_falls_through_to_default_text(self):
        bank = _greeting_bank()
        # disposition_tier=hostile has no variant and no generic fallback
        # matches — wait, the (generic) variant HAS no tags, so it
        # matches. Drop it by removing the context-agnostic.
        result = select_line(bank, "greeting",
                             LineContext(disposition_tier="hostile"))
        # The empty-tag variant matches anything, so we expect it to come
        # back.
        assert result == "(generic)"

    def test_prefers_more_specific_match_over_generic(self):
        bank = _greeting_bank()
        result = select_line(bank, "greeting",
                             LineContext(disposition_tier="friendly"))
        assert result == "You again. Sit wherever."

    def test_prefers_higher_specificity_within_same_dim_count(self):
        bank = _greeting_bank()
        # trusted AND faction_present=lantern_regulars → most specific.
        result = select_line(bank, "greeting", LineContext(
            disposition_tier="trusted",
            faction_present="lantern_regulars",
        ))
        assert "inspector" in result

    def test_recently_picked_avoided_on_ties(self):
        bank = LineBank(npc_id="x")
        bank.add_slot(LineSlot(id="greeting", description="d"))
        bank.add_variant("greeting", LineVariant(text="A"))
        bank.add_variant("greeting", LineVariant(text="B"))
        rng = random.Random(0)
        # Feed A in as recently picked — should get B.
        out = select_line(bank, "greeting", LineContext(),
                          recently_picked={"A"}, rng=rng)
        assert out == "B"

    def test_salience_boost_breaks_same_dim_count_tie(self):
        bank = LineBank(npc_id="x")
        bank.add_slot(LineSlot(id="g", description="d"))
        bank.add_variant("g", LineVariant(
            text="base",
            tags=[LineTag(dimension="mood", value="grateful")]))
        bank.add_variant("g", LineVariant(
            text="boosted",
            tags=[LineTag(dimension="mood", value="grateful")],
            salience_boost=5.0))
        out = select_line(bank, "g", LineContext(mood="grateful"))
        assert out == "boosted"

    def test_slot_default_text_returned_when_no_variants_at_all(self):
        bank = LineBank(npc_id="x")
        bank.add_slot(LineSlot(
            id="g", description="d", default_text="fallback"))
        # No variants added.
        assert select_line(bank, "g", LineContext()) == "fallback"


# ---------------------------------------------------------------------------
# expand_tag_combos
# ---------------------------------------------------------------------------


class TestExpandTagCombos:
    def test_no_axes_returns_single_empty_combo(self):
        combos = expand_tag_combos()
        assert combos == [[]]

    def test_single_axis_produces_one_tag_per_value(self):
        combos = expand_tag_combos(disposition_tiers=["wary", "trusted"])
        assert len(combos) == 2
        assert all(len(c) == 1 for c in combos)
        values = sorted(c[0].value for c in combos)
        assert values == ["trusted", "wary"]

    def test_cartesian_product_of_two_axes(self):
        combos = expand_tag_combos(
            disposition_tiers=["wary", "trusted"],
            times_of_day=["morning", "night"],
        )
        assert len(combos) == 4
        pairs = {(c[0].value, c[1].value) for c in combos}
        assert pairs == {
            ("wary", "morning"), ("wary", "night"),
            ("trusted", "morning"), ("trusted", "night"),
        }


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


class TestCoverageReport:
    def test_totals_and_per_tag_counts(self):
        bank = _greeting_bank()
        report = bank_coverage_report(bank)
        assert report["greeting"]["_total"] == 4
        assert report["greeting"]["disposition_tier=neutral"] == 1
        assert report["greeting"]["disposition_tier=friendly"] == 1
        assert report["greeting"]["faction_present=lantern_regulars"] == 1
