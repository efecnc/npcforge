"""Tests for multi-NPC scene generation (v0.9.0)."""

from __future__ import annotations

from pathlib import Path

import pytest

from npcforge.memory import MemoryStore
from npcforge.scenes import (
    Scene,
    SceneDialogue,
    SceneLine,
    ScenePlayerChoice,
    build_scene_system_prompt,
    render_scene_yarn,
    validate_scene_output,
)
from npcforge.schemas import Faction, FactionsConfig, NpcSheet


def _cast() -> list[NpcSheet]:
    return [
        NpcSheet(
            id="mira",
            name="Mira Vesser",
            role="tavernkeeper",
            voice="gruff, measured",
            faction_id="lantern",
        ),
        NpcSheet(
            id="gereth",
            name="Gereth Blackstone",
            role="miner",
            voice="fragmented, lucid",
            faction_id="miners",
        ),
        NpcSheet(
            id="adelie",
            name="Sister Adelie",
            role="cleric",
            voice="soft, precise",
            faction_id="silent_order",
        ),
    ]


def _factions() -> FactionsConfig:
    return FactionsConfig(
        factions=[
            Faction(id="lantern", name="Lantern Regulars",
                    allies=["miners"], rivals=["councils"]),
            Faction(id="miners", name="Grindholt Miners",
                    allies=["lantern"], rivals=["silent_order"]),
            Faction(id="silent_order", name="Silent Order",
                    rivals=["miners"]),
            Faction(id="councils", name="Free Councils",
                    rivals=["lantern"]),
        ]
    )


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


class TestSceneSchema:
    def test_requires_two_participants(self):
        with pytest.raises(Exception):  # Pydantic validation
            Scene(id="x", location="tavern",
                  participants=["mira"], setup="something")

    def test_main_lines_bounded(self):
        with pytest.raises(Exception):
            SceneDialogue(
                main=[SceneLine(speaker="mira", text="t")] * 3,  # min 4
                choices=[],
            )
        with pytest.raises(Exception):
            SceneDialogue(
                main=[SceneLine(speaker="mira", text="t")] * 20,  # max 14
                choices=[],
            )

    def test_max_lines_honoured_in_scene(self):
        s = Scene(id="s", location="l", participants=["a", "b"],
                  setup="setup", max_lines=10)
        assert s.max_lines == 10
        with pytest.raises(Exception):
            Scene(id="s", location="l", participants=["a", "b"],
                  setup="x", max_lines=3)  # below minimum


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------


class TestScenePrompt:
    def test_system_prompt_includes_all_participant_sheets(self):
        scene = Scene(
            id="inspector",
            location="common room",
            participants=["mira", "gereth"],
            setup="A Guild inspector has just walked in.",
        )
        prompt = build_scene_system_prompt(scene, cast=_cast(),
                                           factions=_factions())
        assert "PARTICIPANTS: mira, gereth" in prompt
        assert "Mira Vesser" in prompt
        assert "Gereth Blackstone" in prompt
        assert "Primary: Lantern Regulars" in prompt
        assert "Primary: Grindholt Miners" in prompt
        # Adelie is not participating — must not leak.
        assert "Sister Adelie" not in prompt

    def test_system_prompt_omits_memory_when_none_supplied(self):
        scene = Scene(id="s", location="l", participants=["mira", "gereth"],
                      setup="s")
        prompt = build_scene_system_prompt(scene, cast=_cast(),
                                           factions=_factions())
        # The rules section mentions "Memory of past encounters" to tell
        # the LLM what to do *if* a memory block appears. Check for the
        # actual per-turn event syntax instead — that's what distinguishes
        # an injected block from the instruction text.
        assert "[turn " not in prompt

    def test_system_prompt_injects_memory_per_participant(self):
        store = MemoryStore()
        store.current_turn = 3
        store.record(npc_id="mira", event_type="lied",
                     summary="The player denied knowing Kess.",
                     salience="pivotal")
        scene = Scene(id="s", location="l", participants=["mira", "gereth"],
                      setup="s")
        prompt = build_scene_system_prompt(scene, cast=_cast(),
                                           factions=_factions(),
                                           memory_store=store)
        assert "Memory of past encounters" in prompt
        assert "denied knowing Kess" in prompt

    def test_prompt_rejects_unknown_participant(self):
        scene = Scene(id="s", location="l",
                      participants=["mira", "nonexistent"], setup="s")
        with pytest.raises(ValueError, match="at least two NPCs"):
            build_scene_system_prompt(scene, cast=_cast())

    def test_prompt_rules_reference_faction_and_quirks(self):
        scene = Scene(id="s", location="l", participants=["mira", "gereth"],
                      setup="s")
        prompt = build_scene_system_prompt(scene, cast=_cast(),
                                           factions=_factions())
        assert "voice of the speaker" in prompt
        assert "Faction affiliation shapes register" in prompt
        assert "Dialogue only" in prompt


# ---------------------------------------------------------------------------
# Output validation
# ---------------------------------------------------------------------------


class TestSceneOutputValidation:
    def test_allows_player_when_present(self):
        scene = Scene(id="s", location="l", participants=["mira", "gereth"],
                      setup="s", player_present=True)
        dlg = SceneDialogue(
            main=[
                SceneLine(speaker="mira", text="a"),
                SceneLine(speaker="gereth", text="b"),
                SceneLine(speaker="Player", text="c"),
                SceneLine(speaker="mira", text="d"),
            ],
            choices=[],
        )
        assert validate_scene_output(scene, dlg) == []

    def test_flags_unknown_speaker_in_main(self):
        scene = Scene(id="s", location="l", participants=["mira", "gereth"],
                      setup="s")
        dlg = SceneDialogue(
            main=[
                SceneLine(speaker="mira", text="a"),
                SceneLine(speaker="adelie", text="b"),  # not a participant
                SceneLine(speaker="mira", text="c"),
                SceneLine(speaker="gereth", text="d"),
            ],
            choices=[],
        )
        warnings = validate_scene_output(scene, dlg)
        assert any("adelie" in w for w in warnings)

    def test_flags_choices_when_player_absent(self):
        scene = Scene(id="s", location="l", participants=["mira", "gereth"],
                      setup="s", player_present=False)
        dlg = SceneDialogue(
            main=[
                SceneLine(speaker="mira", text="a"),
                SceneLine(speaker="gereth", text="b"),
                SceneLine(speaker="mira", text="c"),
                SceneLine(speaker="gereth", text="d"),
            ],
            choices=[ScenePlayerChoice(label="Clear throat")],
        )
        warnings = validate_scene_output(scene, dlg)
        assert any("player_present=False" in w for w in warnings)


# ---------------------------------------------------------------------------
# Yarn rendering
# ---------------------------------------------------------------------------


class TestRenderSceneYarn:
    def test_renders_main_exchange_as_speaker_lines(self):
        scene = Scene(id="inspector", location="common room",
                      participants=["mira", "gereth"], setup="s")
        dlg = SceneDialogue(
            main=[
                SceneLine(speaker="gereth", text="The inspector. In my seat."),
                SceneLine(speaker="mira", text="He paid for it. Sit down."),
                SceneLine(speaker="gereth", text="He paid with which coin?"),
                SceneLine(speaker="mira", text="Good coin. Drink."),
            ],
            choices=[],
        )
        yarn = render_scene_yarn(scene, dlg, _cast())
        assert "title: scene_inspector" in yarn
        assert "tags: scene" in yarn
        assert "# location: common room" in yarn
        assert "Gereth: The inspector. In my seat." in yarn
        assert "Mira: He paid for it. Sit down." in yarn
        assert yarn.strip().endswith("===")

    def test_emits_player_choices_when_present(self):
        scene = Scene(id="s", location="l", participants=["mira", "gereth"],
                      setup="s", player_present=True)
        dlg = SceneDialogue(
            main=[
                SceneLine(speaker="mira", text="a"),
                SceneLine(speaker="gereth", text="b"),
                SceneLine(speaker="mira", text="c"),
                SceneLine(speaker="gereth", text="d"),
            ],
            choices=[
                ScenePlayerChoice(
                    label="Clear your throat",
                    lines=[
                        SceneLine(speaker="mira", text="You'll want to sit."),
                    ],
                ),
            ],
        )
        yarn = render_scene_yarn(scene, dlg, _cast())
        assert "-> [Clear your throat]" in yarn
        assert "    Mira: You'll want to sit." in yarn

    def test_omits_choices_when_player_absent(self):
        scene = Scene(id="s", location="l", participants=["mira", "gereth"],
                      setup="s", player_present=False)
        dlg = SceneDialogue(
            main=[
                SceneLine(speaker="mira", text="a"),
                SceneLine(speaker="gereth", text="b"),
                SceneLine(speaker="mira", text="c"),
                SceneLine(speaker="gereth", text="d"),
            ],
            choices=[ScenePlayerChoice(label="ignored")],
        )
        yarn = render_scene_yarn(scene, dlg, _cast())
        assert "->" not in yarn
        assert "ignored" not in yarn

    def test_emits_jump_to_end_node_when_provided(self):
        scene = Scene(id="s", location="l", participants=["mira", "gereth"],
                      setup="s")
        dlg = SceneDialogue(
            main=[SceneLine(speaker="mira", text=".")] * 4,
            choices=[],
        )
        yarn = render_scene_yarn(scene, dlg, _cast(), end_node="Start")
        assert "<<jump Start>>" in yarn

    def test_yarn_title_sanitizes_invalid_ids(self):
        scene = Scene(id="s with spaces & punctuation!",
                      location="l", participants=["mira", "gereth"],
                      setup="s")
        dlg = SceneDialogue(
            main=[SceneLine(speaker="mira", text=".")] * 4,
            choices=[],
        )
        yarn = render_scene_yarn(scene, dlg, _cast())
        # No spaces or punctuation in the title line.
        title_line = [l for l in yarn.splitlines() if l.startswith("title:")][0]
        assert " " not in title_line.replace("title: ", "")
