"""Scaffold ``npcforge_project.yaml`` for new or existing demo directories."""

from __future__ import annotations

from pathlib import Path

from .project_config import PROJECT_FILE


def scaffold_npcforge_project(
    demo_dir: Path,
    *,
    topology: str,
    depth: str,
    force: bool = False,
) -> int:
    """Write ``npcforge_project.yaml``. Returns 0 on success, 1 if skipped."""
    demo_dir.mkdir(parents=True, exist_ok=True)
    path = demo_dir / PROJECT_FILE
    if path.exists() and not force:
        print(
            f"Refusing to overwrite existing {path.name}. "
            f"Pass --force to replace.",
            flush=True,
        )
        return 1
    body = (
        "# npcforge — per-project narrative defaults\n"
        f"topology: {topology}\n"
        f"depth: {depth}\n"
        "# Optional legacy single-knob (inferred from topology/depth if omitted):\n"
        "# narrative_preset: rpg_standard\n"
        "experimental: []\n"
        "review_workflow: false\n"
    )
    path.write_text(body, encoding="utf-8")
    print(f"Wrote {path}", flush=True)
    return 0
