"""export cast CSV."""

from __future__ import annotations

from pathlib import Path

from npcforge.export_cast import export_cast_csv


def test_export_cast_csv_writes_rows(tmp_path: Path) -> None:
    (tmp_path / "characters.yaml").write_text(
        "npcs:\n"
        "  - id: anna_k\n"
        "    name: Anna\n"
        "    role: innkeeper\n"
        "    voice: Warm, clipped.\n"
        "    tier: main\n"
        "    status: draft\n",
        encoding="utf-8",
    )
    out = export_cast_csv(tmp_path)
    text = out.read_text(encoding="utf-8")
    assert "anna_k" in text
    assert "innkeeper" in text
    assert "main" in text
    assert "draft" in text
    assert "Warm, clipped." in text
