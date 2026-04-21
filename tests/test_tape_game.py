"""Tape-game demo (no LLM; optional Pillow GIF)."""

from __future__ import annotations

from pathlib import Path

import pytest

from npcforge.tape_game import (
    TapeQuestRuntime,
    TapeSessionConfig,
    _lines_for_option,
    _wrap_block_lines,
    load_tape_quest,
    run_tape_session,
)
from npcforge.play import parse_yarn
from npcforge.schemas import PlayerIntent


_FIXTURE = Path(__file__).parent.parent / "examples" / "tape_game"
_NIGHT = Path(__file__).parent.parent / "examples" / "night_city_game"


def test_tape_quest_advances_on_gates():
    spec = load_tape_quest(_NIGHT / "tape_quest.yaml")
    assert spec is not None
    rt = TapeQuestRuntime(spec=spec)
    assert rt.progress == 0
    assert not rt.try_advance("rue_mox_bartender", "wrong_intent")
    assert rt.try_advance("rue_mox_bartender", "ask_about_braindance")
    assert rt.progress == 1
    assert rt.try_advance("santiago_reyes", "ask_about_fixer_jobs")
    assert rt.try_advance("splice_maelstrom", "ask_about_gang")
    assert rt.try_advance("viktor_vector", "buy_chrome")
    assert rt.progress == 4


@pytest.mark.asyncio
async def test_night_city_follow_quest_runs():
    cfg = TapeSessionConfig(
        demo_dir=_NIGHT,
        gif_path=None,
        follow_quest=True,
    )
    code = await run_tape_session(cfg)
    assert code == 0


@pytest.mark.asyncio
async def test_tape_auto_runs_without_error():
    cfg = TapeSessionConfig(
        demo_dir=_FIXTURE,
        gif_path=None,
        auto_turns=2,
    )
    code = await run_tape_session(cfg)
    assert code == 0


def test_wrap_block_lines_splits_long_dialogue():
    raw = [
        "==",
        "T",
        "==",
        "",
        "This is a very long line that must not be dropped when we wrap it for "
        "the tape recorder and the terminal user at the same time.",
        "",
        "--",
    ]
    out = _wrap_block_lines(raw, 40)
    assert all(len(ln) <= 40 for ln in out)
    assert sum(1 for ln in out if "terminal user" in ln) >= 1


def test_lines_for_option_greet():
    text = (_FIXTURE / "out" / "rowan_keel.yarn").read_text(encoding="utf-8")
    nodes = parse_yarn(text)
    node = next(n for n in nodes if n.title == "rowan_keel")
    intent = PlayerIntent(
        id="greet",
        name="Greet",
        description="d",
    )
    lines = _lines_for_option(node, intent)
    assert any("Rowan Keel" in ln for ln in lines)


@pytest.mark.asyncio
async def test_tape_gif_writes(tmp_path):
    pytest.importorskip("PIL")
    gif = tmp_path / "out.gif"
    cfg = TapeSessionConfig(
        demo_dir=_FIXTURE,
        gif_path=gif,
        auto_turns=1,
        frame_ms=100,
    )
    code = await run_tape_session(cfg)
    assert code == 0
    assert gif.exists()
    assert gif.stat().st_size > 100
