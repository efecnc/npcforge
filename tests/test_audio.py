"""Tests for v0.7 audio module — line IDs, duration, emotion, lines.csv I/O."""

from __future__ import annotations

from pathlib import Path

import pytest

from npcforge.audio import (
    LineRecord,
    canonicalise_text,
    count_syllables,
    estimate_duration_seconds,
    infer_emotion,
    line_id,
    read_lines_csv,
    write_lines_csv,
)


# ---------------------------------------------------------------------------
# Canonicalisation + line_id
# ---------------------------------------------------------------------------


def test_canonicalise_collapses_whitespace():
    assert canonicalise_text("  hello    world  ") == "hello world"
    assert canonicalise_text("a\nb\tc") == "a b c"


def test_line_id_is_deterministic_across_whitespace_changes():
    a = line_id("mira_vesser", "Drink's two coppers.", "walk_up:threaten:turn_1")
    b = line_id("mira_vesser", "  Drink's  two  coppers.  ", "walk_up:threaten:turn_1")
    assert a == b


def test_line_id_changes_with_context():
    base = "Kitchen's closed."
    a = line_id("mira_vesser", base, "walk_up:accept_refuge:turn_1")
    b = line_id("mira_vesser", base, "greeting:time_of_day=night")
    assert a != b


def test_line_id_changes_with_text():
    a = line_id("mira_vesser", "Kitchen's closed.", "c")
    b = line_id("mira_vesser", "Kitchen's closing.", "c")
    assert a != b


def test_line_id_format():
    lid = line_id("mira_vesser", "Hello.", "walk_up:farewell:turn_0")
    assert lid.startswith("mira_vesser_")
    assert len(lid) == len("mira_vesser_") + 10


# ---------------------------------------------------------------------------
# Syllable count + duration
# ---------------------------------------------------------------------------


def test_count_syllables_basic_words():
    assert count_syllables("drink") == 1
    # "coppers" has two syllables (cop-pers), not one.
    assert count_syllables("coppers") == 2


def test_count_syllables_empty_and_punctuation_only():
    assert count_syllables("") == 0
    assert count_syllables("   !!! ...") == 0


def test_count_syllables_sentence():
    # "Kitchen's closed just drinks for now" — trailing-e rule applies.
    n = count_syllables("Kitchen's closed. Just drinks for now.")
    assert 7 <= n <= 12  # heuristic; don't over-constrain


def test_estimate_duration_clamps_to_minimum():
    assert estimate_duration_seconds("") == 0.3
    assert estimate_duration_seconds("Hi") == 0.3


def test_estimate_duration_grows_with_length():
    short = estimate_duration_seconds("Kitchen's closed.")
    long_ = estimate_duration_seconds(
        "Kitchen's closed just drinks for now and the roads are wet."
    )
    assert long_ > short


# ---------------------------------------------------------------------------
# Emotion heuristic
# ---------------------------------------------------------------------------


def test_infer_emotion_threatening_keywords():
    emotion, intensity = infer_emotion("Get out. I said leave now.")
    assert emotion == "threatening"


def test_infer_emotion_pleading_keywords():
    emotion, _ = infer_emotion("Please, help me — don't go.")
    assert emotion == "pleading"


def test_infer_emotion_warm_keywords():
    emotion, _ = infer_emotion("Welcome, my friend. Take a seat.")
    assert emotion == "warm"


def test_infer_emotion_neutral_default():
    emotion, intensity = infer_emotion("Drink's two coppers.")
    assert emotion == "neutral"
    assert intensity == "medium"


def test_infer_emotion_intensity_high_from_double_exclamation():
    _, intensity = infer_emotion("GET OUT!!!")
    assert intensity == "high"


def test_infer_emotion_intensity_low_from_ellipsis():
    _, intensity = infer_emotion("I... I don't know what to say.")
    assert intensity == "low"


# ---------------------------------------------------------------------------
# CSV roundtrip
# ---------------------------------------------------------------------------


def _sample_records() -> list[LineRecord]:
    return [
        LineRecord(
            line_id="mira_vesser_aaaa111111",
            npc_id="mira_vesser",
            speaker="Mira Vesser",
            context="walk_up:threaten_for_info:turn_1",
            source_file="mira_vesser.yarn",
            emotion="threatening",
            intensity="medium",
            duration_sec=2.75,
            text="Door's behind you, friend. Use it.",
        ),
        LineRecord(
            line_id="mira_vesser_bbbb222222",
            npc_id="mira_vesser",
            speaker="Player",
            context="walk_up:threaten_for_info:turn_0",
            source_file="mira_vesser.yarn",
            emotion="neutral",
            intensity="medium",
            duration_sec=1.25,
            text="Where is the locket.",
        ),
    ]


def test_write_lines_csv_header_and_order(tmp_path: Path):
    path = tmp_path / "lines.csv"
    write_lines_csv(path, _sample_records())
    raw = path.read_text(encoding="utf-8")
    first_line = raw.splitlines()[0]
    # Column order is the contract downstream tooling relies on.
    assert first_line == (
        "line_id,npc_id,speaker,context,source_file,emotion,"
        "intensity,duration_sec,text"
    )


def test_write_lines_csv_roundtrip(tmp_path: Path):
    path = tmp_path / "lines.csv"
    original = _sample_records()
    write_lines_csv(path, original)
    loaded = read_lines_csv(path)
    assert len(loaded) == len(original)
    assert loaded[0].line_id == original[0].line_id
    assert loaded[0].speaker == "Mira Vesser"
    assert loaded[0].emotion == "threatening"
    assert loaded[0].duration_sec == pytest.approx(2.75, abs=0.01)
    assert loaded[1].context == "walk_up:threaten_for_info:turn_0"


def test_read_lines_csv_returns_empty_for_missing_file(tmp_path: Path):
    assert read_lines_csv(tmp_path / "nonexistent.csv") == []
