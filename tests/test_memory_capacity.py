"""Tests for v0.19.0 MemoryStore capacity + eviction."""

from __future__ import annotations

from pathlib import Path

import pytest

from npcforge.arcs import ARC_LATCH_EVENT_TYPE
from npcforge.memory import MemoryStore


# ---------------------------------------------------------------------------
# Default unbounded behaviour (backwards compat)
# ---------------------------------------------------------------------------


class TestUnboundedDefault:
    def test_default_max_events_is_zero_unbounded(self):
        s = MemoryStore()
        assert s.max_events == 0

    def test_unbounded_store_grows_without_eviction(self):
        s = MemoryStore()  # default unbounded
        for i in range(50):
            s.record(npc_id="mira", event_type="x",
                     summary=str(i), salience="trivial", turn=i)
        assert len(s.events) == 50


# ---------------------------------------------------------------------------
# Capacity with eviction
# ---------------------------------------------------------------------------


class TestCapacityEviction:
    def test_evicts_lowest_salience_when_full(self):
        s = MemoryStore(max_events=3)
        s.record(npc_id="mira", event_type="a",
                 summary="trivial", salience="trivial", turn=1)
        s.record(npc_id="mira", event_type="b",
                 summary="pivotal", salience="pivotal", turn=2)
        s.record(npc_id="mira", event_type="c",
                 summary="notable", salience="notable", turn=3)
        # Adding a fourth should evict the trivial one first.
        s.record(npc_id="mira", event_type="d",
                 summary="notable2", salience="notable", turn=4)
        summaries = [e.summary for e in s.events]
        assert "trivial" not in summaries
        assert "pivotal" in summaries
        assert "notable" in summaries
        assert "notable2" in summaries

    def test_ties_broken_by_oldest_turn(self):
        s = MemoryStore(max_events=2)
        s.record(npc_id="mira", event_type="a",
                 summary="old", salience="notable", turn=1)
        s.record(npc_id="mira", event_type="b",
                 summary="mid", salience="notable", turn=5)
        s.record(npc_id="mira", event_type="c",
                 summary="new", salience="notable", turn=10)
        # Oldest-same-salience evicted first.
        summaries = {e.summary for e in s.events}
        assert "old" not in summaries
        assert "mid" in summaries
        assert "new" in summaries

    def test_pivotal_survives_flood_of_trivial(self):
        s = MemoryStore(max_events=5)
        s.record(npc_id="mira", event_type="secret",
                 summary="PIVOTAL", salience="pivotal", turn=1)
        for i in range(20):
            s.record(npc_id="mira", event_type="chat",
                     summary=f"chat{i}", salience="trivial", turn=i + 2)
        summaries = [e.summary for e in s.events]
        assert "PIVOTAL" in summaries  # never evicted
        assert len(s.events) == 5

    def test_arc_latch_events_preserved(self):
        s = MemoryStore(max_events=2)
        s.record(npc_id="mira", event_type=ARC_LATCH_EVENT_TYPE,
                 summary="arc stage 'trusted' latched",
                 salience="notable", turn=1)
        s.record(npc_id="mira", event_type="a",
                 summary="trivial", salience="trivial", turn=2)
        s.record(npc_id="mira", event_type="b",
                 summary="another trivial", salience="trivial", turn=3)
        # Third record should evict a trivial event, not the latch.
        summaries = [e.summary for e in s.events]
        assert "arc stage 'trusted' latched" in summaries

    def test_all_latched_store_falls_through_on_eviction(self):
        """If every event is an arc-latch, we can't evict any — new
        events still get appended (the latch ceiling is a soft guarantee,
        not a hard block)."""
        s = MemoryStore(max_events=2)
        s.record(npc_id="mira", event_type=ARC_LATCH_EVENT_TYPE,
                 summary="arc stage 'a' latched",
                 salience="notable", turn=1)
        s.record(npc_id="mira", event_type=ARC_LATCH_EVENT_TYPE,
                 summary="arc stage 'b' latched",
                 salience="notable", turn=2)
        s.record(npc_id="mira", event_type="chat",
                 summary="third event", salience="trivial", turn=3)
        assert len(s.events) == 3  # no eviction possible


# ---------------------------------------------------------------------------
# Persistence round-trips max_events
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_save_includes_max_events(self, tmp_path: Path):
        s = MemoryStore(max_events=25)
        path = tmp_path / "mem.json"
        s.save(path)
        reloaded = MemoryStore.load(path)
        assert reloaded.max_events == 25

    def test_legacy_save_without_max_events_loads_unbounded(self, tmp_path: Path):
        path = tmp_path / "mem.json"
        path.write_text(
            '{"schemaVersion": "1", "currentTurn": 5, "events": []}',
            encoding="utf-8",
        )
        reloaded = MemoryStore.load(path)
        assert reloaded.max_events == 0
        assert reloaded.current_turn == 5
