"""Optional Yarn Spinner compile validation.

If ``ysc`` (Yarn Spinner Compiler) is on PATH, run it over the generated
output and return its exit code + messages. Otherwise emit a friendly hint
so authors know how to enable validation.

This module never raises on missing ``ysc``; it is purely informational.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CompileResult:
    """Outcome of a ``ysc compile`` run."""

    ran: bool
    ok: bool
    stdout: str = ""
    stderr: str = ""
    note: str = ""


def ysc_available() -> bool:
    """True when the ``ysc`` binary is discoverable on PATH."""
    return shutil.which("ysc") is not None


def compile_yarn_files(out_dir: Path) -> CompileResult:
    """Run ``ysc compile <out_dir>/*.yarn`` if the compiler is available."""
    if not ysc_available():
        return CompileResult(
            ran=False,
            ok=True,
            note=(
                "ysc not found on PATH. Install Yarn Spinner tooling to enable "
                "compile-time validation: "
                "https://docs.yarnspinner.dev/getting-started/editing-with-visual-studio-code"
            ),
        )

    yarn_files = sorted(out_dir.glob("*.yarn"))
    if not yarn_files:
        return CompileResult(
            ran=False,
            ok=True,
            note=f"No .yarn files in {out_dir} to compile.",
        )

    proc = subprocess.run(
        ["ysc", "compile", *(str(p) for p in yarn_files)],
        capture_output=True,
        text=True,
        check=False,
    )
    return CompileResult(
        ran=True,
        ok=proc.returncode == 0,
        stdout=proc.stdout,
        stderr=proc.stderr,
        note="" if proc.returncode == 0 else f"ysc exited with code {proc.returncode}",
    )
