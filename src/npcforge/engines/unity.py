"""Unity adapter.

Maps npcforge's ``out/`` into a Unity project:

- ``.yarn`` + ``lines.csv``  → ``Assets/NpcForge/Dialogue/``
- Runtime glue (the four C# scripts from ``examples/unity_integration/``)
  → ``Assets/NpcForge/Scripts/`` when ``--install-scripts`` is passed.

We deliberately **do not write ``.meta`` sidecars**. Yarn Spinner's
``ScriptedImporter`` generates the right ``*.yarn.meta`` on first
reimport, and Unity writes its own ``.meta`` for the CSV. Generating
them ourselves tends to desync with whatever Yarn Spinner version the
user has installed.
"""

from __future__ import annotations

from pathlib import Path

from .base import EngineAdapter, SyncAction, SyncResult


class UnityAdapter(EngineAdapter):
    engine_name = "unity"

    def dialogue_dir(self, project_dir: Path) -> Path:
        return project_dir / "Assets" / "NpcForge" / "Dialogue"

    def scripts_dir(self, project_dir: Path) -> Path | None:
        return project_dir / "Assets" / "NpcForge" / "Scripts"

    def install_scripts(
        self,
        *,
        result: SyncResult,
        scripts_source_dir: Path | None,
        dest_dir: Path,
        overwrite: bool,
    ) -> None:
        """Copy the committed C# glue from ``examples/unity_integration``.

        The caller passes ``scripts_source_dir``; when omitted, we walk up
        from this module to find the repo's example folder. In a
        distributed install (pip-installed, no repo checkout) the
        fallback returns nothing and the sync records a ``skip`` with a
        readable reason.
        """
        if scripts_source_dir is None:
            scripts_source_dir = _default_unity_scripts_source()

        if scripts_source_dir is None or not scripts_source_dir.is_dir():
            result.actions.append(
                SyncAction(
                    action="skip",
                    destination=dest_dir,
                    reason=(
                        "Unity runtime scripts unavailable — pass "
                        "--scripts-source or run from a repo checkout."
                    ),
                )
            )
            return

        for script in sorted(scripts_source_dir.glob("*.cs")):
            dest = dest_dir / script.name
            if dest.exists() and not overwrite:
                result.actions.append(
                    SyncAction(
                        action="skip",
                        destination=dest,
                        source=script,
                        reason="script already present",
                    )
                )
                continue
            if not result.dry_run:
                dest.write_bytes(script.read_bytes())
            result.actions.append(
                SyncAction(
                    action="copy",
                    destination=dest,
                    source=script,
                    reason="installed runtime glue",
                )
            )


def _default_unity_scripts_source() -> Path | None:
    """Best-effort locate the shipped Unity C# scripts from a repo checkout."""
    here = Path(__file__).resolve()
    # src/npcforge/engines/unity.py → walk up four to repo root.
    for candidate in here.parents:
        maybe = candidate / "examples" / "unity_integration" / "Assets" / "NpcForge" / "Scripts"
        if maybe.is_dir():
            return maybe
    return None
