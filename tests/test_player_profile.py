"""Tests for v0.13.0 player modeling."""

from __future__ import annotations

from pathlib import Path

import pytest

from npcforge.improv import build_improv_system_prompt
from npcforge.memory import MemoryStore
from npcforge.player_profile import (
    DEFAULT_AXIS_DELTAS,
    PlayerProfile,
    apply_event,
    rebuild_from_store,
    summarize_for_observer,
)
from npcforge.prompts import build_npc_respondent_prompt
from npcforge.schemas import NpcSheet


# ---------------------------------------------------------------------------
# Schema + persistence
# ---------------------------------------------------------------------------


class TestPlayerProfileSchema:
    def test_empty_profile_reads_zero(self):
        p = PlayerProfile()
        assert p.get("aggressive") == 0.0
        assert p.top_traits() == []

    def test_save_load_round_trip(self, tmp_path: Path):
        p = PlayerProfile()
        apply_event(p, "threat")
        apply_event(p, "gift_given")
        path = tmp_path / "profile.json"
        p.save(path)
        reloaded = PlayerProfile.load(path)
        assert reloaded.get("aggressive") == pytest.approx(0.20)
        assert reloaded.get("patient") == pytest.approx(0.10)

    def test_load_missing_file_returns_empty_profile(self, tmp_path: Path):
        p = PlayerProfile.load(tmp_path / "missing.json")
        assert p.axes == {}


# ---------------------------------------------------------------------------
# apply_event
# ---------------------------------------------------------------------------


class TestApplyEvent:
    def test_threat_nudges_aggressive_axis(self):
        p = PlayerProfile()
        apply_event(p, "threat")
        assert p.get("aggressive") == pytest.approx(0.20)

    def test_faction_harmed_applies_positive_and_negative_deltas(self):
        p = PlayerProfile()
        p.axes["loyal"] = 0.5  # pre-existing loyalty to push down
        apply_event(p, "faction_harmed")
        assert p.get("aggressive") == pytest.approx(0.10)
        assert p.get("loyal") == pytest.approx(0.40)

    def test_value_clamps_at_one(self):
        p = PlayerProfile()
        for _ in range(20):
            apply_event(p, "threat")
        assert p.get("aggressive") == 1.0

    def test_value_clamps_at_zero(self):
        p = PlayerProfile()
        p.axes["loyal"] = 0.02
        apply_event(p, "faction_harmed")  # nudges loyal by -0.10
        assert p.get("loyal") == 0.0

    def test_unknown_event_type_is_silent_noop(self):
        p = PlayerProfile()
        apply_event(p, "completely_unknown_event_type")
        assert p.axes == {}

    def test_decay_rate_shrinks_existing_axes(self):
        p = PlayerProfile()
        p.axes = {"aggressive": 0.8, "curious": 0.4}
        # threat nudges aggressive by +0.20; decay=0.5 shrinks both first.
        apply_event(p, "threat", decay_rate=0.5)
        # aggressive = 0.8 * 0.5 + 0.20 = 0.60
        assert p.get("aggressive") == pytest.approx(0.60)
        # curious has no delta — just decayed to 0.20
        assert p.get("curious") == pytest.approx(0.20)

    def test_custom_axis_deltas_override_defaults(self):
        p = PlayerProfile()
        custom = {"threat": {"scholarly": +0.50}}
        apply_event(p, "threat", axis_deltas=custom)
        assert p.get("scholarly") == pytest.approx(0.50)
        assert p.get("aggressive") == 0.0

    def test_turn_only_monotonic(self):
        p = PlayerProfile(updated_at_turn=5)
        apply_event(p, "threat", turn=3)
        assert p.updated_at_turn == 5
        apply_event(p, "threat", turn=10)
        assert p.updated_at_turn == 10


# ---------------------------------------------------------------------------
# rebuild_from_store
# ---------------------------------------------------------------------------


class TestRebuildFromStore:
    def test_rebuild_from_memory_store(self):
        store = MemoryStore()
        store.record(npc_id="mira", event_type="threat",
                     summary="x", salience="pivotal", turn=1)
        store.record(npc_id="mira", event_type="threat",
                     summary="x", salience="pivotal", turn=2)
        store.record(npc_id="mira", event_type="gift_given",
                     summary="y", salience="notable", turn=3)
        p = rebuild_from_store(store.events)
        assert p.get("aggressive") == pytest.approx(0.40)
        assert p.get("patient") == pytest.approx(0.10)

    def test_rebuild_ignores_unknown_event_types(self):
        store = MemoryStore()
        store.record(npc_id="mira", event_type="completely_novel",
                     summary="x", salience="notable", turn=1)
        p = rebuild_from_store(store.events)
        assert p.axes == {}


# ---------------------------------------------------------------------------
# Summariser
# ---------------------------------------------------------------------------


class TestSummarizeForObserver:
    def test_empty_profile_returns_empty_string(self):
        assert summarize_for_observer(PlayerProfile()) == ""

    def test_sub_threshold_profile_returns_empty_string(self):
        p = PlayerProfile()
        p.axes = {"aggressive": 0.10, "patient": 0.05}
        assert summarize_for_observer(p, min_weight=0.25) == ""

    def test_renders_top_traits_with_prose(self):
        p = PlayerProfile()
        p.axes = {"aggressive": 0.8, "curious": 0.4, "patient": 0.1}
        block = summarize_for_observer(p, max_traits=3, min_weight=0.2)
        assert "Player pattern" in block
        assert "aggressive" in block
        assert "curious" in block
        assert "patient" not in block  # below threshold
        # Axis weights are rendered as rounded numbers, not precise floats.
        assert "0.8" in block
        # Closing instruction against listing traits appears verbatim.
        assert "Do not list" in block

    def test_unknown_axis_falls_back_to_generic_phrase(self):
        p = PlayerProfile()
        p.axes = {"scholarly": 0.7}  # not in _AXIS_PROSE
        block = summarize_for_observer(p)
        assert "tends to be scholarly" in block


# ---------------------------------------------------------------------------
# Prompt wiring
# ---------------------------------------------------------------------------


class TestObserverPromptWiring:
    def test_respondent_prompt_hides_block_for_non_observer(self):
        npc = NpcSheet(id="x", name="X", role="y", voice="z",
                       observes_player=False)
        prompt = build_npc_respondent_prompt(
            npc, player_profile_block="Player pattern: ... aggressive (0.8)")
        assert "aggressive (0.8)" not in prompt

    def test_respondent_prompt_shows_block_for_observer(self):
        npc = NpcSheet(id="x", name="X", role="y", voice="z",
                       observes_player=True)
        prompt = build_npc_respondent_prompt(
            npc, player_profile_block="Player pattern (observed):\n- aggressive")
        assert "Player pattern (observed)" in prompt
        assert "- aggressive" in prompt

    def test_rule_13_present_in_base_rules(self):
        npc = NpcSheet(id="x", name="X", role="y", voice="z")
        prompt = build_npc_respondent_prompt(npc)
        assert "13. If a 'Player pattern' block" in prompt

    def test_improv_prompt_honours_observes_player_flag(self):
        npc_off = NpcSheet(id="a", name="A", role="r", voice="v",
                           observes_player=False)
        npc_on = NpcSheet(id="b", name="B", role="r", voice="v",
                          observes_player=True)
        block = "Player pattern (observed):\n- aggressive"
        prompt_off = build_improv_system_prompt(npc_off, lore_chunks=[],
                                                player_profile_block=block)
        prompt_on = build_improv_system_prompt(npc_on, lore_chunks=[],
                                               player_profile_block=block)
        assert "Player pattern (observed)" not in prompt_off
        assert "Player pattern (observed)" in prompt_on


# ---------------------------------------------------------------------------
# Sanity against Rusted Lantern
# ---------------------------------------------------------------------------


class TestRustedLanternObservers:
    def test_ulrik_and_kess_are_observers(self):
        root = Path(__file__).resolve().parent.parent / "examples/rusted_lantern"
        from npcforge.schemas import load_npcs

        by_id = {n.id: n for n in load_npcs(root / "characters.yaml")}
        assert by_id["ulrik_the_old_man"].observes_player
        assert by_id["kess_the_knife"].observes_player
        # Other cast members stay off by default.
        assert not by_id["mira_vesser"].observes_player
        assert not by_id["gereth_blackstone"].observes_player
        assert not by_id["sister_adelie"].observes_player
