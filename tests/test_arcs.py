"""Tests for the v0.10.0 campaign-scale arc system."""

from __future__ import annotations

from pathlib import Path

import pytest

from npcforge.arcs import (
    ARC_LATCH_EVENT_TYPE,
    evaluate_arc,
    newly_latched_stages,
    record_latch,
)
from npcforge.memory import MemoryStore
from npcforge.prompts import build_npc_respondent_prompt
from npcforge.schemas import (
    ArcStage,
    FactionsConfig,
    KnowledgeItem,
    NpcArc,
    NpcSheet,
    TriggerSpec,
    load_npcs,
    validate_npc_arcs,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _npc_with_arc(*stages: ArcStage, knowledge: list[KnowledgeItem] | None = None,
                  faction_id: str = "", secondary: str = "") -> NpcSheet:
    return NpcSheet(
        id="mira",
        name="Mira",
        role="tavernkeeper",
        voice="gruff",
        faction_id=faction_id,
        secondary_faction_id=secondary,
        knowledge=knowledge or [],
        arc=NpcArc(stages=list(stages)),
    )


def _three_stage_arc_npc() -> NpcSheet:
    return _npc_with_arc(
        ArcStage(id="stranger", label="stranger", voice_shift="brief"),
        ArcStage(
            id="tolerated", label="tolerated",
            voice_shift="warmer",
            trigger=TriggerSpec(min_total_events=3),
        ),
        ArcStage(
            id="trusted", label="trusted",
            voice_shift="full sentences",
            trigger=TriggerSpec(
                min_pivotal_events=2,
                min_standing={"lantern_regulars": 10},
            ),
            unlocks_knowledge=["k1"],
        ),
        knowledge=[KnowledgeItem(id="k1", fact="hidden thing")],
        faction_id="lantern_regulars",
    )


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


class TestArcSchemaValidation:
    def test_duplicate_stage_ids_rejected(self):
        npc = _npc_with_arc(
            ArcStage(id="a", label="a", voice_shift="."),
            ArcStage(id="a", label="b", voice_shift=".",
                     trigger=TriggerSpec(min_total_events=1)),
        )
        with pytest.raises(ValueError, match="duplicate arc stage id"):
            validate_npc_arcs([npc])

    def test_unlocks_unknown_knowledge_rejected(self):
        npc = _npc_with_arc(
            ArcStage(id="a", label="a", voice_shift="."),
            ArcStage(id="b", label="b", voice_shift=".",
                     trigger=TriggerSpec(min_total_events=1),
                     unlocks_knowledge=["ghost"]),
        )
        with pytest.raises(ValueError, match="unknown knowledge ids"):
            validate_npc_arcs([npc])

    def test_non_baseline_empty_trigger_rejected(self):
        # Second stage with no trigger fields set => redundant.
        npc = _npc_with_arc(
            ArcStage(id="a", label="a", voice_shift="."),
            ArcStage(id="b", label="b", voice_shift="."),
        )
        with pytest.raises(ValueError, match="empty trigger"):
            validate_npc_arcs([npc])

    def test_npcs_without_arcs_pass(self):
        npc = NpcSheet(id="x", name="X", role="r", voice="v")
        validate_npc_arcs([npc])  # no exception

    def test_rusted_lantern_arcs_validate(self):
        root = Path(__file__).resolve().parent.parent / "examples/rusted_lantern"
        npcs = load_npcs(root / "characters.yaml")
        validate_npc_arcs(npcs)


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------


class TestEvaluateArc:
    def test_baseline_stage_active_with_no_memory(self):
        npc = _three_stage_arc_npc()
        active = evaluate_arc(npc, store=None, standings=None)
        assert [a.stage.id for a in active] == ["stranger"]
        assert all(not a.latched for a in active)

    def test_next_stage_fires_when_trigger_met(self):
        npc = _three_stage_arc_npc()
        store = MemoryStore()
        for i in range(3):
            store.record(npc_id="mira", event_type="chat", summary=f"turn {i}",
                         salience="trivial", turn=i)
        active = evaluate_arc(npc, store=store)
        assert [a.stage.id for a in active] == ["stranger", "tolerated"]

    def test_standing_gate_blocks_later_stage(self):
        npc = _three_stage_arc_npc()
        store = MemoryStore()
        # 3 pivotal events satisfy min_pivotal_events=2, but we pin
        # lantern_regulars standing below the required floor.
        for i in range(3):
            store.record(npc_id="mira", event_type="gift", summary="x",
                         salience="pivotal", turn=i)
        active = evaluate_arc(npc, store=store, standings={"lantern_regulars": 5})
        # stranger + tolerated fire; trusted held back by standing.
        assert [a.stage.id for a in active] == ["stranger", "tolerated"]
        # Bump the standing above the floor → trusted fires.
        active = evaluate_arc(npc, store=store, standings={"lantern_regulars": 20})
        assert [a.stage.id for a in active] == ["stranger", "tolerated", "trusted"]

    def test_faction_shared_events_count_toward_triggers(self):
        npc = _three_stage_arc_npc()
        store = MemoryStore()
        # No events for Mira personally, but three faction-shared ones.
        for i in range(3):
            store.record(npc_id="other", event_type="chat", summary="x",
                         salience="trivial", faction_id="lantern_regulars",
                         turn=i)
        active = evaluate_arc(npc, store=store)
        assert [a.stage.id for a in active] == ["stranger", "tolerated"]

    def test_latched_stage_stays_active_after_conditions_fail(self):
        npc = _three_stage_arc_npc()
        store = MemoryStore()
        # Record a latch for 'tolerated' directly — simulates prior session.
        record_latch(npc, npc.arc.stages[1], store)
        # No other events, no standing — tolerated shouldn't fire fresh,
        # but the latch keeps it active.
        active = evaluate_arc(npc, store=store)
        assert [a.stage.id for a in active] == ["stranger", "tolerated"]
        # The latched stage should report latched=True.
        tolerated = [a for a in active if a.stage.id == "tolerated"][0]
        assert tolerated.latched

    def test_required_event_types_must_all_be_present(self):
        npc = _npc_with_arc(
            ArcStage(id="a", label="a", voice_shift="."),
            ArcStage(
                id="b", label="b", voice_shift=".",
                trigger=TriggerSpec(required_event_types=["gift", "secret"]),
            ),
        )
        store = MemoryStore()
        store.record(npc_id="mira", event_type="gift", summary="x",
                     salience="pivotal", turn=1)
        active = evaluate_arc(npc, store=store)
        assert [a.stage.id for a in active] == ["a"]  # b blocked: secret missing
        store.record(npc_id="mira", event_type="secret", summary="y",
                     salience="pivotal", turn=2)
        active = evaluate_arc(npc, store=store)
        assert [a.stage.id for a in active] == ["a", "b"]

    def test_max_standing_can_block_stage(self):
        npc = _npc_with_arc(
            ArcStage(id="a", label="a", voice_shift="."),
            ArcStage(
                id="b", label="b", voice_shift=".",
                trigger=TriggerSpec(max_standing={"councils": -10}),
            ),
        )
        active = evaluate_arc(npc, standings={"councils": 0})
        assert [a.stage.id for a in active] == ["a"]
        active = evaluate_arc(npc, standings={"councils": -15})
        assert [a.stage.id for a in active] == ["a", "b"]

    def test_newly_latched_stages_skips_already_latched(self):
        npc = _three_stage_arc_npc()
        store = MemoryStore()
        for i in range(3):
            store.record(npc_id="mira", event_type="chat", summary="x",
                         salience="trivial", turn=i)
        # First call — tolerated is newly latchable.
        fresh = newly_latched_stages(npc, store)
        assert [a.stage.id for a in fresh] == ["tolerated"]
        # Simulate the runtime recording the latch.
        record_latch(npc, npc.arc.stages[1], store)
        # Second call — tolerated already latched, so not "newly" latchable.
        fresh = newly_latched_stages(npc, store)
        assert fresh == []

    def test_arc_latch_events_dont_count_toward_triggers(self):
        """Latch events are bookkeeping, not narrative history — they
        must not inflate min_total_events for later stages."""
        npc = _npc_with_arc(
            ArcStage(id="a", label="a", voice_shift="."),
            ArcStage(
                id="b", label="b", voice_shift=".",
                trigger=TriggerSpec(min_total_events=2),
            ),
        )
        store = MemoryStore()
        # Only the latch event for 'a'. No real story events.
        store.record(
            npc_id="mira",
            event_type=ARC_LATCH_EVENT_TYPE,
            summary="arc stage 'a' latched",
            salience="notable",
            turn=0,
        )
        active = evaluate_arc(npc, store=store)
        # b must not activate — only the latch exists, which shouldn't count.
        assert [a.stage.id for a in active] == ["a"]


# ---------------------------------------------------------------------------
# Prompt wiring
# ---------------------------------------------------------------------------


class TestArcPromptBlock:
    def test_prompt_renders_active_stages_cumulatively(self):
        npc = _three_stage_arc_npc()
        store = MemoryStore()
        for i in range(3):
            store.record(npc_id="mira", event_type="gift", summary="x",
                         salience="pivotal", turn=i)
        active = evaluate_arc(npc, store=store,
                              standings={"lantern_regulars": 30})
        prompt = build_npc_respondent_prompt(npc, arc_stages=active)
        assert "Character arc" in prompt
        # All three stages listed in order.
        assert prompt.index("stranger") < prompt.index("tolerated") < prompt.index("trusted")
        # Knowledge unlock surfaced.
        assert "Unlocked knowledge ids" in prompt
        assert "k1" in prompt

    def test_prompt_omits_arc_block_when_no_stages_active(self):
        npc = NpcSheet(id="x", name="X", role="r", voice="v")
        prompt = build_npc_respondent_prompt(npc, arc_stages=[])
        # Rule 12 references "Character arc" by name — check for the
        # block-specific marker instead to tell data from rule text.
        assert "currently-active stages" not in prompt

    def test_prompt_renders_custom_condition_when_set(self):
        npc = _npc_with_arc(
            ArcStage(id="a", label="a", voice_shift="base"),
            ArcStage(
                id="b", label="b", voice_shift="shift",
                trigger=TriggerSpec(
                    min_total_events=1,
                    custom_condition="player has sat in silence with them once",
                ),
            ),
        )
        store = MemoryStore()
        store.record(npc_id="mira", event_type="x", summary="y",
                     salience="notable", turn=0)
        active = evaluate_arc(npc, store=store)
        prompt = build_npc_respondent_prompt(npc, arc_stages=active)
        assert "Narrative condition: player has sat in silence" in prompt

    def test_rule_12_present_in_base_rules(self):
        npc = NpcSheet(id="x", name="X", role="r", voice="v")
        prompt = build_npc_respondent_prompt(npc)
        assert "12. If a 'Character arc' block" in prompt
