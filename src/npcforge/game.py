"""Interactive CLI game driven by a generated npcforge project.

    npcforge game --demo-dir examples/rusted_lantern

Plays a pre-built walk-up dialog set as an explorable, stateful tavern.
The player picks NPCs, picks intents, sees the dialog, and watches their
standing with each NPC drift across that NPC's trajectory waypoints
(with a sensible default scale when a sheet doesn't declare one).

No LLM calls. Everything comes from ``<demo_dir>/out/*.yarn`` plus the
NPC sheets. Run ``npcforge build --mode walk_up`` first.

The presentation layer is deliberately designed for the terminal:

- Box-drawn headers so a scene has a frame;
- A sigil + an owned colour per NPC for fast visual identity;
- A 10-segment disposition bar so a number becomes a gradient you feel;
- Intent tone tags (``warm``, ``hostile``, ``tense``) derived from the
  delta table, so a writer adding a new intent gets good UX for free;
- Two-tier dialog (SPEAKER / wrapped body) that survives 80-column
  terminals without breaking sentences mid-word;
- A reaction beat and a press-Enter gate after every exchange so lines
  breathe instead of being chased off the screen;
- A context-sensitive hint bar at the bottom of every menu so you
  never wonder what the keys are.
"""

from __future__ import annotations

import random
import shutil
import sys
import textwrap
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, TextIO

import yaml
from pydantic import BaseModel, Field

from .play import YarnNode, YarnOption, parse_yarn
from .schemas import NpcSheet, PlayerIntent, load_intents, load_npcs


# ---------------------------------------------------------------------------
# Scoring — how intents move the relationship needle
# ---------------------------------------------------------------------------


INTENT_DELTAS: dict[str, float] = {
    # Communal / vulnerable — biggest positives.
    "confess_vulnerability": 0.15,
    "offer_help": 0.10,
    "confess_sin": 0.12,
    # Warm.
    "flirt": 0.08,
    "accept_refuge": 0.07,
    "ask_to_bless": 0.05,
    # Transactional — mild positives or zero.
    "barter_wares": 0.04,
    "buy_chrome": 0.04,
    "ask_about_fixer_jobs": 0.03,
    "hack_request": 0.02,
    "ask_about_rumors": 0.02,
    "ask_about_local_events": 0.02,
    "ask_about_npc_other": 0.01,
    "ask_about_bayou_guide": 0.02,
    "ask_about_boarding": 0.02,
    "farewell": 0.01,
    "bribe_for_info": 0.00,
    # Sensitive.
    "ask_about_braindance": -0.02,
    "ask_about_netwatch": -0.02,
    "ask_about_locket": -0.04,
    "ask_about_gang": -0.03,
    "ask_about_raiders": -0.03,
    "ask_about_bounty": -0.02,
    # Hostile.
    "threaten_for_info": -0.25,
    "challenge_to_duel": -0.30,
    "challenge_statement": -0.05,
    "challenge_authority": -0.15,
    "insult": -0.20,
}


_DEFAULT_WAYPOINTS = [
    (-float("inf"), "hostile"),
    (-0.25, "wary"),
    (0.0, "stranger"),
    (0.25, "acquainted"),
    (0.65, "trusted"),
    (1.20, "confidant"),
]


@dataclass
class Standing:
    label: str
    description: str = ""
    voice_shift: str = ""
    unlocks_knowledge: tuple[str, ...] = ()


def resolve_standing(npc: NpcSheet, score: float) -> Standing:
    traj = getattr(npc, "trajectory", None)
    if traj is not None and getattr(traj, "waypoints", None):
        waypoints = sorted(traj.waypoints, key=lambda w: w.min_score)
        chosen = waypoints[0]
        for wp in waypoints:
            if score >= wp.min_score:
                chosen = wp
        return Standing(
            label=chosen.label or chosen.id,
            description=chosen.description or "",
            voice_shift=chosen.voice_shift or "",
            unlocks_knowledge=tuple(chosen.unlocks_knowledge),
        )

    label = _DEFAULT_WAYPOINTS[0][1]
    for threshold, name in _DEFAULT_WAYPOINTS:
        if score >= threshold:
            label = name
    return Standing(label=label)


# ---------------------------------------------------------------------------
# Game state
# ---------------------------------------------------------------------------


@dataclass
class GameState:
    disposition: dict[str, float] = field(default_factory=dict)
    visits: dict[str, int] = field(default_factory=dict)
    unlocked_knowledge: dict[str, set[str]] = field(default_factory=dict)
    played_branches: dict[str, set[str]] = field(default_factory=dict)
    turn_count: int = 0
    unlocked_clues: set[str] = field(default_factory=set)
    ending: str | None = None

    def score_for(self, npc_id: str) -> float:
        return self.disposition.get(npc_id, 0.0)

    def apply(self, npc_id: str, intent_id: str) -> float:
        delta = INTENT_DELTAS.get(intent_id, 0.0)
        self.disposition[npc_id] = self.score_for(npc_id) + delta
        self.visits[npc_id] = self.visits.get(npc_id, 0) + 1
        self.played_branches.setdefault(npc_id, set()).add(intent_id)
        self.turn_count += 1
        return self.disposition[npc_id]


# ---------------------------------------------------------------------------
# Quest layer — optional per-project clues.yaml
# ---------------------------------------------------------------------------


class _ClueGate(BaseModel):
    npc: str
    intent: str


class _Clue(BaseModel):
    id: str
    gate: _ClueGate
    flash: str = ""
    log: str = ""


class _Resolution(BaseModel):
    id: str
    min_clues: int = 0
    label: str
    outcome: str = ""
    ending: str = "quest_resolved"


class _QuestMeta(BaseModel):
    id: str
    name: str
    player_brief: str = ""


class CluesConfig(BaseModel):
    """Top-level ``clues.yaml`` schema — the per-project quest layer."""

    quest: _QuestMeta | None = None
    clues: list[_Clue] = Field(default_factory=list)
    resolutions: list[_Resolution] = Field(default_factory=list)

    def by_gate(self, npc_id: str, intent_id: str) -> list[_Clue]:
        return [
            c
            for c in self.clues
            if c.gate.npc == npc_id and c.gate.intent == intent_id
        ]

    def available_resolutions(self, unlocked_count: int) -> list[_Resolution]:
        return [r for r in self.resolutions if r.min_clues <= unlocked_count]


def _load_clues(demo_dir: Path) -> CluesConfig | None:
    path = demo_dir / "clues.yaml"
    if not path.exists():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return None
    try:
        return CluesConfig(**data)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Yarn loader
# ---------------------------------------------------------------------------


def _npc_yarn_path(demo_dir: Path, npc_id: str) -> Path:
    return demo_dir / "out" / f"{npc_id}.yarn"


def _intent_label_to_id_map(intents: list[PlayerIntent]) -> dict[str, str]:
    out: dict[str, str] = {}
    for intent in intents:
        out[intent.name.lower().strip()] = intent.id
        out[intent.id.lower().strip()] = intent.id
    return out


def load_npc_branches(
    demo_dir: Path, npc: NpcSheet, label_to_id: dict[str, str]
) -> dict[str, YarnOption]:
    path = _npc_yarn_path(demo_dir, npc.id)
    if not path.exists():
        return {}
    nodes = parse_yarn(path.read_text(encoding="utf-8"))
    walk_node: YarnNode | None = next(
        (n for n in nodes if n.title == npc.id and "walk_up" in n.tags), None
    )
    if walk_node is None:
        walk_node = next((n for n in nodes if not n.title.endswith("_End")), None)
    if walk_node is None:
        return {}
    out: dict[str, YarnOption] = {}
    for opt in walk_node.options:
        key = label_to_id.get(opt.label.lower().strip(), opt.label.lower().strip())
        out[key] = opt
    return out


# ---------------------------------------------------------------------------
# Presentation primitives
# ---------------------------------------------------------------------------


_ANSI_DIM = "\x1b[2m"
_ANSI_BOLD = "\x1b[1m"
_ANSI_ITALIC = "\x1b[3m"
_ANSI_UNDERLINE = "\x1b[4m"
_ANSI_RESET = "\x1b[0m"

# 24-bit colour palette. Muted, tavern-lamp warm.
_ANSI_RED = "\x1b[38;2;220;100;90m"
_ANSI_YELLOW = "\x1b[38;2;212;176;90m"
_ANSI_GREEN = "\x1b[38;2;120;180;110m"
_ANSI_CYAN = "\x1b[38;2;125;175;205m"
_ANSI_PURPLE = "\x1b[38;2;180;130;210m"
_ANSI_ORANGE = "\x1b[38;2;225;140;80m"
_ANSI_GREY = "\x1b[38;2;160;160;165m"
_ANSI_GREY_DARK = "\x1b[38;2;110;110;115m"
_ANSI_FG_DEFAULT = "\x1b[39m"

# Per-NPC colour palette (deterministic, cycled by index).
_NPC_COLOURS = [_ANSI_YELLOW, _ANSI_ORANGE, _ANSI_CYAN, _ANSI_PURPLE, _ANSI_GREEN]


def _use_colour(stream: TextIO) -> bool:
    return hasattr(stream, "isatty") and stream.isatty()


def _c(stream: TextIO, text: str, code: str) -> str:
    return f"{code}{text}{_ANSI_RESET}" if _use_colour(stream) else text


def _term_width(stream: TextIO, default: int = 80) -> int:
    try:
        return max(60, min(110, shutil.get_terminal_size((default, 24)).columns))
    except Exception:
        return default


# ---------------------------------------------------------------------------
# NPC sigil + colour
# ---------------------------------------------------------------------------


_SIGILS_BY_KEYWORD: list[tuple[tuple[str, ...], str]] = [
    (("tavern", "keeper", "bartender", "innkeeper", "boarding"), "♦"),
    (("dwarf", "miner", "smith", "mason"), "⚒"),
    (("cleric", "priest", "sister", "reverend", "chapel", "temple", "paladin"), "☽"),
    (("thief", "knife", "rogue", "merchant", "trader", "tinker", "fence"), "✦"),
    (("old", "scholar", "cartograph", "star", "mystic", "sage", "reader"), "☌"),
    (("guide", "swamp", "scout", "tracker", "ranger", "bayou", "caravan", "refugee"), "⌇"),
    (("ripper", "doc", "chrome", "medic", "surgeon"), "✚"),
    (("cop", "pinkerton", "agent", "watch", "detective", "inquisitor"), "◈"),
    (("gang", "raider", "fighter", "enforcer", "warrior", "soldier"), "⚔"),
    (("fixer", "courier", "handler"), "⌘"),
]


def _npc_sigil(npc: NpcSheet) -> str:
    haystack = (npc.role + " " + npc.name).lower()
    for keys, sigil in _SIGILS_BY_KEYWORD:
        if any(k in haystack for k in keys):
            return sigil
    return "○"


def _npc_colour(index: int) -> str:
    return _NPC_COLOURS[index % len(_NPC_COLOURS)]


# ---------------------------------------------------------------------------
# Disposition bar + standing formatting
# ---------------------------------------------------------------------------


_BAR_WIDTH = 12
# Score range covered by the bar: -0.5 (left edge) → +1.5 (right edge).
_BAR_MIN = -0.5
_BAR_MAX = 1.5
_BAR_FULL = "█"
_BAR_HALF = "▌"
_BAR_EMPTY = "░"


def _dispo_bar(stream: TextIO, score: float) -> str:
    pct = (score - _BAR_MIN) / (_BAR_MAX - _BAR_MIN)
    pct = max(0.0, min(1.0, pct))
    full_cells = int(pct * _BAR_WIDTH)
    remainder = (pct * _BAR_WIDTH) - full_cells
    bar = _BAR_FULL * full_cells
    if remainder >= 0.5 and full_cells < _BAR_WIDTH:
        bar += _BAR_HALF
        full_cells += 1
    bar += _BAR_EMPTY * (_BAR_WIDTH - full_cells)

    if score >= 0.5:
        code = _ANSI_GREEN
    elif score >= 0.0:
        code = _ANSI_CYAN
    elif score >= -0.2:
        code = _ANSI_YELLOW
    else:
        code = _ANSI_RED
    return _c(stream, bar, code)


def _score_text(stream: TextIO, score: float) -> str:
    sign = "+" if score >= 0 else ""
    raw = f"{sign}{score:.2f}"
    if score >= 0.5:
        code = _ANSI_GREEN
    elif score >= 0.0:
        code = _ANSI_CYAN
    elif score >= -0.2:
        code = _ANSI_YELLOW
    else:
        code = _ANSI_RED
    return _c(stream, raw, code)


# ---------------------------------------------------------------------------
# Intent tone tags
# ---------------------------------------------------------------------------


def _intent_tone(intent_id: str) -> tuple[str, str] | None:
    delta = INTENT_DELTAS.get(intent_id, 0.0)
    if delta <= -0.2:
        return "hostile", _ANSI_RED
    if delta <= -0.03:
        return "tense", _ANSI_YELLOW
    if delta >= 0.10:
        return "warm", _ANSI_GREEN
    if delta >= 0.04:
        return "friendly", _ANSI_CYAN
    return None


# ---------------------------------------------------------------------------
# Reaction beats
# ---------------------------------------------------------------------------


_REACTIONS_BIG_POSITIVE = [
    "Their guard drops a notch.",
    "Something in their face softens; they look at you as a person, not a problem.",
    "They linger on the reply a beat longer than necessary.",
    "A small, unsurprised nod — you said the thing they were waiting to hear.",
]

_REACTIONS_SMALL_POSITIVE = [
    "They allow the conversation to keep going.",
    "A slight, measured nod.",
    "They don't quite smile. But they don't look away.",
]

_REACTIONS_SMALL_NEGATIVE = [
    "A flicker passes across their face.",
    "Their reply lands a half-second late.",
    "They glance past your shoulder before answering.",
]

_REACTIONS_BIG_NEGATIVE = [
    "Their face hardens.",
    "The room quiets around the two of you by half a degree.",
    "You feel the distance open between you.",
    "They take a step back from the bar.",
]


def _reaction_line(delta: float, seed: int) -> str:
    r = random.Random(seed)
    a = abs(delta)
    if a < 0.03:
        return ""
    if delta > 0:
        pool = _REACTIONS_BIG_POSITIVE if a >= 0.10 else _REACTIONS_SMALL_POSITIVE
    else:
        pool = _REACTIONS_BIG_NEGATIVE if a >= 0.15 else _REACTIONS_SMALL_NEGATIVE
    return r.choice(pool)


# ---------------------------------------------------------------------------
# Screen helpers
# ---------------------------------------------------------------------------


def _clear(stream: TextIO) -> None:
    if _use_colour(stream):
        stream.write("\x1b[2J\x1b[H")
        stream.flush()
    else:
        print("\n" * 2, file=stream)


def _hrule(stream: TextIO, char: str = "─", pad: str = "") -> None:
    width = _term_width(stream)
    line = char * width
    print(_c(stream, f"{pad}{line}", _ANSI_GREY_DARK), file=stream)


def _box_header(stream: TextIO, title: str, subtitle: str = "") -> None:
    width = _term_width(stream)
    top = "╭" + "─" * (width - 2) + "╮"
    bot = "╰" + "─" * (width - 2) + "╯"
    print(_c(stream, top, _ANSI_GREY_DARK), file=stream)
    title_line = "│ " + _c(stream, title, _ANSI_BOLD)
    visible = len(title) + 2
    title_line += " " * max(0, width - visible - 1) + _c(stream, "│", _ANSI_GREY_DARK)
    print(title_line, file=stream)
    if subtitle:
        for line in textwrap.wrap(subtitle, width=width - 4):
            sub = "│ " + _c(stream, line, _ANSI_DIM)
            visible = len(line) + 2
            sub += " " * max(0, width - visible - 1) + _c(stream, "│", _ANSI_GREY_DARK)
            print(sub, file=stream)
    print(_c(stream, bot, _ANSI_GREY_DARK), file=stream)


def _hint_bar(stream: TextIO, hints: list[tuple[str, str]]) -> None:
    width = _term_width(stream)
    parts = [
        _c(stream, f"[{key}]", _ANSI_BOLD) + _c(stream, f" {label}", _ANSI_DIM)
        for key, label in hints
    ]
    text = "   ".join(parts)
    print(f"\n  {text}", file=stream)


# ---------------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------------


def _prompt(stream_in: TextIO, stream_out: TextIO, prompt: str = "  > ") -> str:
    print(_c(stream_out, prompt, _ANSI_DIM), end="", file=stream_out, flush=True)
    line = stream_in.readline()
    if not line:
        return "q"
    return line.strip()


def _press_enter(stream_in: TextIO, stream_out: TextIO, note: str = "press Enter") -> None:
    print(file=stream_out)
    print(_c(stream_out, f"  — {note} —", _ANSI_DIM), end="", file=stream_out, flush=True)
    stream_in.readline()


def _pick(
    stream_in: TextIO,
    stream_out: TextIO,
    prompt: str,
    choices: list[str],
    back_label: str | None,
    hints: list[tuple[str, str]],
) -> int | None:
    """Render a menu, read the user's pick. Returns the index or ``None`` for back/quit."""
    for i, line in enumerate(choices, start=1):
        print(f"  {_c(stream_out, f'{i:>2}', _ANSI_BOLD)}  {line}", file=stream_out)
    _hint_bar(stream_out, hints)
    while True:
        raw = _prompt(stream_in, stream_out, f"  {prompt} ")
        if raw in ("q", "Q", "quit", "exit", ""):
            return None
        if back_label is not None and raw in ("b", "B", "back"):
            return None
        try:
            idx = int(raw)
        except ValueError:
            print(
                _c(
                    stream_out,
                    f"  ? type a number 1..{len(choices)} or '{back_label or 'q'}'",
                    _ANSI_GREY_DARK,
                ),
                file=stream_out,
            )
            continue
        if 1 <= idx <= len(choices):
            return idx - 1
        print(
            _c(
                stream_out,
                f"  ? out of range — pick 1..{len(choices)}",
                _ANSI_GREY_DARK,
            ),
            file=stream_out,
        )


# ---------------------------------------------------------------------------
# Dialog rendering — two-tier, wrapped
# ---------------------------------------------------------------------------


def _print_dialog_turn(
    stream: TextIO, speaker: str, speaker_colour: str, text: str, tempo: float
) -> None:
    width = _term_width(stream)
    print(f"  {_c(stream, speaker.upper(), speaker_colour)}", file=stream)
    for line in textwrap.wrap(text, width=width - 6) or [""]:
        print(f"      {line}", file=stream)
    print(file=stream)
    if tempo > 0:
        time.sleep(tempo)


def _play_branch(
    stream: TextIO,
    npc: NpcSheet,
    npc_colour: str,
    option: YarnOption,
    tempo: float,
) -> None:
    width = _term_width(stream)
    label = option.label
    heading = f"── {label} " + "─" * max(0, width - 4 - len(label))
    print(_c(stream, heading, _ANSI_GREY_DARK), file=stream)
    print(file=stream)
    for line in option.lines:
        if line.speaker.lower() == "player":
            _print_dialog_turn(stream, "You", _ANSI_BOLD, line.text, tempo)
        elif line.speaker == npc.name:
            _print_dialog_turn(stream, npc.name, npc_colour, line.text, tempo)
        else:
            _print_dialog_turn(stream, line.speaker or "—", _ANSI_GREY_DARK, line.text, tempo)


# ---------------------------------------------------------------------------
# Screens
# ---------------------------------------------------------------------------


@dataclass
class GameConfig:
    demo_dir: Path
    tempo: float = 0.2
    stream_in: TextIO = field(default_factory=lambda: sys.stdin)
    stream_out: TextIO = field(default_factory=lambda: sys.stdout)


def _draw_quest_strip(
    stream: TextIO,
    cfg: CluesConfig | None,
    state: GameState,
) -> None:
    """One-line banner showing quest progress on the tavern menu."""
    if cfg is None or not cfg.clues:
        return
    total = len(cfg.clues)
    got = len(state.unlocked_clues)
    progress = "●" * got + "○" * (total - got)
    name = cfg.quest.name if cfg.quest else "Quest"
    next_threshold = min(
        (r.min_clues for r in cfg.resolutions if r.min_clues > got),
        default=None,
    )
    tail = ""
    if next_threshold is not None:
        tail = _c(stream, f"   (next resolution at {next_threshold})", _ANSI_DIM)
    elif cfg.resolutions:
        tail = _c(stream, "   (you can Resolve)", _ANSI_GREEN)
    print(
        f"  {_c(stream, name, _ANSI_BOLD)}   "
        f"{_c(stream, progress, _ANSI_CYAN)}   "
        f"{_c(stream, f'{got}/{total} clues', _ANSI_DIM)}"
        f"{tail}",
        file=stream,
    )
    print(file=stream)


def _show_clue_log(
    stream_in: TextIO,
    stream_out: TextIO,
    cfg: CluesConfig,
    state: GameState,
) -> None:
    """Render the accumulated clues for the player to review."""
    _clear(stream_out)
    name = cfg.quest.name if cfg.quest else "Clue Log"
    _box_header(stream_out, f"Clue Log — {name}", "")
    print(file=stream_out)
    if not state.unlocked_clues:
        print(
            _c(
                stream_out,
                "  No clues yet. Talk to the guests.",
                _ANSI_DIM,
            ),
            file=stream_out,
        )
    else:
        for idx, clue in enumerate(cfg.clues, start=1):
            if clue.id not in state.unlocked_clues:
                continue
            print(
                f"  {_c(stream_out, str(idx), _ANSI_BOLD)}. "
                f"{_c(stream_out, clue.id, _ANSI_CYAN)}",
                file=stream_out,
            )
            for line in textwrap.wrap(clue.log.strip(), width=_term_width(stream_out) - 8):
                print(f"      {line}", file=stream_out)
            print(file=stream_out)
    _press_enter(stream_in, stream_out, "press Enter to return")


def _show_resolution_menu(
    stream_in: TextIO,
    stream_out: TextIO,
    cfg: CluesConfig,
    state: GameState,
) -> bool:
    """Present resolutions the player qualifies for. Returns True when chosen."""
    _clear(stream_out)
    name = cfg.quest.name if cfg.quest else "Resolve"
    _box_header(
        stream_out,
        f"Resolve — {name}",
        (
            f"You have unlocked {len(state.unlocked_clues)} of {len(cfg.clues)} clues. "
            "Choose how the night ends."
        ),
    )
    print(file=stream_out)
    available = cfg.available_resolutions(len(state.unlocked_clues))
    if not available:
        print(
            _c(
                stream_out,
                "  Not enough evidence yet. Gather more clues.",
                _ANSI_DIM,
            ),
            file=stream_out,
        )
        _press_enter(stream_in, stream_out, "press Enter to return")
        return False
    choices = [
        f"{_c(stream_out, r.label, _ANSI_BOLD)}  "
        f"{_c(stream_out, f'(min {r.min_clues} clues)', _ANSI_DIM)}"
        for r in available
    ] + [_c(stream_out, "step back — I'm not ready", _ANSI_DIM)]
    pick = _pick(
        stream_in,
        stream_out,
        "▸",
        choices,
        back_label="b",
        hints=[
            ("1-" + str(len(available)), "choose"),
            ("b", "step back"),
        ],
    )
    if pick is None or pick == len(available):
        return False
    chosen = available[pick]
    state.ending = chosen.ending

    _clear(stream_out)
    _box_header(
        stream_out,
        _c(stream_out, chosen.label, _ANSI_GREEN),
        chosen.id,
    )
    print(file=stream_out)
    for line in textwrap.wrap(
        chosen.outcome.strip(), width=_term_width(stream_out) - 4
    ):
        print(f"  {_c(stream_out, line, _ANSI_ITALIC)}", file=stream_out)
    print(file=stream_out)
    _press_enter(stream_in, stream_out, "press Enter to leave the tavern")
    return True


def _tavern_title_and_mood(demo_dir: Path) -> tuple[str, str]:
    """Best-effort reading of a project name + mood line from lore/*.md."""
    lore_dir = demo_dir / "lore"
    mood = "Smoke, sour ale, low voices. Someone at the bar has already decided what face to show you."
    title = demo_dir.name.replace("_", " ").title()
    if lore_dir.is_dir():
        for path in sorted(lore_dir.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            first_heading = next(
                (l.lstrip("# ").strip() for l in text.splitlines() if l.startswith("#")),
                None,
            )
            if first_heading:
                title = first_heading
                break
    return title, mood


def _draw_tavern_scene(
    stream: TextIO,
    title: str,
    mood: str,
) -> None:
    _clear(stream)
    _box_header(stream, title, mood)
    print(file=stream)


def _draw_conversation_header(
    stream: TextIO, npc: NpcSheet, colour: str, standing: Standing, score: float
) -> None:
    _clear(stream)
    sigil = _npc_sigil(npc)
    name_line = f"{sigil}  {npc.name}"
    _box_header(stream, _c(stream, name_line, colour), npc.role)
    summary = (
        f"  {_c(stream, 'standing', _ANSI_DIM)}   "
        f"{_c(stream, standing.label, _ANSI_CYAN):<16s}  "
        f"{_dispo_bar(stream, score)}  "
        f"{_score_text(stream, score)}"
    )
    print(summary, file=stream)
    if standing.description:
        print(
            _c(stream, f"  {standing.description}", _ANSI_GREY),
            file=stream,
        )
    print(file=stream)


# ---------------------------------------------------------------------------
# Menu builders
# ---------------------------------------------------------------------------


def _eligible_intents(
    npc: NpcSheet,
    all_intents: list[PlayerIntent],
    branches: dict[str, YarnOption],
) -> list[PlayerIntent]:
    allowed = set(npc.allowed_intents) if npc.allowed_intents else {i.id for i in all_intents}
    available = [i for i in all_intents if i.id in allowed and i.id in branches]
    if npc.allowed_intents:
        order = {iid: pos for pos, iid in enumerate(npc.allowed_intents)}
        available.sort(key=lambda i: order.get(i.id, 9999))
    return available


def _format_intent_choice(stream: TextIO, intent: PlayerIntent, played: bool) -> str:
    tone = _intent_tone(intent.id)
    tag = ""
    if tone is not None:
        label, code = tone
        tag = "  " + _c(stream, label, code)
    played_mark = _c(stream, "·", _ANSI_DIM) if played else " "
    return (
        f"{played_mark}  "
        f"{_c(stream, intent.name, _ANSI_BOLD):<32s}"
        f"{tag}"
    )


def _format_npc_choice(stream: TextIO, npc: NpcSheet, state: GameState, idx: int) -> str:
    """Render one row of the approach menu with visual-width-correct padding.

    Python's ``:<N`` format-spec counts ANSI bytes, so we pad the plain
    string to the target visible width, then wrap with colour.
    """
    score = state.score_for(npc.id)
    standing = resolve_standing(npc, score)
    sigil = _npc_sigil(npc)
    colour = _npc_colour(idx)
    visited = "●" if npc.id in state.visits else " "
    raw_name = f"{npc.name}"
    name_padded = f"{raw_name:<26s}"
    raw_role = npc.role[:36]
    role_padded = f"{raw_role:<38s}"
    raw_standing = standing.label
    standing_padded = f"{raw_standing:<14s}"
    return (
        f"{_c(stream, visited, _ANSI_DIM)} "
        f"{_c(stream, sigil, colour)}  "
        f"{_c(stream, name_padded, _ANSI_BOLD)}"
        f"{_c(stream, role_padded, _ANSI_DIM)}"
        f"{_c(stream, standing_padded, _ANSI_CYAN)}"
        f"{_dispo_bar(stream, score)} {_score_text(stream, score)}"
    )


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def _summary(
    state: GameState,
    npcs: list[NpcSheet],
    stream: TextIO,
    clues_cfg: CluesConfig | None = None,
) -> None:
    _clear(stream)
    if state.ending:
        tag = _c(stream, f"ending: {state.ending}", _ANSI_GREEN)
    else:
        tag = f"{state.turn_count} conversation{'s' if state.turn_count != 1 else ''} this evening."
    _box_header(stream, "Walking out", tag)
    print(file=stream)
    for idx, npc in enumerate(npcs):
        score = state.score_for(npc.id)
        standing = resolve_standing(npc, score)
        visits = state.visits.get(npc.id, 0)
        unlocked = state.unlocked_knowledge.get(npc.id, set())
        colour = _npc_colour(idx)
        sigil = _npc_sigil(npc)
        print(
            f"  {_c(stream, sigil, colour)}  "
            f"{_c(stream, npc.name, _ANSI_BOLD):<26s}  "
            f"{_c(stream, standing.label, _ANSI_CYAN):<14s}  "
            f"{_dispo_bar(stream, score)} {_score_text(stream, score)}  "
            f"{_c(stream, f'{visits} visit' + ('' if visits == 1 else 's'), _ANSI_DIM)}",
            file=stream,
        )
        if unlocked:
            print(
                _c(stream, f"      unlocked: {', '.join(sorted(unlocked))}", _ANSI_GREEN),
                file=stream,
            )
    if clues_cfg and clues_cfg.clues:
        print(file=stream)
        print(
            _c(
                stream,
                f"  clues recovered: {len(state.unlocked_clues)}/{len(clues_cfg.clues)}",
                _ANSI_CYAN,
            ),
            file=stream,
        )
    print(file=stream)
    print(_c(stream, "  The lantern swings behind you.", _ANSI_GREY), file=stream)
    print(file=stream)


def run_game(config: GameConfig) -> int:
    stream_in, stream_out = config.stream_in, config.stream_out
    demo_dir = config.demo_dir

    if not (demo_dir / "characters.yaml").exists():
        print(
            f"error: {demo_dir}/characters.yaml not found. "
            "Point --demo-dir at an npcforge project.",
            file=sys.stderr,
        )
        return 2

    npcs = load_npcs(demo_dir / "characters.yaml")
    intents_path = demo_dir / "player_intents.yaml"
    intents = load_intents(intents_path) if intents_path.exists() else []
    label_to_id = _intent_label_to_id_map(intents)

    branches_by_npc: dict[str, dict[str, YarnOption]] = {
        npc.id: load_npc_branches(demo_dir, npc, label_to_id) for npc in npcs
    }

    missing = [npc.id for npc in npcs if not branches_by_npc.get(npc.id)]
    if missing:
        print(
            _c(
                stream_out,
                "  note: no walk-up Yarn for: "
                + ", ".join(missing)
                + f"  (run: npcforge build --demo-dir {demo_dir} --mode walk_up)",
                _ANSI_GREY_DARK,
            ),
            file=stream_out,
        )
        print(file=stream_out)

    state = GameState()
    title, mood = _tavern_title_and_mood(demo_dir)
    clues_cfg = _load_clues(demo_dir)

    # Render the quest brief once on entry.
    if clues_cfg and clues_cfg.quest:
        _clear(stream_out)
        _box_header(
            stream_out,
            f"Quest: {clues_cfg.quest.name}",
            clues_cfg.quest.player_brief.strip(),
        )
        print(file=stream_out)
        print(
            _c(
                stream_out,
                "  Gather clues by talking. When you have enough, the "
                "Resolve option will appear on the tavern menu.",
                _ANSI_DIM,
            ),
            file=stream_out,
        )
        _press_enter(stream_in, stream_out, "press Enter to enter the tavern")

    while True:
        _draw_tavern_scene(stream_out, title, mood)
        _draw_quest_strip(stream_out, clues_cfg, state)
        print(_c(stream_out, "  Who do you approach?", _ANSI_BOLD), file=stream_out)
        print(file=stream_out)

        town_choices = [
            _format_npc_choice(stream_out, n, state, i) for i, n in enumerate(npcs)
        ]
        extra_actions: list[tuple[str, object]] = []
        if clues_cfg and clues_cfg.clues:
            extra_actions.append(
                ("clue_log", _c(stream_out, "review the clue log", _ANSI_CYAN))
            )
            # Only surface the Resolve affordance once the player has actually
            # started gathering evidence — before that, "walk out into the
            # night" is the canonical abandon and a Resolve menu showing only
            # a walk-away option is just noise.
            available = (
                clues_cfg.available_resolutions(len(state.unlocked_clues))
                if state.ending is None and state.unlocked_clues
                else []
            )
            if available:
                extra_actions.append(
                    (
                        "resolve",
                        _c(
                            stream_out,
                            f"RESOLVE — {clues_cfg.quest.name if clues_cfg.quest else 'the quest'}",
                            _ANSI_GREEN,
                        ),
                    )
                )
        extra_actions.append(("leave", _c(stream_out, "walk out into the night", _ANSI_DIM)))

        pick = _pick(
            stream_in,
            stream_out,
            "▸",
            town_choices + [label for _, label in extra_actions],
            back_label=None,
            hints=[("1-" + str(len(town_choices)), "approach"), ("q", "leave")],
        )
        if pick is None:
            break
        if pick >= len(town_choices):
            action_tag = extra_actions[pick - len(town_choices)][0]
            if action_tag == "leave":
                break
            if action_tag == "clue_log" and clues_cfg:
                _show_clue_log(stream_in, stream_out, clues_cfg, state)
                continue
            if action_tag == "resolve" and clues_cfg:
                ended = _show_resolution_menu(
                    stream_in, stream_out, clues_cfg, state
                )
                if ended:
                    break
                continue

        idx = pick
        npc = npcs[idx]
        npc_colour = _npc_colour(idx)
        branches = branches_by_npc.get(npc.id, {})

        while True:
            score = state.score_for(npc.id)
            standing = resolve_standing(npc, score)
            _draw_conversation_header(stream_out, npc, npc_colour, standing, score)

            eligible = _eligible_intents(npc, intents, branches)
            if not eligible:
                print(
                    _c(
                        stream_out,
                        f"  {npc.name} has nothing to say tonight.",
                        _ANSI_GREY,
                    ),
                    file=stream_out,
                )
                _press_enter(stream_in, stream_out, "press Enter to step back")
                break

            print(_c(stream_out, "  How do you open?", _ANSI_BOLD), file=stream_out)
            print(file=stream_out)
            played = state.played_branches.get(npc.id, set())
            pick_intent = _pick(
                stream_in,
                stream_out,
                "▸",
                [_format_intent_choice(stream_out, intent, intent.id in played) for intent in eligible]
                + [_c(stream_out, "step back", _ANSI_DIM)],
                back_label="b",
                hints=[("1-" + str(len(eligible)), "speak"), ("b", "step back"), ("q", "walk out")],
            )
            if pick_intent is None or pick_intent == len(eligible):
                break

            intent = eligible[pick_intent]
            option = branches[intent.id]

            _clear(stream_out)
            _box_header(
                stream_out,
                _c(stream_out, f"{_npc_sigil(npc)}  {npc.name}", npc_colour),
                f"intent: {intent.name}",
            )
            print(file=stream_out)
            _play_branch(stream_out, npc, npc_colour, option, config.tempo)
            _press_enter(stream_in, stream_out, "press Enter")

            before = state.score_for(npc.id)
            after = state.apply(npc.id, intent.id)
            delta = after - before
            before_standing = resolve_standing(npc, before)
            after_standing = resolve_standing(npc, after)

            print(file=stream_out)
            reaction = _reaction_line(delta, seed=hash((npc.id, intent.id)) % 2**31)
            if reaction:
                print(_c(stream_out, f"  {reaction}", _ANSI_ITALIC + _ANSI_GREY), file=stream_out)
                print(file=stream_out)

            print(
                f"  {_c(stream_out, 'δ', _ANSI_DIM)} {_score_text(stream_out, delta)}   "
                f"{_c(stream_out, 'score', _ANSI_DIM)} {_score_text(stream_out, after)}   "
                f"{_c(stream_out, 'dispo', _ANSI_DIM)} {_dispo_bar(stream_out, after)}",
                file=stream_out,
            )
            if after_standing.label != before_standing.label:
                direction = "→" if delta >= 0 else "↓"
                colour_code = _ANSI_GREEN if delta >= 0 else _ANSI_RED
                print(
                    f"  {_c(stream_out, 'standing', _ANSI_DIM)}  "
                    f"{before_standing.label}  "
                    f"{_c(stream_out, direction, colour_code)}  "
                    f"{_c(stream_out, after_standing.label, colour_code)}",
                    file=stream_out,
                )

            newly = set(after_standing.unlocks_knowledge) - state.unlocked_knowledge.get(npc.id, set())
            if newly:
                state.unlocked_knowledge.setdefault(npc.id, set()).update(newly)
                print(
                    _c(
                        stream_out,
                        f"\n  ∗ new knowledge: {', '.join(sorted(newly))}",
                        _ANSI_GREEN,
                    ),
                    file=stream_out,
                )

            # Quest: unlock any clues gated on this (npc, intent).
            if clues_cfg is not None:
                gained = [
                    c
                    for c in clues_cfg.by_gate(npc.id, intent.id)
                    if c.id not in state.unlocked_clues
                ]
                for clue in gained:
                    state.unlocked_clues.add(clue.id)
                    print(file=stream_out)
                    print(
                        _c(
                            stream_out,
                            f"  ✦ clue found — {clue.id}",
                            _ANSI_GREEN + _ANSI_BOLD,
                        ),
                        file=stream_out,
                    )
                    if clue.flash:
                        for line in textwrap.wrap(
                            clue.flash.strip(), width=_term_width(stream_out) - 6
                        ):
                            print(
                                _c(stream_out, f"    {line}", _ANSI_ITALIC + _ANSI_GREEN),
                                file=stream_out,
                            )

            _press_enter(stream_in, stream_out, "press Enter to continue")

    _summary(state, npcs, stream_out, clues_cfg)
    return 0
