"""Tests for v0.15.0 emergent NPC birthing — declaration + mention accrual + canon summarisation."""

from __future__ import annotations

from pathlib import Path

import pytest

from npcforge.unseen import (
    MentionRecord,
    UnseenCharacter,
    UnseenRegistry,
    build_materialize_system_prompt,
    summarize_canon,
)
from npcforge.schemas import Faction, FactionsConfig, NpcSheet


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tiny_cast() -> list[NpcSheet]:
    return [
        NpcSheet(id="mira", name="Mira", role="tavernkeeper", voice="gruff"),
        NpcSheet(id="gereth", name="Gereth", role="miner", voice="fragmented"),
    ]


def _tiny_factions() -> FactionsConfig:
    return FactionsConfig(factions=[
        Faction(id="lantern", name="Lantern Regulars"),
        Faction(id="miners", name="Grindholt Miners"),
    ])


# ---------------------------------------------------------------------------
# Registry behaviour
# ---------------------------------------------------------------------------


class TestUnseenRegistryLifecycle:
    def test_declare_is_idempotent(self):
        r = UnseenRegistry()
        r.declare("borin", display_name_hint="Borin")
        r.record_mention("borin", source_npc_id="gereth",
                         context="took the last drink", turn=1)
        r.declare("borin", display_name_hint="Borin the Foreman")  # idempotent
        # Mention survives — declare doesn't wipe history.
        assert len(r.characters["borin"].mention_records) == 1
        # display_name_hint preserved from original declaration (not overwritten).
        assert r.characters["borin"].display_name_hint == "Borin"

    def test_record_mention_requires_declaration(self):
        r = UnseenRegistry()
        with pytest.raises(KeyError, match="has no character 'ghost'"):
            r.record_mention("ghost", source_npc_id="mira",
                             context="x")

    def test_mention_appends_in_order(self):
        r = UnseenRegistry()
        r.declare("borin")
        r.record_mention("borin", source_npc_id="gereth",
                         context="first", turn=1)
        r.record_mention("borin", source_npc_id="mira",
                         context="second", turn=2)
        records = r.characters["borin"].mention_records
        assert [m.context for m in records] == ["first", "second"]

    def test_still_unseen_flags(self):
        r = UnseenRegistry()
        r.declare("borin")
        assert r.still_unseen("borin")
        r.characters["borin"].materialized_as = "borin_of_grindholt"
        assert not r.still_unseen("borin")
        assert not r.still_unseen("ghost_unknown_id")

    def test_save_load_round_trip(self, tmp_path: Path):
        r = UnseenRegistry()
        r.declare("borin", display_name_hint="Borin",
                  role_hint="dwarven foreman")
        r.record_mention("borin", source_npc_id="gereth",
                         context="took the last drink", turn=3,
                         scene_context="common_room")
        path = tmp_path / "unseen.json"
        r.save(path)
        loaded = UnseenRegistry.load(path)
        assert "borin" in loaded.characters
        assert loaded.characters["borin"].role_hint == "dwarven foreman"
        assert len(loaded.characters["borin"].mention_records) == 1
        assert loaded.characters["borin"].mention_records[0].scene_context == "common_room"

    def test_load_missing_file_returns_empty_registry(self, tmp_path: Path):
        r = UnseenRegistry.load(tmp_path / "nothing.json")
        assert r.characters == {}


# ---------------------------------------------------------------------------
# Summariser
# ---------------------------------------------------------------------------


class TestSummarizeCanon:
    def test_empty_mentions_returns_empty_string(self):
        u = UnseenCharacter(canonical_id="x")
        assert summarize_canon(u) == ""

    def test_renders_header_plus_one_line_per_mention(self):
        u = UnseenCharacter(
            canonical_id="borin",
            mention_records=[
                MentionRecord(source_npc_id="gereth",
                              context="took the last drink", turn=3),
                MentionRecord(source_npc_id="mira",
                              context="owes the Lantern two coppers",
                              turn=8, scene_context="walk_up_mira"),
            ],
        )
        block = summarize_canon(u)
        assert "Canon accumulated" in block
        assert "remain TRUE" in block
        assert "[turn 3, from gereth] took the last drink" in block
        assert "[turn 8, from mira, walk_up_mira] owes" in block


# ---------------------------------------------------------------------------
# Materialise prompt assembly
# ---------------------------------------------------------------------------


class TestMaterializePromptAssembly:
    def test_embeds_canon_cast_and_faction_rosters(self):
        u = UnseenCharacter(
            canonical_id="borin", display_name_hint="Borin",
            role_hint="dwarven foreman",
            mention_records=[
                MentionRecord(source_npc_id="gereth",
                              context="took the last drink", turn=3),
            ],
        )
        prompt = build_materialize_system_prompt(
            u,
            world_bible="Emberfall is a town on the edge of the Greywild.",
            existing_cast=_tiny_cast(),
            factions=_tiny_factions(),
        )
        assert "World bible" in prompt
        assert "Emberfall" in prompt
        assert "Canon accumulated" in prompt
        assert "took the last drink" in prompt
        assert "mira: Mira — tavernkeeper" in prompt
        assert "gereth: Gereth — miner" in prompt
        assert "lantern: Lantern Regulars" in prompt
        assert "miners: Grindholt Miners" in prompt
        # Rule 4: no inventing relationship ids.
        assert "Never invent a relationship target id" in prompt

    def test_empty_canon_surfaces_placeholder(self):
        u = UnseenCharacter(canonical_id="new")
        prompt = build_materialize_system_prompt(
            u, world_bible="x", existing_cast=[], factions=None,
        )
        assert "no canon accumulated yet" in prompt

    def test_factions_optional(self):
        u = UnseenCharacter(canonical_id="x")
        prompt = build_materialize_system_prompt(
            u, world_bible="x", existing_cast=[], factions=None,
        )
        assert "Factions currently defined" not in prompt
