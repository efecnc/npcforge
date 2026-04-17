"""Tests for stub handling and the intent / bark-trigger append helpers."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from npcforge.generation import (
    _rewrite_characters_yaml_replacing_stubs,
    append_bark_triggers_to_yaml,
    append_intents_to_yaml,
)
from npcforge.schemas import (
    BarkTrigger,
    NpcSheet,
    PlayerIntent,
    load_barks_config,
    load_intents,
    load_npcs,
    load_npcs_with_stubs,
)


# ---------------------------------------------------------------------------
# Stub schema and loader
# ---------------------------------------------------------------------------


def test_load_npcs_skips_stub_entries(tmp_path: Path):
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
                    },
                    {
                        "id": "the_rival",
                        "_generate": True,
                        "role_hint": "rival tavernkeeper",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    npcs = load_npcs(path)
    # The stub must not appear in the strict loader's output.
    assert [n.id for n in npcs] == ["mira"]


def test_load_npcs_with_stubs_returns_both(tmp_path: Path):
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
                    },
                    {
                        "id": "the_rival",
                        "_generate": True,
                        "role_hint": "rival tavernkeeper",
                        "voice_hint": "posher, younger",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    full, stubs = load_npcs_with_stubs(path)
    assert [n.id for n in full] == ["mira"]
    assert [s.id for s in stubs] == ["the_rival"]
    assert stubs[0].role_hint == "rival tavernkeeper"
    assert stubs[0].voice_hint == "posher, younger"
    assert stubs[0].generate is True


def test_rewrite_characters_replaces_stubs_only(tmp_path: Path):
    path = tmp_path / "characters.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "world": "Testing",
                "npcs": [
                    {
                        "id": "mira",
                        "name": "Mira",
                        "role": "tavernkeeper",
                        "voice": "gruff",
                    },
                    {
                        "id": "the_rival",
                        "_generate": True,
                        "role_hint": "rival tavernkeeper",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    resolved = {
        "the_rival": NpcSheet(
            id="the_rival",
            name="Serren",
            role="rival tavernkeeper",
            voice="polished and younger",
        )
    }
    _rewrite_characters_yaml_replacing_stubs(path, resolved)

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["world"] == "Testing"
    ids = [n["id"] for n in data["npcs"]]
    assert ids == ["mira", "the_rival"]
    rival = next(n for n in data["npcs"] if n["id"] == "the_rival")
    assert rival["name"] == "Serren"
    # Stub markers must be gone after resolution.
    assert "_generate" not in rival
    assert "role_hint" not in rival
    # The untouched entry kept its shape.
    mira = next(n for n in data["npcs"] if n["id"] == "mira")
    assert mira["role"] == "tavernkeeper"


# ---------------------------------------------------------------------------
# Intent append helper
# ---------------------------------------------------------------------------


def test_append_intents_to_empty_file(tmp_path: Path):
    path = tmp_path / "player_intents.yaml"
    append_intents_to_yaml(
        path,
        [
            PlayerIntent(
                id="ask_for_help",
                name="Ask for Help",
                description="Request aid.",
                opening_intent="state what the player needs",
            )
        ],
    )
    intents = load_intents(path)
    assert [i.id for i in intents] == ["ask_for_help"]


def test_append_intents_preserves_existing(tmp_path: Path):
    path = tmp_path / "player_intents.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "intents": [
                    {
                        "id": "farewell",
                        "name": "Farewell",
                        "description": "End the conversation.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    append_intents_to_yaml(
        path,
        [
            PlayerIntent(
                id="flirt",
                name="Flirt",
                description="Light flirtation.",
            )
        ],
    )
    intents = load_intents(path)
    assert [i.id for i in intents] == ["farewell", "flirt"]


# ---------------------------------------------------------------------------
# Bark-trigger append helper
# ---------------------------------------------------------------------------


def test_append_bark_triggers_creates_new_npc_entry(tmp_path: Path):
    path = tmp_path / "barks.yaml"
    append_bark_triggers_to_yaml(
        path,
        "mira_vesser",
        [BarkTrigger(id="greet_patron", description="A patron enters.", n=8)],
    )
    cfg = load_barks_config(path)
    assert [e.npc for e in cfg.barks] == ["mira_vesser"]
    assert [t.id for t in cfg.barks[0].triggers] == ["greet_patron"]


def test_append_bark_triggers_extends_existing_npc(tmp_path: Path):
    path = tmp_path / "barks.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "barks": [
                    {
                        "npc": "mira_vesser",
                        "triggers": [
                            {
                                "id": "greet_patron",
                                "description": "A patron enters.",
                                "n": 8,
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    append_bark_triggers_to_yaml(
        path,
        "mira_vesser",
        [
            BarkTrigger(
                id="reacts_to_hum",
                description="The humming rises audibly.",
                n=6,
            )
        ],
    )
    cfg = load_barks_config(path)
    assert len(cfg.barks) == 1
    trigger_ids = [t.id for t in cfg.barks[0].triggers]
    assert trigger_ids == ["greet_patron", "reacts_to_hum"]


def test_append_bark_triggers_adds_second_npc(tmp_path: Path):
    path = tmp_path / "barks.yaml"
    append_bark_triggers_to_yaml(
        path,
        "mira_vesser",
        [BarkTrigger(id="a", description="x", n=5)],
    )
    append_bark_triggers_to_yaml(
        path,
        "gereth_blackstone",
        [BarkTrigger(id="b", description="y", n=5)],
    )
    cfg = load_barks_config(path)
    assert {e.npc for e in cfg.barks} == {"mira_vesser", "gereth_blackstone"}
