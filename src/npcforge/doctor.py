"""Lightweight project sanity checks for ``npcforge doctor``."""

from __future__ import annotations

from pathlib import Path

from .project_config import PROJECT_FILE, load_project_config
from .schemas import load_intents, load_npcs


def run_doctor(demo_dir: Path) -> tuple[list[str], list[str]]:
    """Return ``(errors, warnings)`` for a demo directory."""
    errors: list[str] = []
    warnings: list[str] = []

    if not demo_dir.is_dir():
        errors.append(f"demo_dir is not a directory: {demo_dir}")
        return errors, warnings

    chars = demo_dir / "characters.yaml"
    intents_path = demo_dir / "player_intents.yaml"

    try:
        cfg = load_project_config(demo_dir)
    except ValueError as exc:
        errors.append(f"{PROJECT_FILE}: {exc}")
        cfg = None

    if cfg is not None:
        if cfg.experimental:
            warnings.append(
                f"experimental flags active: {', '.join(cfg.experimental)}"
            )
        if cfg.review_workflow:
            warnings.append(
                "review_workflow is enabled — use tier/status on sheets for tracking."
            )

    if not (demo_dir / PROJECT_FILE).exists():
        warnings.append(
            f"missing {PROJECT_FILE} — using defaults "
            "(topology=quest_rpg, depth=standard)."
        )

    if not chars.exists():
        errors.append(f"missing characters.yaml under {demo_dir}")
    else:
        try:
            npcs = load_npcs(chars)
            if not npcs:
                warnings.append("characters.yaml loads but contains no full NPC rows.")
        except Exception as exc:  # noqa: BLE001 — surface load failures
            errors.append(f"characters.yaml: {exc}")

    if not intents_path.exists():
        warnings.append(
            "missing player_intents.yaml — walk-up builds need intents "
            "(see examples/)."
        )
    else:
        try:
            load_intents(intents_path)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"player_intents.yaml: {exc}")

    return errors, warnings
