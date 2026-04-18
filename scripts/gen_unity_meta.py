#!/usr/bin/env python3
"""Generate deterministic Unity .meta files for the npcforge UPM package.

Unity treats every file under ``Packages/`` as **immutable** and refuses
to generate ``.meta`` files on import — the package author has to ship
them. Every file and every folder needs a matching ``.meta`` with a
stable 32-hex-char GUID.

This script walks the UPM package tree, picks the right importer per
file type, and emits meta files with GUIDs derived from an md5 of
``dev.altai.npcforge/<relative-posix-path>``. Anyone running it on a
fresh checkout gets byte-identical GUIDs.

Run from the repo root:

    python3 scripts/gen_unity_meta.py

Safe to rerun — existing .meta files are overwritten with the same
content (the GUID derivation is deterministic).

Folders ending in ``~`` (e.g. ``Documentation~``) are Unity's way of
marking "ignored by asset import" and don't need meta files; this
script skips them.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent.parent / "examples" / "unity_integration" / "npcforge-unity"
PACKAGE_ID = "dev.altai.npcforge"


# ---------------------------------------------------------------------------
# Meta file templates — one per Unity importer kind
# ---------------------------------------------------------------------------

_FOLDER = """fileFormatVersion: 2
guid: {guid}
folderAsset: yes
DefaultImporter:
  externalObjects: {{}}
  userData:
  assetBundleName:
  assetBundleVariant:
"""

_SCRIPT = """fileFormatVersion: 2
guid: {guid}
MonoImporter:
  externalObjects: {{}}
  serializedVersion: 2
  defaultReferences: []
  executionOrder: 0
  icon: {{instanceID: 0}}
  userData:
  assetBundleName:
  assetBundleVariant:
"""

_ASMDEF = """fileFormatVersion: 2
guid: {guid}
AssemblyDefinitionImporter:
  externalObjects: {{}}
  userData:
  assetBundleName:
  assetBundleVariant:
"""

_TEXT = """fileFormatVersion: 2
guid: {guid}
TextScriptImporter:
  externalObjects: {{}}
  userData:
  assetBundleName:
  assetBundleVariant:
"""

_PKG_MANIFEST = """fileFormatVersion: 2
guid: {guid}
PackageManifestImporter:
  externalObjects: {{}}
  userData:
  assetBundleName:
  assetBundleVariant:
"""


def _guid_for(rel_posix_path: str) -> str:
    """Deterministic 32-hex-char GUID from the package id + relative path."""
    return hashlib.md5(f"{PACKAGE_ID}/{rel_posix_path}".encode("utf-8")).hexdigest()


def _template_for(path: Path) -> str:
    """Pick the right importer template based on file type."""
    if path.is_dir():
        return _FOLDER
    if path.suffix == ".cs":
        return _SCRIPT
    if path.suffix == ".asmdef":
        return _ASMDEF
    if path.name == "package.json":
        return _PKG_MANIFEST
    # Everything else (md, txt, generic json) ships as a TextAsset.
    return _TEXT


def _is_hidden_folder(rel_parts: tuple[str, ...]) -> bool:
    """Unity hides any folder whose name ends in ``~`` from asset import."""
    return any(part.endswith("~") for part in rel_parts)


def generate(package_root: Path = PACKAGE_ROOT) -> list[Path]:
    """Walk ``package_root`` and write a ``.meta`` for every non-hidden asset.

    Returns the list of meta files that were written (absolute paths).
    """
    if not package_root.is_dir():
        raise SystemExit(f"package root not found: {package_root}")

    written: list[Path] = []
    # Walk every path and every directory, but skip:
    #   - existing .meta files
    #   - anything inside a ~-hidden folder (Documentation~, Samples~, ...)
    for path in sorted(package_root.rglob("*")):
        if path.suffix == ".meta":
            continue
        rel_parts = path.relative_to(package_root).parts
        if _is_hidden_folder(rel_parts[:-1] if path.is_file() else rel_parts):
            continue

        rel_posix = path.relative_to(package_root).as_posix()
        guid = _guid_for(rel_posix)
        template = _template_for(path)

        # Meta file lives *next to* the asset for files, and at
        # <dir>.meta (same level as the folder) for directories.
        meta_path = path.parent / f"{path.name}.meta"
        meta_path.write_text(template.format(guid=guid), encoding="utf-8")
        written.append(meta_path)

    return written


def main() -> int:
    written = generate()
    print(f"Generated {len(written)} .meta files under {PACKAGE_ROOT}:")
    for m in written:
        rel = m.relative_to(PACKAGE_ROOT.parent.parent.parent)
        print(f"  {rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
