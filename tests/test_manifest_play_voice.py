"""Tests for v0.5.0: typed Manifest, play parser/renderer, voice-score math."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from npcforge.manifest import (
    BarkTriggerEntry,
    LintSummary,
    Manifest,
    NpcEntry,
    NpcWalkUpEntry,
    WorldEntry,
)
from npcforge.play import (
    parse_yarn,
    play_barks,
    play_walk_up,
    render_all_branches,
    render_barks,
    render_branch,
)
from npcforge.voice_score import _cosine, _normalise


_SAMPLE_DIR = Path(__file__).parent.parent / "examples" / "rusted_lantern" / "sample_output"


# ---------------------------------------------------------------------------
# Manifest schema
# ---------------------------------------------------------------------------


def test_manifest_round_trips_with_json_alias():
    m = Manifest(
        version="0.5.0",
        generated_at="2026-04-17T12:00:00+00:00",
        provider="gemini",
        mode="all",
        npcs={
            "mira_vesser": NpcEntry(
                sheet_hash="abc123",
                walk_up=NpcWalkUpEntry(
                    yarn="mira_vesser.yarn",
                    yarn_hash="deadbeef",
                    intents=["ask_about_locket", "farewell"],
                    branch_count=2,
                    voice_scores={"ask_about_locket": 0.82, "farewell": 0.77},
                ),
                barks=[
                    BarkTriggerEntry(
                        trigger="greet_patron",
                        requested=10,
                        produced=10,
                        yarn="mira_vesser_bark_greet_patron.yarn",
                        yarn_hash="cafef00d",
                        json_path="mira_vesser_bark_greet_patron.json",
                    )
                ],
            )
        },
        world=WorldEntry(yarn="world.yarn", yarn_hash="1234abcd"),
        lint=LintSummary(markdown="lint.md", total_hits=0),
        elapsed_seconds=331.5,
        voice_scoring_enabled=True,
    )

    as_json = m.model_dump_json(by_alias=True)
    data = json.loads(as_json)

    # The wire format must surface the bark json field as "json", not "json_path".
    assert data["npcs"]["mira_vesser"]["barks"][0]["json"] == "mira_vesser_bark_greet_patron.json"
    assert "json_path" not in data["npcs"]["mira_vesser"]["barks"][0]

    # Voice scores survive.
    scores = data["npcs"]["mira_vesser"]["walk_up"]["voice_scores"]
    assert scores == {"ask_about_locket": 0.82, "farewell": 0.77}

    # Round-trip back into the model via alias-aware parsing.
    loaded = Manifest.model_validate(data)
    assert loaded.npcs["mira_vesser"].barks[0].json_path == "mira_vesser_bark_greet_patron.json"
    assert loaded.voice_scoring_enabled is True


def test_manifest_defaults_keep_shape_stable():
    """A nearly-empty manifest still validates and dumps cleanly."""
    m = Manifest(
        version="0.5.0",
        generated_at="2026-04-17T00:00:00+00:00",
        provider="openai",
        mode="walk_up",
        lint=LintSummary(markdown="lint.md", total_hits=0),
    )
    data = json.loads(m.model_dump_json())
    assert data["npcs"] == {}
    assert data["world"] is None
    assert data["voice_scoring_enabled"] is False


# ---------------------------------------------------------------------------
# Yarn parser
# ---------------------------------------------------------------------------


def test_parse_yarn_walk_up_node_has_expected_options():
    text = (_SAMPLE_DIR / "mira_vesser.yarn").read_text(encoding="utf-8")
    nodes = parse_yarn(text)
    node = next(n for n in nodes if n.title == "mira_vesser")
    option_labels = {opt.label for opt in node.options}
    assert {"Threaten for Information", "Bribe for Information", "Farewell"}.issubset(
        option_labels
    )
    threaten = next(o for o in node.options if o.label == "Threaten for Information")
    # Player opens, NPC replies, jump ends.
    assert len(threaten.lines) >= 2
    assert threaten.lines[0].speaker.lower() == "player"
    assert threaten.jump_to and threaten.jump_to.endswith("_End")


def test_parse_yarn_bark_node_extracts_variants():
    text = (_SAMPLE_DIR / "mira_vesser_bark_reacts_to_hum.yarn").read_text(encoding="utf-8")
    nodes = parse_yarn(text)
    assert len(nodes) == 1
    node = nodes[0]
    # Known content from the committed sample.
    assert len(node.bark_variants) >= 3
    # Emotion/intensity comments must be stripped from line text.
    assert all("//" not in v.text for v in node.bark_variants)
    # Mira's accent marker — all variants should say "deep", never "mine".
    joined = " ".join(v.text.lower() for v in node.bark_variants)
    assert "deep" in joined
    assert "mine" not in joined


# ---------------------------------------------------------------------------
# Renderers (pure, write to StringIO)
# ---------------------------------------------------------------------------


def test_render_branch_by_case_insensitive_match():
    text = (_SAMPLE_DIR / "mira_vesser.yarn").read_text(encoding="utf-8")
    node = next(n for n in parse_yarn(text) if n.title == "mira_vesser")
    buf = io.StringIO()
    ok = render_branch(node, "threaten for info", stream=buf, tempo=0.0, wait=False)
    assert ok
    out = buf.getvalue()
    assert "Threaten for Information" in out
    assert "Mira Vesser:" in out
    assert "Player:" in out


def test_render_branch_returns_false_for_unknown_label():
    text = (_SAMPLE_DIR / "mira_vesser.yarn").read_text(encoding="utf-8")
    node = next(n for n in parse_yarn(text) if n.title == "mira_vesser")
    buf = io.StringIO()
    ok = render_branch(node, "nonsense label", stream=buf, tempo=0.0)
    assert ok is False


def test_render_barks_lists_every_variant():
    text = (_SAMPLE_DIR / "mira_vesser_bark_reacts_to_hum.yarn").read_text(encoding="utf-8")
    node = parse_yarn(text)[0]
    buf = io.StringIO()
    render_barks(node, stream=buf, tempo=0.0)
    out = buf.getvalue()
    for variant in node.bark_variants:
        assert variant.text in out


def test_render_all_branches_prints_every_option():
    text = (_SAMPLE_DIR / "mira_vesser.yarn").read_text(encoding="utf-8")
    node = next(n for n in parse_yarn(text) if n.title == "mira_vesser")
    buf = io.StringIO()
    render_all_branches(node, stream=buf, tempo=0.0)
    out = buf.getvalue()
    for opt in node.options:
        assert opt.label in out


# ---------------------------------------------------------------------------
# End-to-end play_* (no LLM, runs against committed sample_output)
# ---------------------------------------------------------------------------


def test_play_walk_up_against_sample_output():
    buf = io.StringIO()
    code = play_walk_up(
        demo_dir=_SAMPLE_DIR.parent,
        npc_id="mira_vesser",
        intent="Farewell",
        out=_SAMPLE_DIR,
        tempo=0.0,
        wait=False,
        stream=buf,
    )
    assert code == 0
    assert "Farewell" in buf.getvalue()


def test_play_barks_against_sample_output():
    buf = io.StringIO()
    code = play_barks(
        demo_dir=_SAMPLE_DIR.parent,
        npc_id="mira_vesser",
        trigger="reacts_to_hum",
        out=_SAMPLE_DIR,
        tempo=0.0,
        wait=False,
        stream=buf,
    )
    assert code == 0
    assert "Mira Vesser:" in buf.getvalue()


def test_play_walk_up_missing_file_exits_nonzero(tmp_path: Path):
    buf = io.StringIO()
    code = play_walk_up(
        demo_dir=tmp_path,
        npc_id="nobody",
        intent=None,
        out=tmp_path,
        tempo=0.0,
        wait=False,
        stream=buf,
    )
    assert code == 1


# ---------------------------------------------------------------------------
# Voice-score math
# ---------------------------------------------------------------------------


def test_cosine_identical_vectors_is_one():
    v = [0.1, 0.3, 0.7, 0.2]
    assert _cosine(v, v) == pytest.approx(1.0, abs=1e-9)


def test_cosine_orthogonal_vectors_is_zero():
    assert _cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0, abs=1e-9)


def test_cosine_opposite_vectors_is_negative_one():
    assert _cosine([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0, abs=1e-9)


def test_cosine_with_zero_vector_returns_zero():
    assert _cosine([0.0, 0.0], [1.0, 2.0]) == 0.0
    assert _cosine([1.0, 2.0], []) == 0.0


def test_normalise_clamps_to_unit_interval():
    assert _normalise(-0.2) == 0.0
    assert _normalise(1.5) == 1.0
    assert _normalise(0.42) == pytest.approx(0.42)
