"""Tests for v0.6.1 — repeat-greeting Yarn + play parser extensions."""

from __future__ import annotations

import io
from pathlib import Path

from npcforge.play import (
    parse_yarn,
    play_greetings,
    play_repeat_greeting,
    render_enum_variants,
    render_visit_variants,
)
from npcforge.schemas import NpcSheet
from npcforge.yarn import (
    render_greetings_node,
    render_repeat_greeting_node,
    repeat_greeting_node_title,
)


def _mira() -> NpcSheet:
    return NpcSheet(
        id="mira_vesser",
        name="Mira Vesser",
        role="Tavernkeeper",
        voice="gruff",
    )


# ---------------------------------------------------------------------------
# Repeat-greeting Yarn emission
# ---------------------------------------------------------------------------


def test_repeat_greeting_node_title_is_deterministic():
    assert repeat_greeting_node_title("mira_vesser") == "mira_vesser_RepeatGreet"


def test_render_repeat_greeting_three_variants():
    text = render_repeat_greeting_node(
        _mira(),
        [
            "First time I've seen that face.",
            "Back already, friend?",
            "The Lantern remembers you now.",
        ],
    )
    title = "mira_vesser_RepeatGreet"
    assert f"title: {title}" in text
    assert "tags: repeat_greeting,npc:mira_vesser" in text
    # 1 if, 1 elseif, 1 else, 1 endif for 3 variants.
    assert text.count(f'<<if visited_count("{title}") == 0>>') == 1
    assert text.count(f'<<elseif visited_count("{title}") == 1>>') == 1
    assert text.count("<<else>>") == 1
    assert text.count("<<endif>>") == 1
    # All three lines appear verbatim.
    assert "First time I've seen that face." in text
    assert "Back already, friend?" in text
    assert "The Lantern remembers you now." in text


def test_render_repeat_greeting_two_variants_has_no_elseif():
    text = render_repeat_greeting_node(
        _mira(),
        ["Stranger.", "You again."],
    )
    title = "mira_vesser_RepeatGreet"
    assert f'<<if visited_count("{title}") == 0>>' in text
    assert "<<elseif" not in text
    assert "<<else>>" in text
    assert "<<endif>>" in text


def test_render_repeat_greeting_empty_variants_emits_fallback():
    text = render_repeat_greeting_node(_mira(), [])
    assert "title: mira_vesser_RepeatGreet" in text
    assert "<<if" not in text
    assert text.rstrip().endswith("===")


# ---------------------------------------------------------------------------
# Parser extensions — enum + visit variants
# ---------------------------------------------------------------------------


def test_parser_extracts_enum_greeting_variants():
    text = render_greetings_node(
        _mira(),
        "time_of_day",
        [
            ("morning", "Sun's barely up."),
            ("night", "Kitchen's closed."),
        ],
    )
    nodes = parse_yarn(text)
    node = nodes[0]
    assert [(v, value, line.text) for v, value, line in node.enum_variants] == [
        ("time_of_day", "morning", "Sun's barely up."),
        ("time_of_day", "night", "Kitchen's closed."),
    ]
    # No bark / visit variants should have been collected (clean dispatch).
    assert node.bark_variants == []
    assert node.visit_variants == []


def test_parser_extracts_repeat_greeting_variants():
    text = render_repeat_greeting_node(
        _mira(),
        [
            "First time I've seen that face.",
            "Back already, friend?",
            "The Lantern remembers you now.",
        ],
    )
    nodes = parse_yarn(text)
    node = nodes[0]
    indices = [idx for idx, _ in node.visit_variants]
    # Numeric branches plus the else-fallback at index -1.
    assert indices == [0, 1, -1]
    assert node.visit_variants[0][1].text == "First time I've seen that face."
    assert node.visit_variants[1][1].text == "Back already, friend?"
    assert node.visit_variants[2][1].text == "The Lantern remembers you now."
    assert node.enum_variants == []
    assert node.bark_variants == []


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def test_render_enum_variants_labels_each_line():
    text = render_greetings_node(
        _mira(),
        "time_of_day",
        [("morning", "Sun's up."), ("night", "Kitchen's closed.")],
    )
    node = parse_yarn(text)[0]
    buf = io.StringIO()
    render_enum_variants(node, stream=buf, tempo=0.0, wait=False)
    out = buf.getvalue()
    assert "[time_of_day=morning]" in out
    assert "[time_of_day=night]" in out
    assert "Sun's up." in out
    assert "Kitchen's closed." in out


def test_render_visit_variants_labels_each_line():
    text = render_repeat_greeting_node(
        _mira(), ["Stranger.", "You again.", "Regular now."]
    )
    node = parse_yarn(text)[0]
    buf = io.StringIO()
    render_visit_variants(node, stream=buf, tempo=0.0, wait=False)
    out = buf.getvalue()
    assert "[visit #0]" in out
    assert "[visit #1]" in out
    assert "Stranger." in out


# ---------------------------------------------------------------------------
# End-to-end play_* — write a node to tmp, render from disk
# ---------------------------------------------------------------------------


def test_play_greetings_round_trip_from_disk(tmp_path: Path):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    text = render_greetings_node(
        _mira(),
        "time_of_day",
        [("morning", "Sun's barely up."), ("night", "Kitchen's closed.")],
    )
    (out_dir / "mira_vesser_greet_time_of_day.yarn").write_text(text, encoding="utf-8")

    buf = io.StringIO()
    code = play_greetings(
        demo_dir=tmp_path,
        npc_id="mira_vesser",
        variable_id="time_of_day",
        out=out_dir,
        tempo=0.0,
        wait=False,
        stream=buf,
    )
    assert code == 0
    out = buf.getvalue()
    assert "[time_of_day=morning]" in out
    assert "Kitchen's closed." in out


def test_play_repeat_greeting_round_trip_from_disk(tmp_path: Path):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    text = render_repeat_greeting_node(
        _mira(), ["Stranger.", "You again.", "Regular now."]
    )
    (out_dir / "mira_vesser_repeat_greet.yarn").write_text(text, encoding="utf-8")

    buf = io.StringIO()
    code = play_repeat_greeting(
        demo_dir=tmp_path,
        npc_id="mira_vesser",
        out=out_dir,
        tempo=0.0,
        wait=False,
        stream=buf,
    )
    assert code == 0
    out = buf.getvalue()
    assert "[visit #0]" in out
    assert "You again." in out


def test_play_greetings_missing_file_exits_nonzero(tmp_path: Path):
    buf = io.StringIO()
    code = play_greetings(
        demo_dir=tmp_path,
        npc_id="nobody",
        variable_id="time_of_day",
        out=tmp_path,
        tempo=0.0,
        stream=buf,
    )
    assert code == 1
