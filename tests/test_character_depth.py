"""Tests for v0.8.0 character depth — Relationship + KnowledgeItem."""

from __future__ import annotations

from pathlib import Path

import yaml

from npcforge.prompts import build_npc_respondent_prompt, render_character_sheet
from npcforge.schemas import (
    KnowledgeItem,
    NpcSheet,
    Relationship,
    load_npcs,
)


_RUSTED_LANTERN = Path(__file__).parent.parent / "examples" / "rusted_lantern"


# ---------------------------------------------------------------------------
# Schema shape
# ---------------------------------------------------------------------------


def test_relationship_minimal_fields():
    r = Relationship(npc_id="mira_vesser", opinion="protective")
    assert r.npc_id == "mira_vesser"
    assert r.opinion == "protective"
    assert r.reason == ""


def test_knowledge_item_defaults_empty_gates_and_samples():
    k = KnowledgeItem(id="secret", fact="A thing")
    assert k.gate == ""
    assert k.reveal_lines == []
    assert k.deflect_lines == []


def test_npc_sheet_defaults_no_relationships_or_knowledge():
    npc = NpcSheet(id="x", name="X", role="r", voice="v")
    assert npc.relationships == []
    assert npc.knowledge == []


# ---------------------------------------------------------------------------
# YAML round-trip on the committed demo
# ---------------------------------------------------------------------------


def test_mira_has_relationships_and_knowledge_in_demo():
    npcs = load_npcs(_RUSTED_LANTERN / "characters.yaml")
    mira = next(n for n in npcs if n.id == "mira_vesser")
    assert len(mira.relationships) >= 3
    ids = {r.npc_id for r in mira.relationships}
    assert {"gereth_blackstone", "sister_adelie", "kess_the_knife", "ulrik_the_old_man"}.issubset(ids)

    knowledge_ids = {k.id for k in mira.knowledge}
    assert "sold_mine_lease" in knowledge_ids
    assert "broken_seal" in knowledge_ids
    lease = next(k for k in mira.knowledge if k.id == "sold_mine_lease")
    assert lease.gate, "lease knowledge must declare a non-empty gate"
    assert lease.reveal_lines, "lease knowledge must have at least one reveal line"
    assert lease.deflect_lines, "lease knowledge must have deflect lines"


def test_gereth_has_cross_cast_relationship_with_mira():
    npcs = load_npcs(_RUSTED_LANTERN / "characters.yaml")
    gereth = next(n for n in npcs if n.id == "gereth_blackstone")
    targets = {r.npc_id for r in gereth.relationships}
    assert "mira_vesser" in targets


def test_unknown_npc_fields_roundtrip_as_yaml(tmp_path: Path):
    path = tmp_path / "characters.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "npcs": [
                    {
                        "id": "mira",
                        "name": "Mira",
                        "role": "tavernkeeper",
                        "voice": "gruff",
                        "relationships": [
                            {"npc_id": "kess", "opinion": "wary", "reason": "thief"},
                        ],
                        "knowledge": [
                            {
                                "id": "secret",
                                "fact": "She knows the safe combination.",
                                "gate": "after_trust_won",
                                "reveal_lines": ["Only if you ask once."],
                                "deflect_lines": ["Ask the walls."],
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    [npc] = load_npcs(path)
    assert npc.relationships[0].reason == "thief"
    assert npc.knowledge[0].fact == "She knows the safe combination."


# ---------------------------------------------------------------------------
# Prompt rendering
# ---------------------------------------------------------------------------


def test_render_character_sheet_includes_relationships_block():
    npc = NpcSheet(
        id="x",
        name="X",
        role="r",
        voice="v",
        relationships=[
            Relationship(
                npc_id="y", opinion="old friend", reason="shared the long winter"
            ),
        ],
    )
    sheet = render_character_sheet(npc)
    assert "Relationships with other characters:" in sheet
    assert "y: old friend" in sheet
    assert "shared the long winter" in sheet


def test_render_character_sheet_includes_knowledge_block_with_gates_and_samples():
    npc = NpcSheet(
        id="x",
        name="X",
        role="r",
        voice="v",
        knowledge=[
            KnowledgeItem(
                id="safe_code",
                fact="She knows the safe combination.",
                gate="after the player has shown the token",
                reveal_lines=["It's 4-7-2-2, friend."],
                deflect_lines=["Talk to the walls."],
            )
        ],
    )
    sheet = render_character_sheet(npc)
    assert "Knowledge (structured reveals):" in sheet
    assert "safe_code" in sheet
    assert "She knows the safe combination." in sheet
    assert "Gate: after the player has shown the token" in sheet
    assert "Sample reveal lines" in sheet
    assert "Sample deflection lines" in sheet


def test_render_character_sheet_omits_sections_when_empty():
    npc = NpcSheet(id="x", name="X", role="r", voice="v")
    sheet = render_character_sheet(npc)
    assert "Relationships with other characters" not in sheet
    assert "Knowledge (structured reveals)" not in sheet


def test_respondent_prompt_mentions_relationships_and_gates():
    npc = NpcSheet(id="x", name="X", role="r", voice="v")
    prompt = build_npc_respondent_prompt(npc)
    assert "relationships" in prompt.lower()
    assert "gate" in prompt.lower() or "gated" in prompt.lower()
