"""Tests for the v0.9.0 social-graph layer: factions + memory."""

from __future__ import annotations

from pathlib import Path

import pytest

from npcforge.memory import (
    DECAY_HORIZON_NOTABLE,
    DECAY_HORIZON_TRIVIAL,
    MemoryStore,
    summarize_faction_memory,
    summarize_for_npc,
)
from npcforge.prompts import build_npc_respondent_prompt, render_character_sheet
from npcforge.schemas import (
    Faction,
    FactionsConfig,
    MemoryEvent,
    NpcSheet,
    load_factions,
    load_npcs,
    validate_npc_factions,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mira() -> NpcSheet:
    return NpcSheet(
        id="mira",
        name="Mira",
        role="tavernkeeper",
        voice="gruff, measured",
        faction_id="lantern",
        secondary_faction_id="miners",
    )


def _lantern_factions() -> FactionsConfig:
    return FactionsConfig(
        factions=[
            Faction(
                id="lantern",
                name="Lantern Regulars",
                description="Locals of the Rusted Lantern.",
                values=["silence about the deep"],
                allies=["miners"],
                rivals=["councils"],
            ),
            Faction(
                id="miners",
                name="Grindholt Miners",
                allies=["lantern"],
                rivals=["silent_order"],
            ),
            Faction(id="silent_order", name="Silent Order", rivals=["miners"]),
            Faction(id="councils", name="Free Councils", rivals=["lantern"]),
        ]
    )


# ---------------------------------------------------------------------------
# Faction loading
# ---------------------------------------------------------------------------


class TestFactionLoading:
    def test_load_factions_yaml_resolves_allies_and_rivals(self, tmp_path: Path):
        p = tmp_path / "factions.yaml"
        p.write_text(
            "factions:\n"
            "  - id: a\n    name: A\n    allies: [b]\n"
            "  - id: b\n    name: B\n    rivals: [a]\n",
            encoding="utf-8",
        )
        cfg = load_factions(p)
        assert [f.id for f in cfg.factions] == ["a", "b"]

    def test_unknown_ally_fails_loudly(self, tmp_path: Path):
        p = tmp_path / "factions.yaml"
        p.write_text(
            "factions:\n"
            "  - id: a\n    name: A\n    allies: [does_not_exist]\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="unknown allies"):
            load_factions(p)

    def test_missing_file_returns_empty_config(self, tmp_path: Path):
        cfg = load_factions(tmp_path / "does_not_exist.yaml")
        assert cfg.factions == []

    def test_rusted_lantern_factions_load(self):
        root = Path(__file__).resolve().parent.parent / "examples/rusted_lantern"
        cfg = load_factions(root / "factions.yaml")
        ids = {f.id for f in cfg.factions}
        assert {"lantern_regulars", "grindholt_miners", "silent_order",
                "free_councils", "unaffiliated"} <= ids


class TestNpcFactionValidation:
    def test_unknown_primary_faction_is_rejected(self):
        npcs = [NpcSheet(id="x", name="X", role="y", voice="z",
                         faction_id="nope")]
        with pytest.raises(ValueError, match="faction_id='nope'"):
            validate_npc_factions(npcs, _lantern_factions())

    def test_unknown_secondary_faction_is_rejected(self):
        npcs = [NpcSheet(id="x", name="X", role="y", voice="z",
                         faction_id="lantern",
                         secondary_faction_id="nope")]
        with pytest.raises(ValueError, match="secondary_faction_id='nope'"):
            validate_npc_factions(npcs, _lantern_factions())

    def test_npcs_with_factions_require_a_factions_file(self):
        npcs = [NpcSheet(id="x", name="X", role="y", voice="z",
                         faction_id="anything")]
        with pytest.raises(ValueError, match="NPCs claim faction membership"):
            validate_npc_factions(npcs, FactionsConfig())

    def test_rusted_lantern_cast_validates(self):
        root = Path(__file__).resolve().parent.parent / "examples/rusted_lantern"
        factions = load_factions(root / "factions.yaml")
        npcs = load_npcs(root / "characters.yaml")
        validate_npc_factions(npcs, factions)
        # Every NPC has a primary faction.
        assert all(n.faction_id for n in npcs)


# ---------------------------------------------------------------------------
# Memory store
# ---------------------------------------------------------------------------


class TestMemoryStore:
    def test_record_and_for_npc_returns_events_recency_first(self):
        store = MemoryStore()
        store.record(npc_id="mira", event_type="greeting",
                     summary="first meet", turn=1)
        store.record(npc_id="mira", event_type="threat",
                     summary="player threatened her", turn=3)
        store.current_turn = 3
        out = store.for_npc("mira")
        assert [e.turn for e in out] == [3, 1]

    def test_for_npc_folds_in_faction_tagged_events(self):
        store = MemoryStore()
        store.current_turn = 5
        store.record(npc_id="gereth", event_type="own",
                     summary="met the player", turn=5, salience="pivotal")
        store.record(npc_id="mira", event_type="faction_helped",
                     summary="player settled a debt", turn=4,
                     salience="pivotal", faction_id="miners")
        # Gereth is in miners; he should see the faction-shared event too.
        out = store.for_npc("gereth", faction_id="miners")
        summaries = [e.summary for e in out]
        assert "met the player" in summaries
        assert "player settled a debt" in summaries

    def test_trivial_events_decay_after_horizon(self):
        store = MemoryStore()
        store.record(npc_id="mira", event_type="small",
                     summary="pleasantry", turn=1, salience="trivial")
        store.current_turn = 1 + DECAY_HORIZON_TRIVIAL + 1  # past horizon
        assert store.for_npc("mira") == []
        # Include-decayed gets it back.
        assert store.for_npc("mira", include_decayed=True) != []

    def test_notable_events_survive_longer_than_trivial(self):
        store = MemoryStore()
        store.record(npc_id="mira", event_type="x", summary="notable",
                     salience="notable", turn=0)
        # Past trivial horizon but still inside the notable one.
        store.current_turn = DECAY_HORIZON_TRIVIAL + 1
        assert store.for_npc("mira")
        # On the notable horizon boundary — inclusive, so still visible.
        store.current_turn = DECAY_HORIZON_NOTABLE
        assert store.for_npc("mira")
        # One step beyond — decayed.
        store.current_turn = DECAY_HORIZON_NOTABLE + 1
        assert store.for_npc("mira") == []

    def test_pivotal_events_are_permanent(self):
        store = MemoryStore()
        store.record(npc_id="mira", event_type="x", summary="pivotal",
                     salience="pivotal", turn=0)
        store.current_turn = 10_000
        assert len(store.for_npc("mira")) == 1

    def test_for_faction_ignores_decay(self):
        store = MemoryStore()
        store.record(npc_id="anon", event_type="x", summary="y",
                     salience="trivial", faction_id="miners", turn=0)
        store.current_turn = 10_000
        assert store.for_faction("miners")

    def test_save_and_load_round_trip(self, tmp_path: Path):
        store = MemoryStore()
        store.advance_turn(4)
        store.record(npc_id="mira", event_type="gift",
                     summary="offered coin", salience="notable")
        path = tmp_path / "mem.json"
        store.save(path)
        restored = MemoryStore.load(path)
        assert restored.current_turn == 4
        assert len(restored.events) == 1
        assert restored.events[0].summary == "offered coin"

    def test_load_missing_file_returns_empty(self, tmp_path: Path):
        store = MemoryStore.load(tmp_path / "nothing.json")
        assert store.events == []
        assert store.current_turn == 0


class TestMemorySummarisation:
    def test_summarize_for_npc_empty_returns_empty_string(self):
        assert summarize_for_npc(_mira(), MemoryStore()) == ""

    def test_summarize_for_npc_includes_faction_shared(self):
        store = MemoryStore()
        store.current_turn = 2
        store.record(npc_id="mira", event_type="direct",
                     summary="The player threatened you.",
                     salience="pivotal")
        store.record(npc_id="gereth", event_type="faction",
                     summary="A Guildsman saw the player pocket a token.",
                     salience="notable", faction_id="miners")
        out = summarize_for_npc(_mira(), store)
        assert "threatened you" in out
        assert "Guildsman" in out
        # Turn tags are visible (bookkeeping for the LLM to ignore).
        assert "turn" in out

    def test_summarize_for_npc_caps_at_max_lines(self):
        store = MemoryStore()
        store.current_turn = 50
        for i in range(20):
            store.record(npc_id="mira", event_type="x",
                         summary=f"event {i}", salience="pivotal", turn=i)
        out = summarize_for_npc(_mira(), store, max_lines=3)
        # 3 events + 1 header line = 4 lines.
        assert out.count("\n") == 3
        # Most-recent first: event 19 appears, event 0 does not.
        assert "event 19" in out
        assert "event 0 —" not in out

    def test_summarize_for_npc_deduplicates_faction_double_membership(self):
        """Mira is in lantern + miners; a miners-tagged event shouldn't
        appear twice just because both slots match."""
        store = MemoryStore()
        store.current_turn = 1
        store.record(npc_id="mira", event_type="f",
                     summary="helped a miner", faction_id="miners",
                     salience="pivotal", turn=1)
        out = summarize_for_npc(_mira(), store)
        assert out.count("helped a miner") == 1

    def test_summarize_faction_memory_groups_by_faction(self):
        store = MemoryStore()
        store.record(npc_id="a", event_type="x",
                     summary="insulted a member", faction_id="miners",
                     salience="notable", turn=1)
        out = summarize_faction_memory("miners", store)
        assert "miners" in out
        assert "insulted a member" in out


# ---------------------------------------------------------------------------
# Prompt wiring
# ---------------------------------------------------------------------------


class TestRespondentPromptWiring:
    def test_prompt_includes_faction_block_when_factions_passed(self):
        prompt = build_npc_respondent_prompt(_mira(), factions=_lantern_factions())
        assert "Faction affiliation" in prompt
        assert "Primary: Lantern Regulars (lantern)" in prompt
        assert "Secondary: Grindholt Miners (miners)" in prompt
        assert "Allied factions: miners" in prompt
        assert "Rival factions: councils" in prompt

    def test_prompt_omits_faction_block_when_no_factions(self):
        npc = NpcSheet(id="x", name="X", role="r", voice="v")
        prompt = build_npc_respondent_prompt(npc)
        assert "Faction affiliation" not in prompt

    def test_prompt_includes_memory_block_when_supplied(self):
        prompt = build_npc_respondent_prompt(
            _mira(),
            factions=_lantern_factions(),
            memory_summary="Memory of past encounters with the player:\n- something",
        )
        assert "Memory of past encounters" in prompt

    def test_prompt_includes_new_rules_10_and_11(self):
        prompt = build_npc_respondent_prompt(_mira(), factions=_lantern_factions())
        assert "10. If the sheet declares faction affiliation" in prompt
        assert "11. If a 'Memory of past encounters' block" in prompt

    def test_character_sheet_embeds_faction_details(self):
        sheet = render_character_sheet(_mira(), factions=_lantern_factions())
        assert "Primary: Lantern Regulars" in sheet
        assert "silence about the deep" in sheet  # faction value
