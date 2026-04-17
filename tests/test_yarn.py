"""Pure tests for the Yarn exporter — no LLM calls."""

from __future__ import annotations

from npcforge.schemas import BarkLine, BarkTrigger, NpcSheet, PlayerIntent
from npcforge.yarn import (
    bark_node_title,
    render_bark_node,
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


def _intent(**overrides) -> PlayerIntent:
    base = dict(
        id="ask_about_local_events",
        name="Ask About Local Events",
        description="Ask politely.",
        opening_intent="open with a question",
    )
    base.update(overrides)
    return PlayerIntent(**base)


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
    intent = _intent()
    turns = [
        {"role": "user", "content": "Hello."},
        {"role": "assistant", "content": "Hmm."},
    ]
    lines = render_yarn_branch(intent, "Mira", turns, "Mira_End")
    assert lines[0] == "-> [Ask About Local Events]"
    assert "    Player: Hello." in lines
    assert "    Mira: Hmm." in lines
    assert lines[-1] == "    <<jump Mira_End>>"


def test_render_yarn_node_for_npc_has_title_branches_and_end_node():
    npc = _npc()
    branch1 = (
        _intent(),
        [
            {"role": "user", "content": "Hello, tavernkeeper."},
            {"role": "assistant", "content": "Drink's two coppers."},
        ],
    )
    branch2 = (
        _intent(id="threaten", name="Threaten for Info"),
        [
            {"role": "user", "content": "Where is it."},
            {"role": "assistant", "content": "Out the way you came."},
        ],
    )
    out = render_yarn_node_for_npc(npc, [branch1, branch2])

    assert "title: mira" in out
    assert "tags: walk_up" in out
    assert "Mira Vesser waits." in out
    assert "-> [Ask About Local Events]" in out
    assert "-> [Threaten for Info]" in out
    assert out.count("<<jump mira_End>>") == 2
    assert "title: mira_End" in out
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


def test_bark_node_title_is_deterministic():
    assert bark_node_title("mira_vesser", "greet_patron") == "mira_vesser_Bark_greet_patron"


def test_render_bark_node_has_counter_branches_and_tags():
    npc = _npc()
    trigger = BarkTrigger(id="greet_patron", description="A new patron enters.", n=3)
    barks = [
        BarkLine(text="Drink's two coppers.", emotion="neutral", intensity="low"),
        BarkLine(text="Sit or leave.", emotion="angry", intensity="medium"),
        BarkLine(text="Mind the step.", emotion="neutral", intensity="low"),
    ]
    out = render_bark_node(npc, trigger, barks)

    title = "mira_Bark_greet_patron"
    assert f"title: {title}" in out
    assert "tags: bark,trigger:greet_patron,npc:mira" in out
    assert "// Bark library: 3 variants for trigger 'greet_patron'" in out
    # Three conditional variants: one `if`, one `elseif`, one `else`.
    assert f'<<if visited_count("{title}") % 3 == 0>>' in out
    assert f'<<elseif visited_count("{title}") % 3 == 1>>' in out
    assert "<<else>>" in out
    assert "<<endif>>" in out
    # Each bark text + emotion comment survived.
    assert "Mira Vesser: Drink's two coppers.  // emotion=neutral intensity=low" in out
    assert "Mira Vesser: Sit or leave.  // emotion=angry intensity=medium" in out


def test_render_bark_node_handles_single_bark():
    npc = _npc()
    trigger = BarkTrigger(id="single", description="Only one.", n=1)
    barks = [BarkLine(text="Hmph.", emotion="neutral")]
    out = render_bark_node(npc, trigger, barks)
    # With one bark, the first-and-only branch should still be valid — `if` + `else` wrap.
    assert 'visited_count("mira_Bark_single")' in out
    assert "Mira Vesser: Hmph." in out
    assert "<<endif>>" in out
