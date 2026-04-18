"""Engine adapter base class + shared sync types.

An :class:`EngineAdapter` maps npcforge's ``out/`` directory layout into
the conventions of one game engine (Unity / Godot / Unreal / ...).
Concrete adapters subclass this, define the destination paths, and can
optionally install the runtime glue scripts that engine needs.

Design principle: **we copy dialogue files and let the engine's own
importer generate sidecar metadata** (``.meta`` for Unity, ``.import``
for Godot, ``.uasset`` for Unreal). Writing those sidecars ourselves
tends to drift from whichever Yarn Spinner version the user has
installed; letting the engine do it is the robust path.

Every adapter emits a :class:`SyncResult` with a list of
:class:`SyncAction` entries. Callers (CLI, MCP tool) render that into
human or machine output.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal


ActionKind = Literal["copy", "write", "skip", "remove"]


@dataclass
class SyncAction:
    """One filesystem operation performed (or planned) by a sync run."""

    action: ActionKind
    destination: Path
    source: Path | None = None
    reason: str = ""


@dataclass
class SyncResult:
    """Aggregate result of one :meth:`EngineAdapter.sync` call."""

    engine: str
    project_dir: Path
    actions: list[SyncAction] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    marker_path: Path | None = None
    dry_run: bool = False

    @property
    def total_files(self) -> int:
        """Count of files copied from source to destination this run.

        Skips (unchanged content) and marker writes are bookkeeping and
        don't count as deliverables.
        """
        return sum(1 for a in self.actions if a.action == "copy")

    def format_summary(self) -> str:
        by_kind: dict[ActionKind, int] = {}
        for action in self.actions:
            by_kind[action.action] = by_kind.get(action.action, 0) + 1
        parts = [
            f"engine={self.engine}",
            f"project={self.project_dir}",
            f"dry_run={self.dry_run}",
            "actions=" + ", ".join(f"{k}:{v}" for k, v in sorted(by_kind.items())),
        ]
        if self.errors:
            parts.append(f"errors={len(self.errors)}")
        return "  ".join(parts)


# ---------------------------------------------------------------------------
# Sync marker — tracks what we own inside the engine's project tree
# ---------------------------------------------------------------------------


_MARKER_FILENAME = ".npcforge-sync.json"


def marker_path_for(base_dir: Path) -> Path:
    """Where we write the sync marker inside a synced folder."""
    return base_dir / _MARKER_FILENAME


@dataclass
class SyncMarker:
    """Small JSON sidecar describing the last sync we performed.

    On the next sync we read this to:
    - Know which files we previously owned (so we can diff hashes and
      skip no-op overwrites).
    - Optionally prune files we wrote before that are no longer in the
      source (v0.7.2+ feature; recorded, not yet exposed).
    """

    engine: str
    project_dir: str
    last_sync_at: str  # ISO-8601 UTC
    npcforge_version: str
    # Map of {destination-relative-path: sha256-of-source-bytes}
    files: dict[str, str] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(
            {
                "engine": self.engine,
                "project_dir": self.project_dir,
                "last_sync_at": self.last_sync_at,
                "npcforge_version": self.npcforge_version,
                "files": dict(sorted(self.files.items())),
            },
            indent=2,
        )

    @classmethod
    def read(cls, path: Path) -> SyncMarker | None:
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return cls(
            engine=data.get("engine", ""),
            project_dir=data.get("project_dir", ""),
            last_sync_at=data.get("last_sync_at", ""),
            npcforge_version=data.get("npcforge_version", ""),
            files=dict(data.get("files", {})),
        )


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


# ---------------------------------------------------------------------------
# EngineAdapter
# ---------------------------------------------------------------------------


class EngineAdapter:
    """Base class every engine adapter inherits from.

    Subclasses must set ``engine_name`` and implement :meth:`dialogue_dir`.
    They may override :meth:`scripts_dir` and :meth:`install_scripts` when
    the engine has runtime glue npcforge should provide.
    """

    engine_name: str = "base"

    # ---- path resolution ------------------------------------------------

    def dialogue_dir(self, project_dir: Path) -> Path:
        """Where ``.yarn`` + ``lines.csv`` should land."""
        raise NotImplementedError

    def scripts_dir(self, project_dir: Path) -> Path | None:
        """Where runtime glue scripts should land, or ``None`` if the
        engine's adapter does not install scripts."""
        return None

    def marker_dir(self, project_dir: Path) -> Path:
        """Where the ``.npcforge-sync.json`` marker lives. Defaults to the
        dialogue dir; adapters may override."""
        return self.dialogue_dir(project_dir)

    # ---- script installation (optional) --------------------------------

    def install_scripts(
        self,
        *,
        result: SyncResult,
        scripts_source_dir: Path | None,
        dest_dir: Path,
        overwrite: bool,
    ) -> None:
        """Copy runtime glue scripts into ``dest_dir``. No-op by default.

        Adapters that have runtime glue (Unity's C# scripts, Godot's
        GDScript, etc.) override this and copy the files they ship.
        """
        return None

    # ---- core sync ------------------------------------------------------

    def sync(
        self,
        *,
        source_out_dir: Path,
        project_dir: Path,
        install_scripts: bool = False,
        scripts_source_dir: Path | None = None,
        dry_run: bool = False,
    ) -> SyncResult:
        """Copy dialogue + ``lines.csv`` from ``source_out_dir`` into the
        engine's expected layout under ``project_dir``.

        ``install_scripts`` triggers the adapter's :meth:`install_scripts`
        hook — set to true only on first sync or when bumping the runtime
        glue.
        """
        result = SyncResult(
            engine=self.engine_name,
            project_dir=project_dir,
            dry_run=dry_run,
        )

        if not source_out_dir.is_dir():
            result.errors.append(f"Source directory does not exist: {source_out_dir}")
            return result

        dialogue_dest = self.dialogue_dir(project_dir)
        if not dry_run:
            dialogue_dest.mkdir(parents=True, exist_ok=True)

        marker_loc = marker_path_for(self.marker_dir(project_dir))
        previous_marker = SyncMarker.read(marker_loc)
        previous_hashes = previous_marker.files if previous_marker else {}
        new_hashes: dict[str, str] = {}

        # Whitelist which files we own in the source dir. Everything else
        # in out/ (JSONL traces, the manifest, lint.md) is debug output
        # that does not belong in the engine.
        for item in sorted(source_out_dir.iterdir()):
            if not item.is_file():
                continue
            if item.suffix.lower() not in {".yarn", ".csv"}:
                continue
            dest = dialogue_dest / item.name
            source_hash = file_sha256(item)
            rel = str(dest.relative_to(project_dir))
            new_hashes[rel] = source_hash

            if dest.exists():
                if file_sha256(dest) == source_hash:
                    result.actions.append(
                        SyncAction(
                            action="skip",
                            destination=dest,
                            source=item,
                            reason="identical content",
                        )
                    )
                    continue
                reason = "content changed"
            else:
                reason = "new file"

            if not dry_run:
                dest.write_bytes(item.read_bytes())
            result.actions.append(
                SyncAction(action="copy", destination=dest, source=item, reason=reason)
            )

        # Optional script install.
        scripts_dest = self.scripts_dir(project_dir)
        if install_scripts and scripts_dest is not None:
            if not dry_run:
                scripts_dest.mkdir(parents=True, exist_ok=True)
            self.install_scripts(
                result=result,
                scripts_source_dir=scripts_source_dir,
                dest_dir=scripts_dest,
                overwrite=False,
            )

        # Marker write.
        marker_loc.parent.mkdir(parents=True, exist_ok=True)
        new_marker = SyncMarker(
            engine=self.engine_name,
            project_dir=str(project_dir),
            last_sync_at=datetime.now(timezone.utc).isoformat(),
            npcforge_version=_current_version(),
            files=new_hashes,
        )
        if not dry_run:
            marker_loc.write_text(new_marker.to_json(), encoding="utf-8")
        result.marker_path = marker_loc
        result.actions.append(
            SyncAction(
                action="write",
                destination=marker_loc,
                reason="sync marker updated",
            )
        )

        return result


def _current_version() -> str:
    """Return npcforge's version without creating an import cycle."""
    try:
        from .. import __version__
        return __version__
    except Exception:
        return "unknown"
