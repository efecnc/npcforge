"""Tests for v0.20.0 emotion state."""

from __future__ import annotations

import pytest

from npcforge.emotion import (
    DEFAULT_EMOTION_DELTAS,
    EMOTION_AXES,
    EmotionState,
    compute_emotion_state,
    summarize_emotion_state,
)
from npcforge.memory import MemoryStore
from npcforge.prompts import build_npc_respondent_prompt
from npcforge.schemas import NpcSheet


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _npc(faction: str = "", secondary: str = "") -> NpcSheet:
    return NpcSheet(
        id="mira", name="M", role="r", voice="v",
        faction_id=faction, secondary_faction_id=secondary,
    )


# ---------------------------------------------------------------------------
# EmotionState + summariser
# ---------------------------------------------------------------------------


class TestEmotionStateShape:
    def test_empty_state_has_no_dominant(self):
        assert EmotionState().dominant() is None

    def test_low_intensity_below_threshold_no_dominant(self):
        state = EmotionState(axes={"joy": 0.05})
        assert state.dominant() is None  # below 0.1 default

    def test_dominant_picks_highest(self):
        state = EmotionState(axes={"joy": 0.3, "fear": 0.7, "anger": 0.4})
        dom = state.dominant()
        assert dom is not None
        assert dom[0] == "fear"
        assert dom[1] == pytest.approx(0.7)

    def test_top_n_sorted_descending(self):
        state = EmotionState(axes={
            "joy": 0.2, "fear": 0.7, "anger": 0.4, "trust": 0.05,
        })
        top = state.top(n=2, min_intensity=0.1)
        assert [a for a, _ in top] == ["fear", "anger"]


class TestSummariser:
    def test_empty_returns_empty(self):
        assert summarize_emotion_state(EmotionState()) == ""

    def test_below_threshold_returns_empty(self):
        assert summarize_emotion_state(EmotionState(axes={"joy": 0.02})) == ""

    def test_renders_dominant_and_guards_against_narration(self):
        block = summarize_emotion_state(
            EmotionState(axes={"fear": 0.7, "anger": 0.5})
        )
        assert "Current emotional state" in block
        assert "fear: 0.70" in block
        assert "anger: 0.50" in block
        assert "Dominant tone: fear" in block
        assert "never narrate" in block
        # The rule that the LLM should NOT name emotions aloud is
        # spelled out verbatim.
        assert "surface naturally in register" in block


# ---------------------------------------------------------------------------
# compute_emotion_state
# ---------------------------------------------------------------------------


class TestComputeEmotionState:
    def test_empty_memory_returns_empty_state(self):
        store = MemoryStore()
        assert compute_emotion_state(_npc(), store).axes == {}

    def test_threat_raises_fear_and_anger(self):
        store = MemoryStore()
        store.record(npc_id="mira", event_type="threat",
                     summary="x", salience="pivotal", turn=1)
        store.current_turn = 1
        state = compute_emotion_state(_npc(), store, decay_per_turn=0.0)
        assert state.get("fear") == pytest.approx(0.40)
        assert state.get("anger") == pytest.approx(0.30)

    def test_secret_shared_raises_trust(self):
        store = MemoryStore()
        store.record(npc_id="mira", event_type="secret_shared",
                     summary="x", salience="pivotal", turn=1)
        store.current_turn = 1
        state = compute_emotion_state(_npc(), store, decay_per_turn=0.0)
        assert state.get("trust") == pytest.approx(0.40)

    def test_decay_reduces_magnitude_over_turns(self):
        store = MemoryStore()
        store.record(npc_id="mira", event_type="threat",
                     summary="x", salience="pivotal", turn=0)
        # Fear base delta = +0.40. With decay 0.05/turn, after 4 turns
        # magnitude = max(0.40 - 0.20, 0) = 0.20.
        store.current_turn = 4
        state = compute_emotion_state(_npc(), store, decay_per_turn=0.05)
        assert state.get("fear") == pytest.approx(0.20)

    def test_decay_zeros_out_stale_events(self):
        store = MemoryStore()
        store.record(npc_id="mira", event_type="threat",
                     summary="x", salience="pivotal", turn=0)
        # 10 * 0.05 > 0.40 → fear contribution zeros out entirely.
        store.current_turn = 10
        state = compute_emotion_state(_npc(), store, decay_per_turn=0.05)
        assert "fear" not in state.axes

    def test_negative_deltas_clamp_at_zero_do_not_go_negative(self):
        store = MemoryStore()
        # player_lied contributes trust: -0.20. With no prior trust,
        # the result should clamp to 0 (axes drop out), not be negative.
        store.record(npc_id="mira", event_type="player_lied",
                     summary="x", salience="pivotal", turn=1)
        store.current_turn = 1
        state = compute_emotion_state(_npc(), store, decay_per_turn=0.0)
        assert "trust" not in state.axes
        assert state.get("trust") == 0.0
        # Positive axes from the same event still register.
        assert state.get("disgust") > 0

    def test_faction_shared_events_fold_in(self):
        npc = _npc(faction="lantern")
        store = MemoryStore()
        store.record(npc_id="other", event_type="faction_helped",
                     summary="x", salience="pivotal",
                     faction_id="lantern", turn=1)
        store.current_turn = 1
        state = compute_emotion_state(npc, store, decay_per_turn=0.0)
        assert state.get("joy") > 0
        assert state.get("trust") > 0

    def test_unknown_event_ignored(self):
        store = MemoryStore()
        store.record(npc_id="mira", event_type="totally_new_event_type",
                     summary="x", salience="notable", turn=1)
        store.current_turn = 1
        state = compute_emotion_state(_npc(), store, decay_per_turn=0.0)
        assert state.axes == {}

    def test_all_plutchik_axes_reachable(self):
        """Ensure the default table covers every Plutchik axis as a
        positive delta somewhere — otherwise an axis is dead weight."""
        covered: set[str] = set()
        for deltas in DEFAULT_EMOTION_DELTAS.values():
            for axis, v in deltas.items():
                if v > 0:
                    covered.add(axis)
        assert set(EMOTION_AXES) == covered

    def test_clamps_at_one(self):
        store = MemoryStore()
        # Stack enough events to overflow the clamp.
        for i in range(5):
            store.record(npc_id="mira", event_type="secret_shared",
                         summary="x", salience="pivotal", turn=i)
        store.current_turn = 5
        state = compute_emotion_state(_npc(), store, decay_per_turn=0.0)
        assert state.get("trust") == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Prompt wiring
# ---------------------------------------------------------------------------


class TestPromptWiring:
    def test_block_absent_when_kwarg_empty(self):
        npc = NpcSheet(id="x", name="X", role="r", voice="v")
        prompt = build_npc_respondent_prompt(npc)
        # Rule 18 text mentions "Current emotional state"; distinguish
        # actual block by a render-only phrase.
        assert "Dominant tone:" not in prompt

    def test_block_present_when_kwarg_supplied(self):
        npc = NpcSheet(id="x", name="X", role="r", voice="v")
        prompt = build_npc_respondent_prompt(
            npc,
            emotion_block=(
                "Current emotional state (YOUR internal feeling):\n"
                "- fear: 0.70\nDominant tone: fear."
            ),
        )
        assert "Dominant tone: fear" in prompt

    def test_rule_18_present(self):
        npc = NpcSheet(id="x", name="X", role="r", voice="v")
        prompt = build_npc_respondent_prompt(npc)
        assert "18. If a 'Current emotional state' block" in prompt
