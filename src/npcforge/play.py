"""Terminal playback for generated Yarn files.

A writer can now read one NPC's dialogue at speaking pace without opening
a YAML editor:

    npcforge play --demo-dir my_game --npc mira_vesser
    npcforge play --demo-dir my_game --npc mira_vesser --intent threaten_for_info
    npcforge play --demo-dir my_game --npc mira_vesser --bark greet_patron

The parser intentionally handles only the subset of Yarn Spinner 2 syntax
that :mod:`npcforge.yarn` emits. It is *not* a full Yarn interpreter — it
knows about ``title:`` headers, ``->`` option lines, dialogue lines in
``Speaker: text`` form, ``<<jump ...>>``, and the ``<<if visited_count(...)
% N == I>>`` rotation barks use. Any other Yarn directive is ignored with
a note.
"""

from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path


_TITLE_RE = re.compile(r"^title:\s*(.+?)\s*$")
_TAGS_RE = re.compile(r"^tags:\s*(.+?)\s*$")
_OPTION_RE = re.compile(r"^->\s*\[(.+?)\]\s*$")
_BARE_OPTION_RE = re.compile(r"^->\s*(.+?)\s*$")
_JUMP_RE = re.compile(r"^\s*<<jump\s+([^>\s]+)>>\s*$")
_IF_COUNTER_RE = re.compile(
    r"^<<(?:else)?if\s+visited_count\(\s*\"(?P<node>[^\"]+)\"\s*\)\s*%\s*(?P<mod>\d+)\s*==\s*(?P<idx>\d+)\s*>>"
)
_ELSE_RE = re.compile(r"^<<else>>\s*$")
_ENDIF_RE = re.compile(r"^<<endif>>\s*$")
_SPEAKER_LINE_RE = re.compile(r"^(?P<speaker>[^:/][^:]*?):\s*(?P<text>.+?)\s*$")


@dataclass
class YarnLine:
    """One dialogue turn inside a node or option body."""

    speaker: str
    text: str


@dataclass
class YarnOption:
    """One ``-> [label]`` block inside a node."""

    label: str
    lines: list[YarnLine] = field(default_factory=list)
    jump_to: str | None = None


@dataclass
class YarnNode:
    """One ``title: ... --- ... ===`` block."""

    title: str
    tags: list[str] = field(default_factory=list)
    preamble: list[YarnLine] = field(default_factory=list)
    options: list[YarnOption] = field(default_factory=list)
    bark_variants: list[YarnLine] = field(default_factory=list)  # for bark nodes


def parse_yarn(text: str) -> list[YarnNode]:
    """Parse one or more Yarn nodes out of a file.

    Handles the subset of syntax npcforge emits. Lines that do not match any
    known pattern are attached to the current scope as narration (no speaker).
    """
    nodes: list[YarnNode] = []
    current: YarnNode | None = None
    in_header = False
    in_body = False
    current_option: YarnOption | None = None
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()

        # Node boundary
        if stripped == "===":
            if current is not None:
                nodes.append(current)
            current = None
            current_option = None
            in_header = False
            in_body = False
            i += 1
            continue

        if current is None:
            m = _TITLE_RE.match(stripped)
            if m:
                current = YarnNode(title=m.group(1))
                in_header = True
            i += 1
            continue

        if in_header:
            if stripped == "---":
                in_header = False
                in_body = True
                i += 1
                continue
            m = _TAGS_RE.match(stripped)
            if m:
                current.tags = [t.strip() for t in m.group(1).split(",")]
            # Silently skip other header keys (e.g. position).
            i += 1
            continue

        if in_body:
            # Node-level Yarn control.
            if _ENDIF_RE.match(stripped) or _ELSE_RE.match(stripped):
                i += 1
                continue

            m = _IF_COUNTER_RE.match(stripped)
            if m:
                # We're inside a bark-rotation node. Each branch has one
                # speaker line immediately after. Scoop it.
                if i + 1 < len(lines):
                    nxt = lines[i + 1].strip()
                    sm = _SPEAKER_LINE_RE.match(nxt)
                    if sm:
                        text_content = _strip_trailing_comment(sm.group("text"))
                        current.bark_variants.append(
                            YarnLine(speaker=sm.group("speaker").strip(), text=text_content)
                        )
                        i += 2
                        continue
                i += 1
                continue

            # Option line.
            mopt = _OPTION_RE.match(stripped)
            if not mopt:
                mopt = _BARE_OPTION_RE.match(stripped)
            if mopt:
                current_option = YarnOption(label=mopt.group(1).strip())
                current.options.append(current_option)
                i += 1
                continue

            # Jump inside an option.
            mjump = _JUMP_RE.match(raw)
            if mjump:
                if current_option is not None:
                    current_option.jump_to = mjump.group(1)
                i += 1
                continue

            # Speaker line (optionally indented — options indent their bodies).
            ms = _SPEAKER_LINE_RE.match(raw.strip())
            if ms:
                yln = YarnLine(
                    speaker=ms.group("speaker").strip(),
                    text=_strip_trailing_comment(ms.group("text")),
                )
                if current_option is not None:
                    current_option.lines.append(yln)
                else:
                    current.preamble.append(yln)
                i += 1
                continue

            # Narration / unrecognised — keep as preamble narration when at node level.
            if current_option is None and stripped and not stripped.startswith("//") and not stripped.startswith("<<"):
                current.preamble.append(YarnLine(speaker="", text=stripped))
            i += 1
            continue

        i += 1

    if current is not None:
        nodes.append(current)
    return nodes


def _strip_trailing_comment(text: str) -> str:
    """Remove any trailing ``//`` comment (e.g. bark emotion/intensity tags)."""
    idx = text.find("  //")
    if idx == -1:
        idx = text.find(" //")
    if idx != -1:
        return text[:idx].rstrip()
    return text


# ---------------------------------------------------------------------------
# Colour helpers — respect NO_COLOR / non-TTY output
# ---------------------------------------------------------------------------


def _use_colour(stream) -> bool:
    import os

    if os.environ.get("NO_COLOR"):
        return False
    return hasattr(stream, "isatty") and stream.isatty()


_ANSI = {
    "npc": "\033[36m",      # cyan
    "player": "\033[33m",   # yellow
    "label": "\033[35m",    # magenta (option label)
    "dim": "\033[2m",
    "reset": "\033[0m",
}


def _fmt(stream, text: str, colour: str) -> str:
    if _use_colour(stream):
        return f"{_ANSI[colour]}{text}{_ANSI['reset']}"
    return text


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_branch(
    node: YarnNode,
    label: str,
    *,
    stream=sys.stdout,
    tempo: float = 0.0,
    wait: bool = False,
) -> bool:
    """Print one option branch to ``stream``.

    Returns ``False`` if no branch with the given label was found. ``tempo``
    is a multiplier on a 300ms-per-line delay (0 = instant). ``wait`` prompts
    Enter between lines.
    """
    match = None
    target = label.strip().lower()
    for opt in node.options:
        if opt.label.strip().lower() == target:
            match = opt
            break
    if match is None:
        # Try substring match for convenience.
        for opt in node.options:
            if target in opt.label.strip().lower():
                match = opt
                break
    if match is None:
        return False

    print(_fmt(stream, f"── {node.title} :: [{match.label}] ──", "dim"), file=stream)
    for line in match.lines:
        _emit_line(line, stream=stream, tempo=tempo, wait=wait)
    if match.jump_to:
        print(_fmt(stream, f"   (jump to {match.jump_to})", "dim"), file=stream)
    return True


def render_all_branches(
    node: YarnNode,
    *,
    stream=sys.stdout,
    tempo: float = 0.0,
    wait: bool = False,
) -> None:
    """Print every option branch of a walk-up node in order."""
    print(_fmt(stream, f"══ {node.title} ══", "dim"), file=stream)
    for line in node.preamble:
        _emit_line(line, stream=stream, tempo=tempo, wait=wait)
    for opt in node.options:
        print(file=stream)
        print(_fmt(stream, f"── [{opt.label}] ──", "label"), file=stream)
        for line in opt.lines:
            _emit_line(line, stream=stream, tempo=tempo, wait=wait)
        if opt.jump_to:
            print(_fmt(stream, f"   (jump to {opt.jump_to})", "dim"), file=stream)


def render_barks(
    node: YarnNode,
    *,
    stream=sys.stdout,
    tempo: float = 0.0,
    wait: bool = False,
) -> None:
    """Print every bark variant in a bark-rotation node."""
    print(_fmt(stream, f"══ {node.title} ══", "dim"), file=stream)
    if not node.bark_variants:
        print(
            _fmt(stream, "  (no variants parsed — unusual Yarn shape)", "dim"),
            file=stream,
        )
        return
    for i, line in enumerate(node.bark_variants, start=1):
        prefix = _fmt(stream, f"  {i:>2}. ", "dim")
        body = _fmt(stream, f"{line.speaker}: {line.text}", "npc")
        print(prefix + body, file=stream)
        if tempo > 0:
            time.sleep(0.15 * tempo)
        if wait:
            _wait_for_enter(stream)


def _emit_line(line: YarnLine, *, stream, tempo: float, wait: bool) -> None:
    if not line.text:
        return
    if not line.speaker:
        print(f"  {line.text}", file=stream)
    else:
        speaker_colour = "player" if line.speaker.strip().lower() == "player" else "npc"
        print(
            f"  {_fmt(stream, line.speaker + ':', speaker_colour)} {line.text}",
            file=stream,
        )
    if tempo > 0:
        word_count = max(len(line.text.split()), 1)
        time.sleep(min(0.08 * word_count * tempo, 5.0))
    if wait:
        _wait_for_enter(stream)


def _wait_for_enter(stream) -> None:
    try:
        input()
    except EOFError:
        pass


# ---------------------------------------------------------------------------
# High-level play flow used by the CLI
# ---------------------------------------------------------------------------


def _out_dir(demo_dir: Path, out: Path | None) -> Path:
    return out or (demo_dir / "out")


def play_walk_up(
    *,
    demo_dir: Path,
    npc_id: str,
    intent: str | None = None,
    out: Path | None = None,
    tempo: float = 1.0,
    wait: bool = False,
    stream=sys.stdout,
) -> int:
    """CLI-style play of ``<out>/<npc_id>.yarn``. Returns a process exit code."""
    path = _out_dir(demo_dir, out) / f"{npc_id}.yarn"
    if not path.exists():
        print(
            f"No walk-up file at {path}. Run `npcforge build --demo-dir "
            f"{demo_dir}` first.",
            file=sys.stderr,
        )
        return 1
    nodes = parse_yarn(path.read_text(encoding="utf-8"))
    node = next((n for n in nodes if n.title == npc_id), None) or (nodes[0] if nodes else None)
    if node is None:
        print(f"{path} parsed to zero nodes.", file=sys.stderr)
        return 1
    if intent:
        ok = render_branch(node, intent, stream=stream, tempo=tempo, wait=wait)
        if not ok:
            print(f"No branch with label matching '{intent}'. Available:", file=sys.stderr)
            for opt in node.options:
                print(f"  - {opt.label}", file=sys.stderr)
            return 1
        return 0
    render_all_branches(node, stream=stream, tempo=tempo, wait=wait)
    return 0


def play_barks(
    *,
    demo_dir: Path,
    npc_id: str,
    trigger: str,
    out: Path | None = None,
    tempo: float = 1.0,
    wait: bool = False,
    stream=sys.stdout,
) -> int:
    """CLI-style play of ``<out>/<npc_id>_bark_<trigger>.yarn``."""
    path = _out_dir(demo_dir, out) / f"{npc_id}_bark_{trigger}.yarn"
    if not path.exists():
        print(
            f"No bark file at {path}. Run `npcforge build --demo-dir "
            f"{demo_dir} --mode barks` first.",
            file=sys.stderr,
        )
        return 1
    nodes = parse_yarn(path.read_text(encoding="utf-8"))
    if not nodes:
        print(f"{path} parsed to zero nodes.", file=sys.stderr)
        return 1
    render_barks(nodes[0], stream=stream, tempo=tempo, wait=wait)
    return 0
