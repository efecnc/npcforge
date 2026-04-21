"""Minimal CLI tavern loop + optional GIF recording (Pillow).

Play a tiny npcforge project (pre-built ``out/*.yarn``) like a visual-novel
stub: choose NPC from ``world.yarn``, choose an intent, read the branch.
Optionally record each screen as a frame in an animated GIF.

Offline demo::

    npcforge tape-game --demo-dir examples/tape_game --gif playthrough.gif \\
        --auto-turns 6

Longer Night City quest + scripted GIF::

    npcforge tape-game --demo-dir examples/night_city_game \\
        --follow-quest --gif night_city_run.gif --frame-ms 900

Interactive::

    npcforge tape-game --demo-dir examples/tape_game --gif session.gif

Requires Pillow for ``--gif``::

    pip install 'npcforge[tape]'
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

import yaml
from pydantic import BaseModel, Field

from .play import YarnNode, parse_yarn
from .schemas import NpcSheet, PlayerIntent, load_intents, load_npcs, load_world_bible
from .schemas import resolve_intents_for_npc


@dataclass
class TapeSessionConfig:
    demo_dir: Path
    gif_path: Path | None = None
    """Write animated GIF here when set (requires Pillow)."""

    auto_turns: int = 0
    """If > 0, pick NPCs and intents automatically (no stdin)."""

    follow_quest: bool = False
    """When True, play ``tape_auto.yaml`` beats in order (best for quest GIFs)."""

    frame_ms: int = 750
    """Delay between GIF frames (whole GIF uses one duration per frame)."""

    regenerate: bool = False
    """When True, run ``build_pipeline`` walk_up before play (needs API key)."""

    provider: str = "gemini"
    model: str | None = None
    api_key_env: str | None = None

    stream_out: TextIO = sys.stdout
    stream_in: TextIO = sys.stdin

    width: int = 80
    height: int = 52
    """GIF / layout grid; long screens paginate into multiple GIF frames."""


# ---------------------------------------------------------------------------
# Optional tape quest (tape_quest.yaml beside characters.yaml)
# ---------------------------------------------------------------------------


class TapeGate(BaseModel):
    npc_id: str
    intent_id: str


class TapeMilestone(BaseModel):
    """Linear beat; optional gate unlocks this row after the previous."""

    summary: str
    gate: TapeGate | None = None


class TapeQuestFile(BaseModel):
    title: str
    objective: str = ""
    milestones: list[TapeMilestone] = Field(default_factory=list)


def load_tape_quest(path: Path) -> TapeQuestFile | None:
    if not path.exists():
        return None
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict) or not raw.get("title"):
        return None
    return TapeQuestFile.model_validate(raw)


def _load_hub_title(chars_yaml: Path) -> str:
    raw = yaml.safe_load(chars_yaml.read_text(encoding="utf-8")) or {}
    w = raw.get("world")
    if isinstance(w, str) and w.strip():
        t = w.strip()
        return (t[:56] + "…").upper() if len(t) > 56 else t.upper()
    return "TAPE SESSION"


def load_tape_auto_script(path: Path) -> list[tuple[str, str]]:
    """Return list of (npc_id, intent_id) from ``tape_auto.yaml``."""
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    beats = raw.get("beats") or []
    out: list[tuple[str, str]] = []
    if not isinstance(beats, list):
        return out
    for b in beats:
        if not isinstance(b, dict):
            continue
        nid = b.get("npc_id")
        iid = b.get("intent_id")
        if isinstance(nid, str) and isinstance(iid, str):
            out.append((nid.strip(), iid.strip()))
    return out


def _arrival_index_for_npc(
    start: YarnNode, npc_id: str, npcs: list[NpcSheet]
) -> int:
    for i, opt in enumerate(start.options):
        if _npc_id_from_start_label(opt.label, npcs) == npc_id:
            return i + 1
    return 1


def _intent_index_for(npc: NpcSheet, intent_id: str, intents_all: list[PlayerIntent]) -> int:
    resolved = resolve_intents_for_npc(npc, intents_all)
    for i, it in enumerate(resolved):
        if it.id == intent_id:
            return i + 1
    return 1


@dataclass
class TapeQuestRuntime:
    spec: TapeQuestFile
    progress: int = 0  # highest unlocked milestone index (0 = intro)

    def try_advance(self, npc_id: str, intent_id: str) -> bool:
        nxt = self.progress + 1
        ms = self.spec.milestones
        if nxt >= len(ms):
            return False
        g = ms[nxt].gate
        if g is None:
            return False
        if g.npc_id == npc_id and g.intent_id == intent_id:
            self.progress = nxt
            return True
        return False

    def footer(self, *, width: int) -> list[str]:
        ms = self.spec.milestones
        if not ms:
            return []
        w = max(20, int(width))
        cur = ms[min(self.progress, len(ms) - 1)].summary
        last_i = len(ms) - 1
        lines = ["", "─" * w, f"QUEST: {self.spec.title}"]
        if self.spec.objective:
            obj = " ".join(self.spec.objective.split())
            lines.append(f"Objective: {obj}")
        lines.append(f"Progress: {self.progress}/{last_i}")
        # Full text; frame layout wraps/paginates for GIF and terminal.
        lines.append(f"Latest: {cur.strip()}")
        if self.progress >= last_i:
            lines.append(">> Case closed — burn this copy after viewing.")
        return lines


def _pad_screen(lines: list[str], *, width: int, height: int) -> list[str]:
    out: list[str] = []
    for row in range(height):
        if row < len(lines):
            s = lines[row].replace("\t", "    ")
            out.append(s[:width].ljust(width))
        else:
            out.append(" " * width)
    return out


def _is_rule_line(line: str) -> bool:
    s = line.strip()
    if len(s) < 3:
        return False
    return len(set(s)) == 1 and s[0] in "=-─"


def _wrap_words(paragraph: str, width: int) -> list[str]:
    """Greedy word-wrap; breaks overlong tokens."""
    if width < 8:
        width = 8
    p = paragraph.rstrip("\n")
    if not p:
        return [""]
    out: list[str] = []
    for raw_word in p.split():
        word = raw_word
        while len(word) > width:
            out.append(word[:width])
            word = word[width:]
        if not word:
            continue
        if not out:
            out.append(word)
            continue
        if len(out[-1]) + 1 + len(word) <= width:
            out[-1] = f"{out[-1]} {word}"
        else:
            out.append(word)
    return out if out else [""]


def _wrap_block_lines(lines: list[str], width: int) -> list[str]:
    """Wrap each logical line to ``width`` (rule lines are truncated, not wrapped)."""
    w = max(8, int(width))
    expanded: list[str] = []
    for line in lines:
        if len(line) <= w:
            expanded.append(line)
            continue
        if _is_rule_line(line):
            expanded.append(line[:w])
            continue
        expanded.extend(_wrap_words(line, w))
    return expanded


def _lines_for_option(node: YarnNode, intent: PlayerIntent) -> list[str]:
    target = intent.name.strip().lower()
    match: YarnOption | None = None
    for opt in node.options:
        if opt.label.strip().lower() == target:
            match = opt
            break
    if match is None:
        for opt in node.options:
            if target in opt.label.strip().lower():
                match = opt
                break
    if match is None:
        return [f"(no branch for intent {intent.name!r} in {node.title})"]
    lines: list[str] = [f"── {node.title} :: [{match.label}] ──"]
    for yl in match.lines:
        if yl.speaker:
            lines.append(f"{yl.speaker}: {yl.text}")
        else:
            lines.append(yl.text)
    if match.jump_to:
        lines.append(f"(→ {match.jump_to})")
    return lines


def _npc_id_from_start_label(label: str, npcs: list[NpcSheet]) -> str | None:
    head = label.split("—", 1)[0].strip()
    low = head.lower()
    for n in npcs:
        if n.name.strip().lower() == low:
            return n.id
    for n in npcs:
        if low in n.name.lower() or n.name.lower() in low:
            return n.id
    return None


class GifRecorder:
    """Capture fixed-size text screens as GIF frames."""

    def __init__(self, *, width: int, height: int, cell_w: int = 9, cell_h: int = 18) -> None:
        self._width = width
        self._height = height
        self._cell_w = cell_w
        self._cell_h = cell_h
        self._frames: list[object] = []
        pil = self._pil()
        if pil is None:
            raise RuntimeError(
                "Pillow is required for GIF export. Install with: pip install 'npcforge[tape]'"
            )
        self._Image, self._ImageDraw, self._ImageFontMod = pil

    @staticmethod
    def _pil():
        try:
            from PIL import Image, ImageDraw, ImageFont

            return Image, ImageDraw, ImageFont
        except ImportError:
            return None

    def _font(self):
        IF = self._ImageFontMod
        paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "/Library/Fonts/Menlo.ttc",
            "/System/Library/Fonts/Supplemental/Courier New.ttf",
            "C:\\Windows\\Fonts\\consola.ttf",
        ]
        for p in paths:
            if Path(p).exists():
                try:
                    return IF.truetype(p, 14)
                except OSError:
                    continue
        return IF.load_default()

    def snapshot(self, screen_lines: list[str]) -> None:
        """One logical screen may become several GIF pages if taller than ``height``."""
        n = len(screen_lines)
        if n == 0:
            screen_lines = [""]
            n = 1
        i = 0
        while i < n:
            chunk = screen_lines[i : i + self._height]
            i += self._height
            pad = _pad_screen(chunk, width=self._width, height=self._height)
            px_w = 16 + self._width * self._cell_w
            px_h = 16 + self._height * self._cell_h
            img = self._Image.new("RGB", (px_w, px_h), (14, 16, 22))
            draw = self._ImageDraw.Draw(img)
            font = self._font()
            y = 12
            for row in pad:
                draw.text((12, y), row, fill=(210, 215, 225), font=font)
                y += self._cell_h
            self._frames.append(img)

    def save(self, path: Path, *, duration_ms: int) -> None:
        if not self._frames:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        first, *rest = self._frames
        first.save(
            path,
            save_all=True,
            append_images=rest,
            duration=duration_ms,
            loop=0,
            optimize=False,
        )


def _print_block(lines: list[str], *, stream: TextIO) -> None:
    for ln in lines:
        print(ln, file=stream)


async def _maybe_regenerate(cfg: TapeSessionConfig) -> None:
    if not cfg.regenerate:
        return
    env = cfg.api_key_env or (
        "GEMINI_API_KEY"
        if cfg.provider == "gemini"
        else "OPENAI_API_KEY"
        if cfg.provider == "openai"
        else "GEMINI_API_KEY"
    )
    key = os.environ.get(env or "GEMINI_API_KEY", "")
    if not key:
        raise SystemExit(
            f"Missing API key for --regenerate. Set {env} or pass --api-key-env."
        )
    from .tools import BuildPipelineInput, build_pipeline

    prov = cfg.provider
    if prov not in ("gemini", "openai", "deepseek", "openrouter", "local"):
        prov = "gemini"
    await build_pipeline(
        BuildPipelineInput(
            demo_dir=cfg.demo_dir,
            mode="walk_up",
            api_key=key,
            provider=prov,  # type: ignore[arg-type]
            model=cfg.model,
        )
    )


def _load_walk_node(demo_dir: Path, npc_id: str) -> YarnNode | None:
    path = demo_dir / "out" / f"{npc_id}.yarn"
    if not path.exists():
        return None
    nodes = parse_yarn(path.read_text(encoding="utf-8"))
    for n in nodes:
        if n.title.strip() == npc_id:
            return n
    return nodes[0] if nodes else None


def _load_start_node(demo_dir: Path) -> YarnNode | None:
    path = demo_dir / "out" / "world.yarn"
    if not path.exists():
        return None
    nodes = parse_yarn(path.read_text(encoding="utf-8"))
    for n in nodes:
        if n.title.strip().lower() == "start":
            return n
    return nodes[0] if nodes else None


async def run_tape_session(cfg: TapeSessionConfig) -> int:
    await _maybe_regenerate(cfg)

    npcs = load_npcs(cfg.demo_dir / "characters.yaml")
    intents_all = load_intents(cfg.demo_dir / "player_intents.yaml")
    _lore = load_world_bible(cfg.demo_dir / "lore")

    start = _load_start_node(cfg.demo_dir)
    if start is None:
        print("No world.yarn Start node found under demo_dir/out/", file=sys.stderr)
        return 1

    hub_title = _load_hub_title(cfg.demo_dir / "characters.yaml")
    quest_spec = load_tape_quest(cfg.demo_dir / "tape_quest.yaml")
    quest_rt: TapeQuestRuntime | None = (
        TapeQuestRuntime(spec=quest_spec) if quest_spec else None
    )

    recorder: GifRecorder | None = None
    if cfg.gif_path is not None:
        recorder = GifRecorder(width=cfg.width, height=cfg.height)

    auto_plays = cfg.auto_turns

    def frame(title: str, body: list[str]) -> None:
        w = max(20, int(cfg.width))
        body_lines = list(body)
        if quest_rt:
            body_lines.extend(quest_rt.footer(width=w))
        raw = [
            "=" * w,
            title[: w - 2].center(w),
            "=" * w,
            "",
            *body_lines,
            "",
            "-" * w,
        ]
        screen = _wrap_block_lines(raw, w)
        _print_block(screen, stream=cfg.stream_out)
        if recorder:
            recorder.snapshot(screen)

    def one_round(arrival_pick: int, intent_pick: int) -> bool:
        """Return False if choices invalid."""
        pre = [ln.text for ln in start.preamble if ln.text.strip()]
        opts = start.options
        opt_labels = [o.label for o in opts]
        body = [*pre, "", "Who do you approach?"]
        for i, lab in enumerate(opt_labels, 1):
            body.append(f"  [{i}] {lab}")
        frame(hub_title, body)

        if not opts:
            return False
        choice = arrival_pick
        if choice < 1 or choice > len(opts):
            print("Invalid NPC choice.", file=cfg.stream_out)
            return False

        npc_id = _npc_id_from_start_label(opt_labels[choice - 1], npcs)
        if not npc_id:
            print("Could not map that option to an NPC id.", file=cfg.stream_out)
            return False

        npc = next((n for n in npcs if n.id == npc_id), None)
        if npc is None:
            print("NPC not in cast.", file=cfg.stream_out)
            return False

        node = _load_walk_node(cfg.demo_dir, npc_id)
        if node is None:
            print(f"Missing out/{npc_id}.yarn", file=cfg.stream_out)
            return False

        resolved = resolve_intents_for_npc(npc, intents_all)
        if not resolved:
            print("No intents for this NPC.", file=cfg.stream_out)
            return False

        pre2 = [ln.text for ln in node.preamble if ln.text.strip()]
        body2 = [
            f"Speaking with {npc.name}.",
            "",
            *(pre2 or ["(They wait.)"]),
            "",
            "Choose an approach:",
        ]
        for i, it in enumerate(resolved, 1):
            body2.append(f"  [{i}] {it.name}")
        frame(npc.name.upper(), body2)

        ichoice = intent_pick
        if ichoice < 1 or ichoice > len(resolved):
            print("Invalid intent.", file=cfg.stream_out)
            return False

        intent = resolved[ichoice - 1]
        branch_lines = _lines_for_option(node, intent)
        frame(f"{npc.name.upper()} — {intent.name}", branch_lines)
        if quest_rt:
            quest_rt.try_advance(npc.id, intent.id)
        return True

    if cfg.follow_quest:
        script = load_tape_auto_script(cfg.demo_dir / "tape_auto.yaml")
        if not script:
            print(
                "tape_auto.yaml is missing or has no beats; "
                "it is required with --follow-quest.",
                file=sys.stderr,
            )
            return 1
        for nid, iid in script:
            npcx = next((n for n in npcs if n.id == nid), None)
            if npcx is None:
                print(f"Unknown npc_id in tape_auto.yaml: {nid}", file=sys.stderr)
                continue
            ap = _arrival_index_for_npc(start, nid, npcs)
            ip = _intent_index_for(npcx, iid, intents_all)
            one_round(ap, ip)
    elif auto_plays > 0:
        n_opt = max(len(start.options), 1)
        for k in range(auto_plays):
            arrival_pick = (k % n_opt) + 1
            lab = start.options[arrival_pick - 1].label
            npc_guess = _npc_id_from_start_label(lab, npcs)
            if not npc_guess:
                continue
            npc_obj = next((n for n in npcs if n.id == npc_guess), npcs[0])
            resolved_n = resolve_intents_for_npc(npc_obj, intents_all)
            n_int = max(len(resolved_n), 1)
            intent_pick = (k % n_int) + 1
            one_round(arrival_pick, intent_pick)
    else:
        while True:
            pre = [ln.text for ln in start.preamble if ln.text.strip()]
            opts = start.options
            opt_labels = [o.label for o in opts]
            body = [*pre, "", "Who do you approach?"]
            for i, lab in enumerate(opt_labels, 1):
                body.append(f"  [{i}] {lab}")
            frame(hub_title, body)

            raw = cfg.stream_in.readline()
            if not raw:
                break
            m = re.match(r"\s*(\d+)\s*", raw)
            if not m:
                print("Pick a number, or Ctrl-D to quit.", file=cfg.stream_out)
                continue
            choice = int(m.group(1))
            if not opts or choice < 1 or choice > len(opts):
                print("Invalid choice.", file=cfg.stream_out)
                continue

            npc_id = _npc_id_from_start_label(opt_labels[choice - 1], npcs)
            if not npc_id:
                print("Could not map that option to an NPC id.", file=cfg.stream_out)
                continue
            npc = next((n for n in npcs if n.id == npc_id), None)
            if npc is None:
                continue
            node = _load_walk_node(cfg.demo_dir, npc_id)
            if node is None:
                continue
            resolved = resolve_intents_for_npc(npc, intents_all)
            if not resolved:
                continue

            pre2 = [ln.text for ln in node.preamble if ln.text.strip()]
            body2 = [
                f"Speaking with {npc.name}.",
                "",
                *(pre2 or ["(They wait.)"]),
                "",
                "Choose an approach:",
            ]
            for i, it in enumerate(resolved, 1):
                body2.append(f"  [{i}] {it.name}")
            frame(npc.name.upper(), body2)

            raw2 = cfg.stream_in.readline()
            if not raw2:
                break
            m2 = re.match(r"\s*(\d+)\s*", raw2)
            if not m2:
                print("Pick a number.", file=cfg.stream_out)
                continue
            ichoice = int(m2.group(1))
            if ichoice < 1 or ichoice > len(resolved):
                print("Invalid intent.", file=cfg.stream_out)
                continue

            intent = resolved[ichoice - 1]
            branch_lines = _lines_for_option(node, intent)
            frame(f"{npc.name.upper()} — {intent.name}", branch_lines)
            if quest_rt:
                quest_rt.try_advance(npc.id, intent.id)

            print("(Enter for main room)", file=cfg.stream_out)
            cfg.stream_in.readline()

    if recorder and cfg.gif_path:
        recorder.save(cfg.gif_path, duration_ms=cfg.frame_ms)
        print(f"GIF written: {cfg.gif_path}", file=cfg.stream_out)

    _ = _lore
    return 0
