"""Cast table export for spreadsheets / production trackers."""

from __future__ import annotations

import csv
from pathlib import Path

from .schemas import load_npcs


def export_cast_csv(demo_dir: Path, out: Path | None = None) -> Path:
    """Write a CSV of NPC ids, names, roles, tier, status, and a one-line voice summary.

    Default output: ``<demo_dir>/out/cast.csv``.
    """
    characters = demo_dir / "characters.yaml"
    if not characters.exists():
        raise FileNotFoundError(f"Missing characters.yaml under {demo_dir}")

    npcs = load_npcs(characters)
    dest = out or (demo_dir / "out" / "cast.csv")
    dest.parent.mkdir(parents=True, exist_ok=True)

    with dest.open("w", encoding="utf-8", newline="") as handle:
        w = csv.writer(handle)
        w.writerow(["id", "name", "role", "tier", "status", "voice_line"])
        for n in npcs:
            voice_line = (n.voice or "").split("\n", 1)[0].strip().replace("\r", " ")
            w.writerow(
                [
                    n.id,
                    n.name,
                    n.role,
                    n.tier or "",
                    n.status or "",
                    voice_line,
                ]
            )

    return dest
