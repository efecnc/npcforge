"""Tests for the voice-ceiling lint scanner."""

from __future__ import annotations

from npcforge.lint import (
    LintReport,
    lint_barks,
    lint_text,
    lint_walk_up_branches,
)
from npcforge.schemas import BarkLine, NpcSheet, PlayerIntent


def _npc(forbidden: list[str]) -> NpcSheet:
    return NpcSheet(
        id="test_npc",
        name="Test NPC",
        role="tester",
        voice="v",
        forbidden_words=forbidden,
    )


def test_lint_text_flags_forbidden_stem_and_inflection():
    npc = _npc(["intriguing", "peculiar"])
    text = "That is an intriguing tale, and the pattern is peculiar."
    hits = lint_text(npc, text, location="walk_up:x:turn_0")
    assert len(hits) == 2
    assert {h.word.lower() for h in hits} == {"intriguing", "peculiar"}
    assert all(h.npc_id == "test_npc" for h in hits)
    assert all(h.location == "walk_up:x:turn_0" for h in hits)


def test_lint_text_matches_common_inflections():
    npc = _npc(["fascinate"])
    text = "She fascinates the crowd. Yesterday she fascinated them even more."
    hits = lint_text(npc, text, location="l")
    # 'fascinates' → matches 'fascinate' + 's'; 'fascinated' → + 'ed'.
    assert len(hits) >= 2


def test_lint_text_is_case_insensitive():
    npc = _npc(["LOL"])
    hits = lint_text(npc, "lol that's wild", location="l")
    assert len(hits) == 1


def test_lint_text_no_forbidden_returns_empty():
    npc = _npc([])
    assert lint_text(npc, "any text", location="l") == []


def test_lint_walk_up_branches_only_scans_assistant_turns():
    npc = _npc(["intriguing"])
    intent = PlayerIntent(id="i", name="I", description="d")
    branches = [
        (
            intent,
            [
                # Player line — must be ignored even if it contains the word.
                {"role": "user", "content": "Tell me something intriguing."},
                {"role": "assistant", "content": "Plain story, nothing fancy."},
                {"role": "user", "content": "More?"},
                {"role": "assistant", "content": "Here is an intriguing tale."},
            ],
        ),
    ]
    hits = lint_walk_up_branches(npc, branches)
    assert len(hits) == 1
    assert hits[0].location == "walk_up:i:turn_3"


def test_lint_barks_locations_are_indexed():
    npc = _npc(["dude"])
    barks = [
        BarkLine(text="Back off.", emotion="angry"),
        BarkLine(text="Easy, dude, easy.", emotion="neutral"),
    ]
    hits = lint_barks(npc, "combat_start", barks)
    assert len(hits) == 1
    assert hits[0].location == "bark:combat_start:1"


def test_lint_report_markdown_clean_and_dirty():
    clean = LintReport()
    md = clean.format_markdown()
    assert "Clean run" in md

    dirty = LintReport()
    dirty.hits.extend(
        lint_text(_npc(["intriguing"]), "That is intriguing.", location="walk_up:a:turn_0")
    )
    md2 = dirty.format_markdown()
    assert "**Total hits:** 1" in md2
    assert "test_npc" in md2
