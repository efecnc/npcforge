"""Godot adapter.

Maps npcforge's ``out/`` into a Godot 4 project:

- ``.yarn`` files  → ``npcforge/dialogue/`` under the project root
- ``lines.csv``    → same directory

We do not generate ``.import`` sidecars. Godot's editor produces them on
first scan of the project; the Yarn Spinner for Godot plugin handles
``.yarn`` files once installed. Users need the plugin installed before
the dialogue works, same as Unity needs Yarn Spinner.

Note: Godot's project root is the directory containing ``project.godot``.
We target paths relative to that root rather than any ``res://`` alias —
``res://`` is an editor-time concept, not a filesystem one.
"""

from __future__ import annotations

from pathlib import Path

from .base import EngineAdapter


class GodotAdapter(EngineAdapter):
    engine_name = "godot"

    def dialogue_dir(self, project_dir: Path) -> Path:
        return project_dir / "npcforge" / "dialogue"
