"""Tests for v0.21.0 quest / story-state gating."""

from __future__ import annotations

from pathlib import Path

import pytest

from npcforge.arcs import evaluate_arc
from npcforge.memory import MemoryStore
from npcforge.prompts import build_npc_respondent_prompt
from npcforge.quests import QuestTracker, summarize_active_quests
from npcforge.schemas import (
    ArcStage,
    NpcArc,
    NpcSheet,
    Quest,
    QuestsConfig,
    QuestStage,
    TriggerSpec,
    load_quests,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _quest() -> Quest:
    return Quest(
        id="recover_locket",
        name="Recover the Locket",
        stages=[
            QuestStage(id="not_started", label="not started"),
            QuestStage(id="accepted", label="accepted"),
            QuestStage(id="clue_found", label="clue found"),
            QuestStage(id="confronted", label="confronted"),
        ],
    )


def _config() -> QuestsConfig:
    return QuestsConfig(quests=[_quest()])


# ---------------------------------------------------------------------------
# Schema + loader
# ---------------------------------------------------------------------------


class TestQuestSchema:
    def test_stage_index_lookup(self):
        q = _quest()
        assert q.stage_index("not_started") == 0
        assert q.stage_index("confronted") == 3
        assert q.stage_index("missing") == -1

    def test_loader_rejects_duplicate_stage_ids(self, tmp_path: Path):
        p = tmp_path / "quests.yaml"
        p.write_text(
            "quests:\n"
            "  - id: q\n    name: Q\n    stages:\n"
            "      - id: a\n        label: a\n"
            "      - id: a\n        label: b\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="duplicate stage id"):
            load_quests(p)

    def test_loader_missing_file_returns_empty(self, tmp_path: Path):
        cfg = load_quests(tmp_path / "nope.yaml")
        assert cfg.quests == []

    def test_rusted_lantern_quests_load(self):
        root = Path(__file__).resolve().parent.parent / "examples/rusted_lantern"
        cfg = load_quests(root / "quests.yaml")
        assert any(q.id == "recover_locket" for q in cfg.quests)


# ---------------------------------------------------------------------------
# Tracker
# ---------------------------------------------------------------------------


class TestQuestTrackerLifecycle:
    def test_set_stage_requires_valid_quest(self):
        cfg = _config()
        t = QuestTracker()
        with pytest.raises(KeyError, match="Unknown quest"):
            t.set_stage("ghost", "accepted", cfg)

    def test_set_stage_requires_valid_stage(self):
        cfg = _config()
        t = QuestTracker()
        with pytest.raises(KeyError, match="has no stage"):
            t.set_stage("recover_locket", "nowhere", cfg)

    def test_advance_from_unset_starts_first_stage(self):
        cfg = _config()
        t = QuestTracker()
        new = t.advance("recover_locket", cfg)
        assert new == "not_started"
        assert t.current_stage_id("recover_locket") == "not_started"

    def test_advance_ratchets_and_stops_at_end(self):
        cfg = _config()
        t = QuestTracker()
        for expected in ["not_started", "accepted", "clue_found", "confronted"]:
            assert t.advance("recover_locket", cfg) == expected
        # Next advance returns None (already at end).
        assert t.advance("recover_locket", cfg) is None

    def test_is_at_or_past_uses_index_comparison(self):
        cfg = _config()
        t = QuestTracker()
        t.set_stage("recover_locket", "clue_found", cfg)
        assert t.is_at_or_past("recover_locket", "accepted", cfg)
        assert t.is_at_or_past("recover_locket", "clue_found", cfg)
        assert not t.is_at_or_past("recover_locket", "confronted", cfg)

    def test_is_at_or_past_false_for_unset_quest(self):
        cfg = _config()
        t = QuestTracker()
        assert not t.is_at_or_past("recover_locket", "accepted", cfg)

    def test_active_states_skips_unstarted_quests(self):
        cfg = QuestsConfig(quests=[_quest(), Quest(
            id="other",
            name="Other",
            stages=[QuestStage(id="a", label="a")],
        )])
        t = QuestTracker()
        t.set_stage("recover_locket", "accepted", cfg)
        states = t.active_states(cfg)
        assert [s.quest_id for s in states] == ["recover_locket"]
        assert states[0].is_completed is False

    def test_save_load_round_trip(self, tmp_path: Path):
        cfg = _config()
        t = QuestTracker()
        t.set_stage("recover_locket", "clue_found", cfg)
        p = tmp_path / "quest_state.json"
        t.save(p)
        reloaded = QuestTracker.load(p)
        assert reloaded.current_stage_id("recover_locket") == "clue_found"

    def test_load_missing_returns_empty(self, tmp_path: Path):
        t = QuestTracker.load(tmp_path / "nothing.json")
        assert t.current_stages == {}


# ---------------------------------------------------------------------------
# Visibility (known_to filter)
# ---------------------------------------------------------------------------


class TestStageVisibility:
    def test_empty_known_to_visible_to_all(self):
        cfg = _config()
        t = QuestTracker()
        t.set_stage("recover_locket", "accepted", cfg)
        visible = t.stages_visible_to("anyone", cfg)
        assert len(visible) == 1

    def test_restricted_stage_filters_by_npc_id(self):
        cfg = QuestsConfig(quests=[Quest(
            id="secret",
            name="Secret",
            stages=[QuestStage(
                id="reached", label="reached",
                known_to=["mira", "ulrik"],
            )],
        )])
        t = QuestTracker()
        t.set_stage("secret", "reached", cfg)
        assert t.stages_visible_to("mira", cfg)
        assert t.stages_visible_to("ulrik", cfg)
        assert not t.stages_visible_to("kess", cfg)


# ---------------------------------------------------------------------------
# Arc quest gates
# ---------------------------------------------------------------------------


class TestArcQuestGates:
    def test_arc_stage_blocked_by_unmet_quest_gate(self):
        cfg = _config()
        npc = NpcSheet(id="mira", name="M", role="r", voice="v", arc=NpcArc(
            stages=[
                ArcStage(id="base", label="base", voice_shift="."),
                ArcStage(
                    id="gated", label="gated", voice_shift=".",
                    trigger=TriggerSpec(
                        min_quest_stages={"recover_locket": "clue_found"},
                    ),
                ),
            ],
        ))
        store = MemoryStore()
        tracker = QuestTracker()

        # Not started — gated stage must not fire.
        active = evaluate_arc(npc, store, quest_tracker=tracker, quest_config=cfg)
        assert [a.stage.id for a in active] == ["base"]

        # Past the required stage — gated stage fires.
        tracker.set_stage("recover_locket", "confronted", cfg)
        active = evaluate_arc(npc, store, quest_tracker=tracker, quest_config=cfg)
        assert [a.stage.id for a in active] == ["base", "gated"]

    def test_arc_with_quest_gate_but_no_tracker_fails_closed(self):
        cfg = _config()
        npc = NpcSheet(id="mira", name="M", role="r", voice="v", arc=NpcArc(
            stages=[
                ArcStage(id="base", label="base", voice_shift="."),
                ArcStage(
                    id="gated", label="gated", voice_shift=".",
                    trigger=TriggerSpec(
                        min_quest_stages={"recover_locket": "accepted"},
                    ),
                ),
            ],
        ))
        store = MemoryStore()
        # No tracker passed → gated stage is blocked.
        active = evaluate_arc(npc, store)
        assert [a.stage.id for a in active] == ["base"]


# ---------------------------------------------------------------------------
# Prompt block
# ---------------------------------------------------------------------------


class TestSummariser:
    def test_empty_tracker_returns_empty(self):
        assert summarize_active_quests("mira", QuestTracker(), _config()) == ""

    def test_active_quest_renders_name_and_label(self):
        cfg = _config()
        t = QuestTracker()
        t.set_stage("recover_locket", "accepted", cfg)
        block = summarize_active_quests("mira", t, cfg)
        assert "Active quests" in block
        assert "Recover the Locket" in block
        assert "accepted" in block
        assert "never recite" in block


class TestRule19:
    def test_rule_19_present(self):
        npc = NpcSheet(id="x", name="X", role="r", voice="v")
        prompt = build_npc_respondent_prompt(npc)
        assert "19. If an 'Active quests' block" in prompt

    def test_block_present_when_kwarg_supplied(self):
        npc = NpcSheet(id="x", name="X", role="r", voice="v")
        prompt = build_npc_respondent_prompt(
            npc,
            active_quests_block=(
                "Active quests (what the player is currently holding):\n"
                "- Recover the Locket: accepted"
            ),
        )
        assert "Recover the Locket: accepted" in prompt
