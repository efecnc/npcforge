"""VO / audio-pipeline helpers.

Turns generated dialogue into the side-data an audio pipeline needs:

- **Deterministic line IDs** (hash of ``npc_id | context | canonical-text``)
  so Wwise / FMOD / Unity Audio keys survive regeneration as long as the
  line text itself does not change.
- **Syllable-based duration estimates** — good enough for lip-sync timing
  budgets and loc length checks; not a replacement for real TTS metering.
- **Heuristic emotion inference** — cheap, offline, deterministic first
  draft of an emotion tag per line. Barks already carry emotion from the
  structured generator; walk-up and greeting lines get it here.
- **`lines.csv` writer** — one canonical export format audio pipelines and
  localisation tools both read.

No LLM calls. Everything in this module is pure.
"""

from __future__ import annotations

import csv
import hashlib
import re
from pathlib import Path
from typing import Iterable

from pydantic import BaseModel


class LineRecord(BaseModel):
    """One dialogue line, ready for the VO / loc / engine pipeline."""

    line_id: str
    npc_id: str
    speaker: str  # NPC display name, or "Player"
    context: str  # e.g. "walk_up:threaten_for_info" | "bark:greet_patron" | "greeting:time_of_day=dawn"
    source_file: str  # Filename inside out/ the line came from
    emotion: str = "neutral"
    intensity: str = "medium"  # low / medium / high
    duration_sec: float = 0.0
    text: str = ""


# ---------------------------------------------------------------------------
# Canonicalisation + line IDs
# ---------------------------------------------------------------------------


def canonicalise_text(text: str) -> str:
    """Normalise whitespace so ID hashing is stable across tiny formatting shifts."""
    return " ".join((text or "").split()).strip()


def line_id(npc_id: str, text: str, context: str = "") -> str:
    """Return a deterministic ``<npc_id>_<hash>`` ID for a single line.

    Same ``(npc_id, context, canonical text)`` → same ID across runs, so
    version-controlled ``lines.csv`` diffs stay readable when one branch
    regenerates but the surviving lines keep their IDs.
    """
    canonical = canonicalise_text(text)
    raw = f"{npc_id}|{context}|{canonical}".encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()[:10]
    return f"{npc_id}_{digest}"


# ---------------------------------------------------------------------------
# Duration estimate
# ---------------------------------------------------------------------------


_VOWEL_GROUPS_RE = re.compile(r"[aeiouyAEIOUY]+")
_SPEECH_RATE_SYLLABLES_PER_SEC = 4.0  # moderate English pace
_MIN_DURATION_SEC = 0.3


def count_syllables(text: str) -> int:
    """Approximate syllable count via vowel-group runs.

    Accurate enough for length budgets; a proper prosody pass happens in
    the VO session itself.
    """
    total = 0
    for word in (text or "").split():
        cleaned = re.sub(r"[^a-zA-Z]", "", word)
        if not cleaned:
            continue
        groups = _VOWEL_GROUPS_RE.findall(cleaned.lower())
        # Common trailing-e rule: 'made' → 1 syllable, not 2.
        count = len(groups) or 1
        if count > 1 and cleaned.lower().endswith("e"):
            count -= 1
        total += max(count, 1)
    return total


def estimate_duration_seconds(text: str) -> float:
    """Syllable-based duration estimate in seconds. Minimum of 0.3 s."""
    syllables = count_syllables(text)
    raw = syllables / _SPEECH_RATE_SYLLABLES_PER_SEC
    return max(round(raw, 2), _MIN_DURATION_SEC)


# ---------------------------------------------------------------------------
# Heuristic emotion tagging
# ---------------------------------------------------------------------------


_HIGH_INTENSITY_TOKENS = ("!!!", "!!")
_LOW_INTENSITY_TOKENS = ("...", "…", "—")

_EMOTION_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    # (emotion, tokens)
    ("threatening", ("leave now", "get out", "i said", "enough of", "or i will", "shut ")),
    ("pleading",    ("please", "i beg", "i need you", "help me", "don't go", "forgive me")),
    ("warm",        ("welcome", "my friend", "take a seat", "glad to", "nice to", "bless you")),
    ("angry",       ("damn", "stupid", "fool", "liar", "how dare", "never ")),
    ("sad",         ("gone", "alone", "i'm sorry", "miss ", "lost ", "no one")),
    ("confused",    ("what do you", "i don't understand", "who are", "that makes no")),
    ("wary",        ("why ", "who sent", "you seem", "explain yourself", "what business")),
    ("sarcastic",   ("of course", "naturally", "oh sure", "really now", "how convenient")),
)


def _detect_intensity(text: str) -> str:
    """Return one of ``low`` / ``medium`` / ``high`` from exclamations + ellipses."""
    stripped = (text or "").strip()
    if not stripped:
        return "medium"
    # Drop letters to evaluate punctuation density.
    if any(tok in stripped for tok in _HIGH_INTENSITY_TOKENS):
        return "high"
    letters = re.sub(r"[^A-Za-z]", "", stripped)
    if letters and letters.isupper() and len(letters) >= 3:
        return "high"
    if any(tok in stripped for tok in _LOW_INTENSITY_TOKENS):
        return "low"
    return "medium"


def infer_emotion(text: str) -> tuple[str, str]:
    """Return ``(emotion, intensity)`` via token-based rules.

    First match wins. Designed to produce something usable as a starting
    emotion tag for facial animation / VO direction without an extra LLM
    call. Writers can always override by editing ``lines.csv`` or the
    corresponding JSON.
    """
    lower = (text or "").lower()
    intensity = _detect_intensity(text)
    for emotion, tokens in _EMOTION_RULES:
        if any(tok in lower for tok in tokens):
            return emotion, intensity
    return "neutral", intensity


# ---------------------------------------------------------------------------
# CSV I/O
# ---------------------------------------------------------------------------


_LINES_CSV_FIELDS = [
    "line_id",
    "npc_id",
    "speaker",
    "context",
    "source_file",
    "emotion",
    "intensity",
    "duration_sec",
    "text",
]


def write_lines_csv(path: Path, records: Iterable[LineRecord]) -> Path:
    """Write a list of :class:`LineRecord` to ``path`` as UTF-8 CSV.

    Column order matches :data:`_LINES_CSV_FIELDS` — stable across npcforge
    versions so downstream tooling can depend on it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_LINES_CSV_FIELDS)
        writer.writeheader()
        for r in records:
            row = r.model_dump()
            # Normalise floats so CSV stays tidy.
            row["duration_sec"] = f"{float(row.get('duration_sec', 0.0)):.2f}"
            writer.writerow(row)
    return path


def read_lines_csv(path: Path) -> list[LineRecord]:
    """Inverse of :func:`write_lines_csv`. Useful for tools and tests."""
    if not path.exists():
        return []
    out: list[LineRecord] = []
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row["duration_sec"] = float(row.get("duration_sec") or 0.0)
            out.append(LineRecord(**row))
    return out
