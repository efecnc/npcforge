"""Tests for v0.8.1 — StateEvolution schema + peer-role anchor in relationships."""

from __future__ import annotations

from pathlib import Path

from npcforge.prompts import render_character_sheet
from npcforge.schemas import (
    KnowledgeItem,
    NpcSheet,
    Relationship,
    StateEvolution,
    load_npcs,
)


_RUSTED_LANTERN = Path(__file__).parent.parent / "examples" / "rusted_lantern"


# ---------------------------------------------------------------------------
# StateEvolution schema
# ---------------------------------------------------------------------------


def test_state_evolution_minimal_fields():
    s = StateEvolution(
        trigger="disposition_mira < 20", voice_shift="Drops the veneer."
    )
    assert s.trigger == "disposition_mira < 20"
    assert s.voice_shift == "Drops the veneer."
    assert s.description == ""


def test_npc_sheet_default_empty_state_evolution():
    npc = NpcSheet(id="x", name="X", role="r", voice="v")
    assert npc.state_evolution == []


def test_demo_mira_and_gereth_have_state_evolution():
    npcs = load_npcs(_RUSTED_LANTERN / "characters.yaml")
    mira = next(n for n in npcs if n.id == "mira_vesser")
    gereth = next(n for n in npcs if n.id == "gereth_blackstone")
    assert len(mira.state_evolution) >= 1, "Mira must ship with at least one evolution"
    assert len(gereth.state_evolution) >= 1, "Gereth must ship with at least one evolution"
    triggers = {s.trigger for s in mira.state_evolution}
    assert any("disposition_mira" in t for t in triggers), \
        "Mira's evolution should reference her own disposition"


# ---------------------------------------------------------------------------
# Relationship peer-role anchor
# ---------------------------------------------------------------------------


def test_relationship_renders_without_cast_annotation_when_cast_missing():
    npc = NpcSheet(
        id="mira",
        name="Mira",
        role="Tavernkeeper",
        voice="gruff",
        relationships=[Relationship(npc_id="gereth", opinion="protective")],
    )
    block = render_character_sheet(npc)
    assert "Relationships with other characters:" in block
    assert "- gereth: protective" in block
    # Without cast, the line should not include a parenthesised role.
    assert "- gereth (" not in block


def test_relationship_injects_peer_role_when_cast_supplied():
    gereth = NpcSheet(
        id="gereth",
        name="Gereth Blackstone",
        role="Dwarven miner, sole survivor of the cave-in",
        voice="hums",
    )
    mira = NpcSheet(
        id="mira",
        name="Mira",
        role="Tavernkeeper",
        voice="gruff",
        relationships=[
            Relationship(
                npc_id="gereth",
                opinion="protective",
                reason="She sold the lease.",
            )
        ],
    )
    block = render_character_sheet(mira, cast=[mira, gereth])
    assert "- gereth (Gereth Blackstone, Dwarven miner, sole survivor of the cave-in): protective" in block
    assert "Why: She sold the lease." in block


def test_relationship_unknown_peer_falls_back_gracefully():
    npc = NpcSheet(
        id="x",
        name="X",
        role="r",
        voice="v",
        relationships=[Relationship(npc_id="ghost", opinion="wary")],
    )
    # Cast contains someone, but not the relationship's target — should not break.
    other = NpcSheet(id="other", name="Other", role="r", voice="v")
    block = render_character_sheet(npc, cast=[npc, other])
    # Falls back to the un-annotated form because `ghost` is not in the cast.
    assert "- ghost: wary" in block


# ---------------------------------------------------------------------------
# state_evolution block rendering
# ---------------------------------------------------------------------------


def test_render_state_evolution_includes_trigger_and_voice_shift():
    npc = NpcSheet(
        id="x",
        name="X",
        role="r",
        voice="v",
        state_evolution=[
            StateEvolution(
                trigger="quest_stage >= 3",
                voice_shift="Speaks in full sentences now.",
                description="Trauma eases after the investigation.",
            )
        ],
    )
    block = render_character_sheet(npc)
    assert "State evolution (voice shifts to apply when a trigger is active):" in block
    assert "Trigger: quest_stage >= 3" in block
    assert "Voice shift: Speaks in full sentences now." in block
    assert "Note: Trauma eases after the investigation." in block


def test_render_state_evolution_omitted_when_empty():
    npc = NpcSheet(id="x", name="X", role="r", voice="v")
    block = render_character_sheet(npc)
    assert "State evolution" not in block


def test_render_state_evolution_skips_writer_note_when_empty():
    npc = NpcSheet(
        id="x",
        name="X",
        role="r",
        voice="v",
        state_evolution=[
            StateEvolution(
                trigger="x >= 1",
                voice_shift="Something shifts.",
                # description intentionally omitted
            )
        ],
    )
    block = render_character_sheet(npc)
    assert "Trigger: x >= 1" in block
    assert "Note:" not in block
