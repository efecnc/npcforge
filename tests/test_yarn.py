"""Pure tests for the Yarn exporter — no LLM calls."""

from __future__ import annotations

from npcforge.schemas import NpcSheet, PlayerArchetype
from npcforge.yarn import (
    render_world_start_node,
    render_yarn_branch,
    render_yarn_node_for_npc,
    yarn_escape_line,
    yarn_safe_title,
)


def _npc(**overrides) -> NpcSheet:
    base = dict(
        id="mira",
        name="Mira Vesser",
        role="Tavernkeeper",
        voice="Gruff, dry, pragmatic.",
    )
    base.update(overrides)
    return NpcSheet(**base)


def _archetype(**overrides) -> PlayerArchetype:
    base = dict(
        id="scholar",
        name="Curious Scholar",
        description="A polite scholar.",
        opening_intent="ask about local events",
    )
    base.update(overrides)
    return PlayerArchetype(**base)


def test_yarn_safe_title_sanitises():
    assert yarn_safe_title("Mira Vesser") == "Mira_Vesser"
    assert yarn_safe_title("mira!@#vesser") == "mira_vesser"
    assert yarn_safe_title("") == "Untitled"
    assert yarn_safe_title("123foo") == "N123foo"


def test_yarn_escape_line_collapses_whitespace():
    assert yarn_escape_line("hello   world") == "hello world"
    assert yarn_escape_line("a\nb\t c") == "a b c"
    assert yarn_escape_line("  padded  ") == "padded"


def test_render_yarn_branch_emits_option_with_turns_and_jump():
    arch = _archetype()
    turns = [
        {"role": "user", "content": "Hello."},
        {"role": "assistant", "content": "Hmm."},
    ]
    lines = render_yarn_branch(arch, "Mira", turns, "Mira_End")
    assert lines[0] == "-> [Curious Scholar]"
    assert "    Player: Hello." in lines
    assert "    Mira: Hmm." in lines
    assert lines[-1] == "    <<jump Mira_End>>"


def test_render_yarn_node_for_npc_has_title_branches_and_end_node():
    npc = _npc()
    branch1 = (
        _archetype(),
        [
            {"role": "user", "content": "Hello, tavernkeeper."},
            {"role": "assistant", "content": "Drink's two coppers."},
        ],
    )
    branch2 = (
        _archetype(id="mercenary", name="Hostile Mercenary"),
        [
            {"role": "user", "content": "Where is it."},
            {"role": "assistant", "content": "Out the way you came."},
        ],
    )
    out = render_yarn_node_for_npc(npc, [branch1, branch2])

    assert "title: mira" in out
    assert "Mira Vesser waits." in out
    assert "-> [Curious Scholar]" in out
    assert "-> [Hostile Mercenary]" in out
    assert out.count("<<jump mira_End>>") == 2
    assert "title: mira_End" in out
    # Two node separators (main + end)
    assert out.count("===") == 2


def test_render_world_start_node_routes_to_each_npc():
    npcs = [_npc(), _npc(id="kess", name="Kess", role="Thief")]
    out = render_world_start_node(npcs)

    assert "title: Start" in out
    assert "-> Mira Vesser — Tavernkeeper" in out
    assert "<<jump mira>>" in out
    assert "-> Kess — Thief" in out
    assert "<<jump kess>>" in out
    assert out.rstrip().endswith("===")
