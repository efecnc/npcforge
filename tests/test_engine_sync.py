"""Tests for v0.7.1 engine-sync — path resolution, marker I/O, copy semantics."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from npcforge.engines import (
    GodotAdapter,
    SyncMarker,
    UnityAdapter,
    UnrealAdapter,
    get_adapter,
    marker_path_for,
    supported_engines,
)
from npcforge.tools import EngineSyncInput, engine_sync


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_supported_engines_exposes_the_three_adapters():
    assert supported_engines() == ["godot", "unity", "unreal"]


def test_get_adapter_resolves_known_engines():
    assert isinstance(get_adapter("unity"), UnityAdapter)
    assert isinstance(get_adapter("godot"), GodotAdapter)
    assert isinstance(get_adapter("unreal"), UnrealAdapter)


def test_get_adapter_rejects_unknown_engine():
    with pytest.raises(ValueError, match="Unknown engine"):
        get_adapter("cryengine")


# ---------------------------------------------------------------------------
# Path resolution — each engine knows where its dialogue folder lives
# ---------------------------------------------------------------------------


def test_unity_dialogue_path(tmp_path: Path):
    assert UnityAdapter().dialogue_dir(tmp_path) == tmp_path / "Assets" / "NpcForge" / "Dialogue"


def test_unity_scripts_path(tmp_path: Path):
    assert UnityAdapter().scripts_dir(tmp_path) == tmp_path / "Assets" / "NpcForge" / "Scripts"


def test_godot_dialogue_path(tmp_path: Path):
    assert GodotAdapter().dialogue_dir(tmp_path) == tmp_path / "npcforge" / "dialogue"


def test_godot_has_no_scripts_target(tmp_path: Path):
    assert GodotAdapter().scripts_dir(tmp_path) is None


def test_unreal_dialogue_path(tmp_path: Path):
    assert UnrealAdapter().dialogue_dir(tmp_path) == tmp_path / "Content" / "NpcForge" / "Dialogue"


# ---------------------------------------------------------------------------
# Sync marker round-trip
# ---------------------------------------------------------------------------


def test_sync_marker_roundtrip(tmp_path: Path):
    marker = SyncMarker(
        engine="unity",
        project_dir=str(tmp_path),
        last_sync_at="2026-04-18T00:00:00+00:00",
        npcforge_version="0.7.1",
        files={"Assets/NpcForge/Dialogue/foo.yarn": "abc123"},
    )
    path = tmp_path / ".npcforge-sync.json"
    path.write_text(marker.to_json(), encoding="utf-8")
    loaded = SyncMarker.read(path)
    assert loaded is not None
    assert loaded.engine == "unity"
    assert loaded.npcforge_version == "0.7.1"
    assert loaded.files == {"Assets/NpcForge/Dialogue/foo.yarn": "abc123"}


def test_sync_marker_returns_none_for_missing_or_bad_file(tmp_path: Path):
    assert SyncMarker.read(tmp_path / "nope.json") is None

    bad = tmp_path / "bad.json"
    bad.write_text("not json at all", encoding="utf-8")
    assert SyncMarker.read(bad) is None


def test_marker_path_for_points_inside_base(tmp_path: Path):
    assert marker_path_for(tmp_path / "sub") == tmp_path / "sub" / ".npcforge-sync.json"


# ---------------------------------------------------------------------------
# Unity end-to-end sync on fake out/ tree
# ---------------------------------------------------------------------------


def _fake_out_dir(tmp_path: Path) -> Path:
    out = tmp_path / "out"
    out.mkdir()
    (out / "mira_vesser.yarn").write_text("title: mira_vesser\n---\n===\n", encoding="utf-8")
    (out / "world.yarn").write_text("title: Start\n---\n===\n", encoding="utf-8")
    (out / "lines.csv").write_text(
        "line_id,npc_id,speaker,context,source_file,emotion,intensity,duration_sec,text\n"
        "mira_vesser_abc,mira_vesser,Mira,walk_up:x:turn_0,mira_vesser.yarn,neutral,medium,1.00,Hi\n",
        encoding="utf-8",
    )
    # Debug output that should NOT be synced:
    (out / "manifest.json").write_text("{}", encoding="utf-8")
    (out / "lint.md").write_text("", encoding="utf-8")
    (out / "mira_vesser.jsonl").write_text("", encoding="utf-8")
    return out


def test_unity_sync_copies_yarn_and_csv_but_skips_debug_output(tmp_path: Path):
    out_dir = _fake_out_dir(tmp_path)
    project = tmp_path / "game"

    adapter = UnityAdapter()
    result = adapter.sync(source_out_dir=out_dir, project_dir=project)

    dialogue = project / "Assets" / "NpcForge" / "Dialogue"
    assert (dialogue / "mira_vesser.yarn").exists()
    assert (dialogue / "world.yarn").exists()
    assert (dialogue / "lines.csv").exists()
    assert not (dialogue / "manifest.json").exists(), "debug files must not be synced"
    assert not (dialogue / "lint.md").exists()
    assert not (dialogue / "mira_vesser.jsonl").exists()

    # Marker written and records hashes for every synced file.
    marker = SyncMarker.read(project / "Assets" / "NpcForge" / "Dialogue" / ".npcforge-sync.json")
    assert marker is not None
    assert marker.engine == "unity"
    assert len(marker.files) == 3
    assert result.total_files == 3


def test_second_sync_skips_unchanged_files(tmp_path: Path):
    out_dir = _fake_out_dir(tmp_path)
    project = tmp_path / "game"

    UnityAdapter().sync(source_out_dir=out_dir, project_dir=project)
    second = UnityAdapter().sync(source_out_dir=out_dir, project_dir=project)

    skipped = [a for a in second.actions if a.action == "skip" and a.source is not None]
    copied = [a for a in second.actions if a.action == "copy"]
    assert len(skipped) == 3, "every unchanged file should be a skip, not a recopy"
    assert copied == []


def test_changed_file_is_recopied_on_next_sync(tmp_path: Path):
    out_dir = _fake_out_dir(tmp_path)
    project = tmp_path / "game"
    UnityAdapter().sync(source_out_dir=out_dir, project_dir=project)

    (out_dir / "mira_vesser.yarn").write_text(
        "title: mira_vesser\n---\nMira: New line.\n===\n", encoding="utf-8"
    )
    second = UnityAdapter().sync(source_out_dir=out_dir, project_dir=project)

    copies = [
        a for a in second.actions
        if a.action == "copy" and a.source and a.source.name == "mira_vesser.yarn"
    ]
    assert len(copies) == 1
    assert copies[0].reason == "content changed"


def test_dry_run_writes_nothing(tmp_path: Path):
    out_dir = _fake_out_dir(tmp_path)
    project = tmp_path / "game"

    result = UnityAdapter().sync(
        source_out_dir=out_dir, project_dir=project, dry_run=True
    )

    assert result.dry_run is True
    # Nothing should actually exist on disk yet.
    dialogue = project / "Assets" / "NpcForge" / "Dialogue"
    assert not dialogue.exists() or not any(dialogue.iterdir())
    assert not (dialogue / ".npcforge-sync.json").exists()
    # Actions should still describe the planned work.
    assert result.total_files == 3


def test_sync_reports_error_on_missing_source(tmp_path: Path):
    project = tmp_path / "game"
    result = UnityAdapter().sync(
        source_out_dir=tmp_path / "does_not_exist", project_dir=project
    )
    assert result.errors
    assert "Source directory does not exist" in result.errors[0]


# ---------------------------------------------------------------------------
# Unreal's lines.csv relocation
# ---------------------------------------------------------------------------


def test_unreal_splits_lines_csv_into_data_folder(tmp_path: Path):
    out_dir = _fake_out_dir(tmp_path)
    project = tmp_path / "game"

    UnrealAdapter().sync(source_out_dir=out_dir, project_dir=project)

    dialogue = project / "Content" / "NpcForge" / "Dialogue"
    data = project / "Content" / "NpcForge" / "Data"
    assert (dialogue / "mira_vesser.yarn").exists()
    assert (dialogue / "world.yarn").exists()
    assert (data / "lines.csv").exists()
    assert not (dialogue / "lines.csv").exists(), "CSV should have been moved"


# ---------------------------------------------------------------------------
# engine_sync tool — end-to-end
# ---------------------------------------------------------------------------


def test_engine_sync_tool_on_unity(tmp_path: Path):
    out_dir = _fake_out_dir(tmp_path)
    demo = tmp_path / "demo"
    demo.mkdir()
    # engine_sync resolves the source from demo_dir/out by default, so
    # symlink or copy out into the demo tree.
    for item in out_dir.iterdir():
        (demo / "out").mkdir(exist_ok=True)
        (demo / "out" / item.name).write_bytes(item.read_bytes())

    project = tmp_path / "unity_project"
    result = asyncio.run(
        engine_sync(
            EngineSyncInput(
                demo_dir=demo,
                project_dir=project,
                engine="unity",
            )
        )
    )
    assert result.engine == "unity"
    assert result.total_files == 3
    assert result.errors == []
    assert (project / "Assets" / "NpcForge" / "Dialogue" / "mira_vesser.yarn").exists()
    assert result.marker_path is not None


def test_engine_sync_tool_dry_run_reports_actions_without_writing(tmp_path: Path):
    demo = tmp_path / "demo"
    (demo / "out").mkdir(parents=True)
    (demo / "out" / "a.yarn").write_text("title: a\n---\n===\n", encoding="utf-8")

    project = tmp_path / "proj"
    result = asyncio.run(
        engine_sync(
            EngineSyncInput(
                demo_dir=demo,
                project_dir=project,
                engine="godot",
                dry_run=True,
            )
        )
    )
    assert result.dry_run is True
    assert result.total_files == 1
    assert not (project / "npcforge" / "dialogue" / "a.yarn").exists()


def test_engine_sync_tool_accepts_source_dir_override(tmp_path: Path):
    source = tmp_path / "some_snapshot"
    source.mkdir()
    (source / "b.yarn").write_text("title: b\n---\n===\n", encoding="utf-8")

    project = tmp_path / "proj"
    result = asyncio.run(
        engine_sync(
            EngineSyncInput(
                demo_dir=tmp_path / "unused",
                project_dir=project,
                engine="godot",
                source_dir=source,
            )
        )
    )
    assert result.total_files == 1
    assert (project / "npcforge" / "dialogue" / "b.yarn").exists()
