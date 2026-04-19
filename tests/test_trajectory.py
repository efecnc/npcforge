"""Tests for v0.17.0 relationship trajectory — the final roadmap item."""

from __future__ import annotations

from pathlib import Path

import pytest

from npcforge.memory import MemoryStore
from npcforge.prompts import build_npc_respondent_prompt
from npcforge.schemas import (
    NpcSheet,
    RelationshipTrajectory,
    TrajectoryWaypoint,
    load_npcs,
)
from npcforge.trajectory import (
    DEFAULT_EVENT_DELTAS,
    evaluate_trajectory,
    resolve_event_deltas,
    summarize_trajectory,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _three_waypoint_npc() -> NpcSheet:
    return NpcSheet(
        id="mira", name="Mira", role="tavernkeeper", voice="gruff",
        trajectory=RelationshipTrajectory(
            waypoints=[
                TrajectoryWaypoint(
                    id="stranger", label="stranger", min_score=0.0,
                    voice_shift="terse"),
                TrajectoryWaypoint(
                    id="tolerated", label="tolerated", min_score=0.3,
                    voice_shift="warmer"),
                TrajectoryWaypoint(
                    id="trusted", label="trusted", min_score=0.8,
                    voice_shift="full sentences",
                    unlocks_knowledge=["secret_x"]),
            ],
        ),
    )


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class TestSchema:
    def test_min_length_enforced(self):
        with pytest.raises(Exception):
            RelationshipTrajectory(waypoints=[])

    def test_waypoint_by_id(self):
        npc = _three_waypoint_npc()
        assert npc.trajectory.waypoint_by_id("trusted").label == "trusted"
        assert npc.trajectory.waypoint_by_id("nope") is None


# ---------------------------------------------------------------------------
# Resolve deltas
# ---------------------------------------------------------------------------


class TestResolveDeltas:
    def test_npc_override_replaces_default(self):
        traj = RelationshipTrajectory(
            waypoints=[TrajectoryWaypoint(id="a", label="a", min_score=0)],
            event_deltas={"player_lied": -1.0},
        )
        resolved = resolve_event_deltas(traj)
        assert resolved["player_lied"] == -1.0
        # Other defaults preserved.
        assert resolved["gift_given"] == DEFAULT_EVENT_DELTAS["gift_given"]

    def test_npc_can_zero_out_default(self):
        traj = RelationshipTrajectory(
            waypoints=[TrajectoryWaypoint(id="a", label="a", min_score=0)],
            event_deltas={"gift_given": 0.0},
        )
        resolved = resolve_event_deltas(traj)
        assert resolved["gift_given"] == 0.0


# ---------------------------------------------------------------------------
# Evaluate
# ---------------------------------------------------------------------------


class TestEvaluate:
    def test_no_trajectory_returns_none(self):
        npc = NpcSheet(id="x", name="X", role="y", voice="z")
        assert evaluate_trajectory(npc, MemoryStore()) is None

    def test_empty_store_below_lowest_waypoint(self):
        npc = _three_waypoint_npc()
        reading = evaluate_trajectory(npc, MemoryStore())
        # score = 0.0; lowest waypoint sits at min_score 0.0 so current = stranger.
        assert reading is not None
        assert reading.current is not None
        assert reading.current.id == "stranger"

    def test_gift_nudges_toward_tolerated(self):
        npc = _three_waypoint_npc()
        store = MemoryStore()
        # One gift gives +0.10 (default) — not enough to cross 0.3.
        store.record(npc_id="mira", event_type="gift_given",
                     summary="x", salience="notable", turn=1)
        store.current_turn = 1
        r = evaluate_trajectory(npc, store)
        assert r.current.id == "stranger"
        assert r.next_waypoint.id == "tolerated"
        # Three gifts (+0.30) crosses the boundary.
        for i in range(2):
            store.record(npc_id="mira", event_type="gift_given",
                         summary="x", salience="notable", turn=2 + i)
        store.current_turn = 3
        r = evaluate_trajectory(npc, store)
        assert r.current.id == "tolerated"

    def test_negative_event_can_push_back(self):
        npc = _three_waypoint_npc()
        store = MemoryStore()
        store.record(npc_id="mira", event_type="gift_given",
                     summary="x", salience="notable", turn=1)
        store.record(npc_id="mira", event_type="gift_given",
                     summary="x", salience="notable", turn=2)
        store.record(npc_id="mira", event_type="gift_given",
                     summary="x", salience="notable", turn=3)
        store.current_turn = 3
        assert evaluate_trajectory(npc, store).current.id == "tolerated"
        # Now a lie: -0.20, dropping score to 0.10 — back to stranger.
        store.record(npc_id="mira", event_type="player_lied",
                     summary="x", salience="pivotal", turn=4)
        store.current_turn = 4
        assert evaluate_trajectory(npc, store).current.id == "stranger"

    def test_decay_reduces_old_event_contribution(self):
        npc = NpcSheet(
            id="mira", name="M", role="r", voice="v",
            trajectory=RelationshipTrajectory(
                waypoints=[
                    TrajectoryWaypoint(id="a", label="a", min_score=0.0),
                    TrajectoryWaypoint(id="b", label="b", min_score=0.2),
                ],
                decay_per_turn=0.02,
            ),
        )
        store = MemoryStore()
        # One gift_given at turn 0 (+0.10).
        store.record(npc_id="mira", event_type="gift_given",
                     summary="x", salience="notable", turn=0)
        # At turn 0 the score is +0.10 (below 0.2).
        store.current_turn = 0
        r = evaluate_trajectory(npc, store)
        assert r.score == pytest.approx(0.10, abs=1e-6)
        # At turn 5 decay is 5 * 0.02 = 0.10 — event magnitude
        # reduces to 0, score = 0.
        store.current_turn = 5
        r = evaluate_trajectory(npc, store)
        assert r.score == pytest.approx(0.0, abs=1e-6)

    def test_decay_cannot_flip_sign(self):
        npc = NpcSheet(
            id="mira", name="M", role="r", voice="v",
            trajectory=RelationshipTrajectory(
                waypoints=[TrajectoryWaypoint(id="a", label="a", min_score=0)],
                decay_per_turn=10.0,  # brutal
            ),
        )
        store = MemoryStore()
        store.record(npc_id="mira", event_type="gift_given",
                     summary="x", salience="notable", turn=0)
        store.current_turn = 100
        r = evaluate_trajectory(npc, store)
        assert r.score >= 0  # clamped — never flips to negative

    def test_custom_event_delta_overrides_default(self):
        npc = NpcSheet(
            id="mira", name="M", role="r", voice="v",
            trajectory=RelationshipTrajectory(
                waypoints=[
                    TrajectoryWaypoint(id="a", label="a", min_score=0.0),
                    TrajectoryWaypoint(id="b", label="b", min_score=0.5),
                ],
                event_deltas={"gift_given": 1.0},  # per-NPC override
            ),
        )
        store = MemoryStore()
        store.record(npc_id="mira", event_type="gift_given",
                     summary="x", salience="notable", turn=1)
        store.current_turn = 1
        r = evaluate_trajectory(npc, store)
        # One gift now worth +1.0 instead of +0.10 → crosses into b.
        assert r.current.id == "b"


# ---------------------------------------------------------------------------
# Summariser
# ---------------------------------------------------------------------------


class TestSummarize:
    def test_empty_when_none(self):
        npc = NpcSheet(id="x", name="X", role="y", voice="z")
        assert summarize_trajectory(npc, None) == ""

    def test_empty_when_reading_has_no_current(self):
        npc = _three_waypoint_npc()
        from npcforge.trajectory import TrajectoryReading
        reading = TrajectoryReading(
            npc_id="mira", score=-99.0, current=None,
            next_waypoint=None, distance_to_next=0.0, top_events=[],
        )
        assert summarize_trajectory(npc, reading) == ""

    def test_renders_waypoint_unlocks_and_top_events(self):
        npc = _three_waypoint_npc()
        store = MemoryStore()
        store.record(npc_id="mira", event_type="secret_shared",
                     summary="revealed something difficult",
                     salience="pivotal", turn=1)
        store.record(npc_id="mira", event_type="offer_help",
                     summary="offered to help her",
                     salience="notable", turn=2)
        store.record(npc_id="mira", event_type="gift_given",
                     summary="bought her a drink",
                     salience="notable", turn=3)
        store.current_turn = 3
        reading = evaluate_trajectory(npc, store)
        # secret_shared (+0.25) + offer_help (+0.12) + gift (+0.10) = +0.47
        # → trusted should NOT fire (min 0.8); tolerated (min 0.3) wins.
        block = summarize_trajectory(npc, reading)
        assert "Relationship trajectory" in block
        assert "tolerated" in block
        # Top-weighted should include secret_shared.
        assert "secret_shared" in block
        # Never narrate.
        assert "Never say the waypoint name aloud" in block


# ---------------------------------------------------------------------------
# Prompt wiring
# ---------------------------------------------------------------------------


class TestPromptWiring:
    def test_block_absent_when_empty_kwarg(self):
        npc = _three_waypoint_npc()
        prompt = build_npc_respondent_prompt(npc)
        # Rule 16 mentions "Relationship trajectory"; distinguish block
        # by a phrase only the summariser emits.
        assert "DO NOT narrate the mechanic" not in prompt

    def test_block_present_when_kwarg_supplied(self):
        npc = _three_waypoint_npc()
        prompt = build_npc_respondent_prompt(
            npc,
            trajectory_block=(
                "Relationship trajectory with this player (your private "
                "read on how close they've come to you; DO NOT narrate "
                "the mechanic or name the waypoint to them):\n"
                "- Current waypoint: trusted (trusted)."
            ),
        )
        assert "DO NOT narrate the mechanic" in prompt
        assert "trusted (trusted)" in prompt

    def test_rule_16_present(self):
        npc = NpcSheet(id="x", name="X", role="y", voice="z")
        prompt = build_npc_respondent_prompt(npc)
        assert "16. If a 'Relationship trajectory' block" in prompt


# ---------------------------------------------------------------------------
# Rusted Lantern demo shapes
# ---------------------------------------------------------------------------


class TestRustedLanternShapes:
    def test_kess_flips_faster_than_mira(self):
        """Mira's slow-build requires bigger score to reach the top;
        Kess's fast-flip reaches the top on fewer events."""
        root = Path(__file__).resolve().parent.parent / "examples/rusted_lantern"
        by_id = {n.id: n for n in load_npcs(root / "characters.yaml")}
        mira = by_id["mira_vesser"]
        kess = by_id["kess_the_knife"]
        assert mira.trajectory is not None
        assert kess.trajectory is not None

        # Kess's top waypoint sits at a LOWER min_score than Mira's.
        mira_top = max(w.min_score for w in mira.trajectory.waypoints)
        kess_top = max(w.min_score for w in kess.trajectory.waypoints)
        assert kess_top < mira_top

        # Kess overrides secret_shared upward — a strong positive
        # signal for him.
        kess_deltas = resolve_event_deltas(kess.trajectory)
        mira_deltas = resolve_event_deltas(mira.trajectory)
        assert kess_deltas["secret_shared"] > mira_deltas["secret_shared"]
