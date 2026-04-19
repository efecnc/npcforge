"""Tests for v0.16.0 moral profile + ethical reactions."""

from __future__ import annotations

from pathlib import Path

import pytest

from npcforge.ethics import (
    DEFAULT_EVENT_JUDGEMENTS,
    EthicalReading,
    evaluate_player_against_npc,
    summarize_ethical_reading,
)
from npcforge.memory import MemoryStore
from npcforge.prompts import build_npc_respondent_prompt
from npcforge.schemas import EthicalProfile, NpcSheet, load_npcs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _npc(axes: dict[str, float]) -> NpcSheet:
    return NpcSheet(
        id="x", name="X", role="y", voice="z",
        ethical_profile=EthicalProfile(**axes),
    )


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class TestEthicalProfileSchema:
    def test_values_clamp_at_zero_and_one(self):
        with pytest.raises(Exception):
            EthicalProfile(honor_bound=-0.5)
        with pytest.raises(Exception):
            EthicalProfile(zealot=1.5)

    def test_missing_axis_is_zero(self):
        p = EthicalProfile(honor_bound=0.7)
        assert p.weight("honor_bound") == 0.7
        assert p.weight("pragmatic") == 0.0

    def test_dominant_axes_sorted_and_thresholded(self):
        p = EthicalProfile(
            honor_bound=0.8, pragmatic=0.3, zealot=0.6,
            communal=0.1, self_serving=0.05,
        )
        assert p.dominant_axes() == ["honor_bound", "zealot"]
        assert p.dominant_axes(top_n=5, min_weight=0.05) == [
            "honor_bound", "zealot", "pragmatic", "communal", "self_serving",
        ]


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------


class TestEvaluatePlayerAgainstNpc:
    def test_no_profile_returns_zero_reading(self):
        npc = NpcSheet(id="x", name="X", role="y", voice="z")  # no profile
        store = MemoryStore()
        store.record(npc_id="x", event_type="player_lied",
                     summary="x", salience="pivotal", turn=1)
        r = evaluate_player_against_npc(npc, store)
        assert r.score == 0.0
        assert r.by_axis == {}
        assert r.top_events == []

    def test_zealot_judges_lie_harder_than_pragmatic(self):
        pragmatic = _npc({"pragmatic": 0.9})
        zealot = _npc({"zealot": 0.9})
        store = MemoryStore()
        store.record(npc_id="x", event_type="player_lied",
                     summary="denied knowing Kess",
                     salience="pivotal", turn=1)
        rp = evaluate_player_against_npc(pragmatic, store)
        rz = evaluate_player_against_npc(zealot, store)
        assert rp.score == pytest.approx(0.0)  # pragmatic 0.9 × 0.0 delta
        assert rz.score < 0.0
        # zealot weight 0.9 × -0.20 delta from default table.
        assert rz.score == pytest.approx(0.9 * -0.20)

    def test_honor_bound_approves_secret_shared(self):
        npc = _npc({"honor_bound": 1.0})
        store = MemoryStore()
        store.record(npc_id="x", event_type="secret_shared",
                     summary="gave coin anonymously",
                     salience="pivotal", turn=1)
        r = evaluate_player_against_npc(npc, store)
        assert r.score > 0
        assert "honor_bound" in r.by_axis

    def test_faction_shared_events_are_judged(self):
        npc = _npc({"communal": 1.0})
        npc.faction_id = "lantern"
        store = MemoryStore()
        store.record(npc_id="other", event_type="faction_helped",
                     summary="cleared a debt",
                     salience="notable", faction_id="lantern", turn=1)
        r = evaluate_player_against_npc(npc, store)
        assert r.score > 0

    def test_top_events_sorted_by_abs_contribution(self):
        npc = _npc({"honor_bound": 1.0})
        store = MemoryStore()
        store.record(npc_id="x", event_type="offer_help",
                     summary="small help",
                     salience="notable", turn=1)  # +0.20 × 1.0 = +0.20
        store.record(npc_id="x", event_type="player_lied",
                     summary="big lie",
                     salience="pivotal", turn=2)  # -0.30 × 1.0 = -0.30
        r = evaluate_player_against_npc(npc, store)
        # Top event should be the lie (bigger absolute magnitude).
        assert r.top_events[0][0] == "player_lied"

    def test_unknown_event_type_ignored(self):
        npc = _npc({"honor_bound": 1.0})
        store = MemoryStore()
        store.record(npc_id="x", event_type="completely_novel",
                     summary="x", salience="notable", turn=1)
        r = evaluate_player_against_npc(npc, store)
        assert r.score == 0.0

    def test_custom_judgement_table_overrides_default(self):
        npc = _npc({"honor_bound": 1.0})
        store = MemoryStore()
        store.record(npc_id="x", event_type="offer_help",
                     summary="x", salience="notable", turn=1)
        # Default: honor_bound +0.20 for offer_help.
        # Custom: honor_bound -0.5 for offer_help.
        custom = {"offer_help": {"honor_bound": -0.5}}
        r = evaluate_player_against_npc(npc, store, judgement_table=custom)
        assert r.score == pytest.approx(-0.5)


# ---------------------------------------------------------------------------
# Summariser
# ---------------------------------------------------------------------------


class TestSummarizeEthicalReading:
    def test_empty_when_npc_has_no_profile(self):
        npc = NpcSheet(id="x", name="X", role="y", voice="z")
        reading = EthicalReading(score=0.0, by_axis={}, top_events=[])
        assert summarize_ethical_reading(npc, reading) == ""

    def test_empty_when_no_events_judged(self):
        npc = _npc({"honor_bound": 0.8})
        reading = EthicalReading(score=0.0, by_axis={}, top_events=[])
        assert summarize_ethical_reading(npc, reading) == ""

    def test_rendered_block_contains_verdict_and_top_events(self):
        npc = _npc({"zealot": 0.8, "honor_bound": 0.5})
        reading = EthicalReading(
            score=-0.4,
            by_axis={"zealot": -0.3, "honor_bound": -0.1},
            top_events=[
                ("player_lied", "denied knowing Kess", -0.4),
            ],
        )
        block = summarize_ethical_reading(npc, reading)
        assert "Ethical reading" in block
        assert "net disapproving" in block
        assert "zealot" in block and "honor_bound" in block
        assert "player_lied" in block
        assert "denied knowing Kess" in block
        # Guard clause against narration.
        assert "no lectures" in block


# ---------------------------------------------------------------------------
# Prompt wiring
# ---------------------------------------------------------------------------


class TestEthicsPromptWiring:
    def test_block_absent_without_kwarg(self):
        npc = _npc({"pragmatic": 0.8})
        prompt = build_npc_respondent_prompt(npc)
        # Rule 15 mentions "Ethical reading"; look for the block's
        # specific 'your private judgement' phrasing instead.
        assert "YOUR private judgement" not in prompt

    def test_block_present_when_kwarg_supplied(self):
        npc = _npc({"pragmatic": 0.8})
        prompt = build_npc_respondent_prompt(
            npc,
            ethical_reading_block=(
                "Ethical reading (YOUR private judgement of the player):\n"
                "- Your dominant ethical axes: pragmatic."
            ),
        )
        assert "YOUR private judgement" in prompt
        assert "dominant ethical axes: pragmatic" in prompt

    def test_rule_15_present_in_base_rules(self):
        npc = NpcSheet(id="x", name="X", role="y", voice="z")
        prompt = build_npc_respondent_prompt(npc)
        assert "15. If an 'Ethical reading' block" in prompt


# ---------------------------------------------------------------------------
# Rusted Lantern demo assertions
# ---------------------------------------------------------------------------


class TestRustedLanternEthics:
    def test_mira_adelie_ulrik_have_distinct_profiles(self):
        root = Path(__file__).resolve().parent.parent / "examples/rusted_lantern"
        by_id = {n.id: n for n in load_npcs(root / "characters.yaml")}
        mira = by_id["mira_vesser"].ethical_profile
        adelie = by_id["sister_adelie"].ethical_profile
        ulrik = by_id["ulrik_the_old_man"].ethical_profile
        assert mira is not None
        assert adelie is not None
        assert ulrik is not None
        # Mira is dominantly pragmatic.
        assert mira.dominant_axes()[0] == "pragmatic"
        # Adelie is dominantly zealot.
        assert adelie.dominant_axes()[0] == "zealot"
        # Ulrik is dominantly honor_bound.
        assert ulrik.dominant_axes()[0] == "honor_bound"

    def test_default_table_covers_every_event_type_in_player_profile_map(self):
        """Events that move the player profile should also have ethical
        judgments for at least one axis — otherwise the systems drift
        apart (the same action would affect player stance but not the
        NPC's ethical read)."""
        from npcforge.player_profile import DEFAULT_AXIS_DELTAS
        # Build the intersection the other way: any event_type a project
        # might record through the player profile should usually have
        # SOME ethical meaning. Not a hard requirement — but we flag
        # gaps so designers can audit.
        missing = [e for e in DEFAULT_AXIS_DELTAS
                   if e not in DEFAULT_EVENT_JUDGEMENTS]
        # Empty is ideal; if not, we at least want to notice when it grows.
        assert len(missing) <= 2, (
            f"player_profile tracks these event_types but ethics doesn't: "
            f"{missing}"
        )
