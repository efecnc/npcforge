"""Unreal Engine adapter.

Maps npcforge's ``out/`` into an Unreal project:

- ``.yarn`` files  → ``Content/NpcForge/Dialogue/``
- ``lines.csv``    → ``Content/NpcForge/Data/``

Unreal's ``Content/`` tree is what the editor scans; ``.uasset`` binaries
are generated on reimport. We deliberately don't create any binary
sidecar files here — the editor handles import on next launch.

The `Yarn Spinner for Unreal` plugin consumes ``.yarn`` files placed
under ``Content/``; users need that plugin installed the same way Unity
users need Yarn Spinner for Unity.
"""

from __future__ import annotations

from pathlib import Path

from .base import EngineAdapter, SyncAction, SyncResult


class UnrealAdapter(EngineAdapter):
    engine_name = "unreal"

    def dialogue_dir(self, project_dir: Path) -> Path:
        return project_dir / "Content" / "NpcForge" / "Dialogue"

    def sync(
        self,
        *,
        source_out_dir: Path,
        project_dir: Path,
        install_scripts: bool = False,
        scripts_source_dir: Path | None = None,
        dry_run: bool = False,
    ) -> SyncResult:
        """Unreal splits dialogue and data into separate trees, so we
        override the base copy path to send ``lines.csv`` to
        ``Content/NpcForge/Data/`` while ``.yarn`` files go under
        ``Content/NpcForge/Dialogue/``.
        """
        # Run the base sync first — handles .yarn + marker.
        result = super().sync(
            source_out_dir=source_out_dir,
            project_dir=project_dir,
            install_scripts=install_scripts,
            scripts_source_dir=scripts_source_dir,
            dry_run=dry_run,
        )

        # Now move lines.csv from the dialogue tree into Data/ if the base
        # sync just copied it there.
        dialogue_dest = self.dialogue_dir(project_dir)
        data_dest = project_dir / "Content" / "NpcForge" / "Data"
        wrong_csv = dialogue_dest / "lines.csv"
        right_csv = data_dest / "lines.csv"

        if wrong_csv.exists() and not dry_run:
            data_dest.mkdir(parents=True, exist_ok=True)
            right_csv.write_bytes(wrong_csv.read_bytes())
            wrong_csv.unlink()

        # Record the move in the action log regardless of dry_run.
        if any(a.source and a.source.name == "lines.csv" for a in result.actions):
            result.actions.append(
                SyncAction(
                    action="write",
                    destination=right_csv,
                    reason="relocated lines.csv into Content/NpcForge/Data",
                )
            )
        return result
