"""Tests for v0.6.0 state layer — variables.yaml, Yarn declares, greeting nodes."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from npcforge.schemas import NpcSheet, load_npcs
from npcforge.state import (
    ProjectVariable,
    VariableType,
    format_variables_for_prompt,
    load_variables,
    yarn_declare_block,
    yarn_literal,
)
from npcforge.yarn import greeting_node_title, render_greetings_node, render_world_start_node


_RUSTED_LANTERN = Path(__file__).parent.parent / "examples" / "rusted_lantern"


# ---------------------------------------------------------------------------
# ProjectVariable schema
# ---------------------------------------------------------------------------


def test_enum_variable_defaults_to_first_value():
    v = ProjectVariable(id="time_of_day", type="enum", values=["dawn", "morning", "night"])
    assert v.default == "dawn"


def test_enum_variable_rejects_default_outside_values():
    with pytest.raises(ValueError):
        ProjectVariable(
            id="time_of_day",
            type="enum",
            values=["morning", "night"],
            default="midnight",
        )


def test_enum_variable_requires_non_empty_values():
    with pytest.raises(ValueError):
        ProjectVariable(id="x", type="enum", values=[])


def test_int_variable_gets_zero_default():
    v = ProjectVariable(id="bounty", type="int")
    assert v.default == 0


def test_bool_variable_gets_false_default():
    v = ProjectVariable(id="flag", type="bool")
    assert v.default is False


def test_load_variables_parses_demo_file():
    cfg = load_variables(_RUSTED_LANTERN / "variables.yaml")
    ids = {v.id for v in cfg.variables}
    assert "time_of_day" in ids
    tod = next(v for v in cfg.variables if v.id == "time_of_day")
    assert tod.type == VariableType.ENUM
    assert tod.values == ["dawn", "morning", "afternoon", "dusk", "night"]
    assert tod.default == "morning"


def test_load_variables_returns_empty_when_missing(tmp_path: Path):
    cfg = load_variables(tmp_path / "nonexistent.yaml")
    assert cfg.variables == []


# ---------------------------------------------------------------------------
# Yarn literal + declare rendering
# ---------------------------------------------------------------------------


def test_yarn_literal_string_is_quoted():
    assert yarn_literal("morning", VariableType.ENUM) == '"morning"'
    assert yarn_literal("a 'b", VariableType.STRING) == '"a \'b"'


def test_yarn_literal_bool_is_lowercase():
    assert yarn_literal(True, VariableType.BOOL) == "true"
    assert yarn_literal(False, VariableType.BOOL) == "false"


def test_yarn_literal_int_and_float_pass_through():
    assert yarn_literal(42, VariableType.INT) == "42"
    assert yarn_literal(3.14, VariableType.FLOAT) == "3.14"


def test_yarn_declare_block_one_line_per_variable():
    vars_ = [
        ProjectVariable(id="time_of_day", type="enum", values=["morning", "night"]),
        ProjectVariable(id="bounty", type="int", default=50),
        ProjectVariable(id="suspicious", type="bool", default=True),
    ]
    lines = yarn_declare_block(vars_)
    assert lines == [
        '<<declare $time_of_day = "morning">>',
        "<<declare $bounty = 50>>",
        "<<declare $suspicious = true>>",
    ]


def test_yarn_declare_block_empty_for_no_variables():
    assert yarn_declare_block([]) == []


# ---------------------------------------------------------------------------
# Start node integration
# ---------------------------------------------------------------------------


def test_world_start_node_includes_declares_above_dialogue():
    npcs = [
        NpcSheet(id="mira", name="Mira", role="tavernkeeper", voice="gruff"),
        NpcSheet(id="kess", name="Kess", role="thief", voice="warm"),
    ]
    vars_ = [
        ProjectVariable(id="time_of_day", type="enum", values=["morning", "night"]),
        ProjectVariable(id="bounty", type="int", default=0),
    ]
    text = render_world_start_node(npcs, declare_lines=yarn_declare_block(vars_))

    assert "title: Start" in text
    # Both declares must be present.
    assert '<<declare $time_of_day = "morning">>' in text
    assert "<<declare $bounty = 0>>" in text
    # Declares must appear before the first option line (Yarn requires it).
    declare_pos = text.find("<<declare $time_of_day")
    option_pos = text.find("-> Mira")
    assert declare_pos < option_pos


def test_world_start_node_backward_compatible_without_declares():
    npcs = [NpcSheet(id="mira", name="Mira", role="tavernkeeper", voice="gruff")]
    text = render_world_start_node(npcs)  # no declare_lines arg
    assert "<<declare" not in text
    assert "-> Mira" in text


# ---------------------------------------------------------------------------
# render_greetings_node
# ---------------------------------------------------------------------------


def _mira() -> NpcSheet:
    return NpcSheet(
        id="mira_vesser",
        name="Mira Vesser",
        role="Tavernkeeper",
        voice="gruff",
    )


def test_greeting_node_title_is_deterministic():
    assert greeting_node_title("mira_vesser", "time_of_day") == "mira_vesser_Greet_time_of_day"


def test_render_greetings_node_five_values_emits_correct_chain():
    variants = [
        ("dawn", "Early, friend."),
        ("morning", "Morning. Fire's lit."),
        ("afternoon", "Sun's high. Drink?"),
        ("dusk", "Long shadows, friend."),
        ("night", "Kitchen's closed."),
    ]
    text = render_greetings_node(_mira(), "time_of_day", variants)

    # For N variants the chain is: 1 <<if>> + (N-1) <<elseif>> + 1 <<else>>
    # (fallback) + 1 <<endif>>. Here N = 5.
    assert text.count("<<if $time_of_day == ") == 1
    assert text.count("<<elseif $time_of_day == ") == 4
    assert text.count("<<else>>") == 1
    assert text.count("<<endif>>") == 1
    # All five values present as literals.
    for value, line in variants:
        assert f'"{value}"' in text
        assert line in text
    # Node metadata.
    assert "title: mira_vesser_Greet_time_of_day" in text
    assert "tags: greeting,variable:time_of_day,npc:mira_vesser" in text
    assert text.rstrip().endswith("===")


def test_render_greetings_node_two_values_uses_if_elseif_else():
    variants = [
        ("morning", "Morning."),
        ("night", "Late."),
    ]
    text = render_greetings_node(_mira(), "time_of_day", variants)
    assert "<<if $time_of_day == \"morning\">>" in text
    assert "<<elseif $time_of_day == \"night\">>" in text
    assert "<<else>>" in text
    assert "<<endif>>" in text


def test_render_greetings_node_empty_variants_still_parseable():
    text = render_greetings_node(_mira(), "time_of_day", [])
    assert "title: mira_vesser_Greet_time_of_day" in text
    assert text.rstrip().endswith("===")


# ---------------------------------------------------------------------------
# Prompt formatter
# ---------------------------------------------------------------------------


def test_format_variables_for_prompt_mentions_enum_values_and_defaults():
    vars_ = [
        ProjectVariable(
            id="time_of_day",
            type="enum",
            values=["morning", "night"],
            description="In-game clock.",
        ),
        ProjectVariable(
            id="bounty",
            type="int",
            range=(0, 1000),
            default=0,
            description="Player bounty.",
        ),
    ]
    block = format_variables_for_prompt(vars_)
    assert "time_of_day" in block
    assert "enum: morning, night" in block
    assert "bounty" in block
    assert "range 0-1000" in block
    # Defaults surface for each variable.
    assert "default: 'morning'" in block
    assert "default: 0" in block


def test_format_variables_for_prompt_empty_returns_empty_string():
    assert format_variables_for_prompt([]) == ""


# ---------------------------------------------------------------------------
# NpcSheet reacts_to field
# ---------------------------------------------------------------------------


def test_npc_sheet_has_reacts_to_default_empty():
    npc = NpcSheet(id="x", name="X", role="r", voice="v")
    assert npc.reacts_to == []


def test_npc_sheet_reacts_to_roundtrips_through_yaml(tmp_path: Path):
    path = tmp_path / "characters.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "npcs": [
                    {
                        "id": "mira",
                        "name": "Mira",
                        "role": "Tavernkeeper",
                        "voice": "gruff",
                        "reacts_to": ["time_of_day", "player_bounty"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    npcs = load_npcs(path)
    assert npcs[0].reacts_to == ["time_of_day", "player_bounty"]
