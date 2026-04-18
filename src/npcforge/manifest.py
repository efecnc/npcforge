"""Typed manifest produced by ``build_pipeline``.

Replaces the v0.4.x ``dict[str, Any]`` manifest with a Pydantic model so
downstream consumers (CI diffs, writer dashboards, engine importers) get a
known schema. The CLI and MCP server both serialise this to JSON; the
tool-layer output surfaces it as a first-class field.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LintSummary(BaseModel):
    """Roll-up of the forbidden-word lint pass."""

    markdown: str = Field(
        ..., description="Filename (inside out/) of the human-readable report."
    )
    total_hits: int = Field(
        ..., description="Total forbidden-word violations across the whole run."
    )


class NpcWalkUpEntry(BaseModel):
    """Walk-up dialogue artefacts for one NPC."""

    yarn: str
    yarn_hash: str
    intents: list[str] = Field(
        default_factory=list,
        description="Ordered intent ids that produced a branch.",
    )
    branch_count: int = 0
    voice_scores: dict[str, float] = Field(
        default_factory=dict,
        description=(
            "Per-intent voice-consistency score in [0, 1]. Higher = assistant "
            "turns sit closer (in embedding space) to the NPC's sample_lines. "
            "Empty when scoring was disabled or the embedding provider failed."
        ),
    )


class BarkTriggerEntry(BaseModel):
    """Bark library produced for one (NPC, trigger)."""

    trigger: str
    requested: int
    produced: int
    yarn: str
    yarn_hash: str
    # Pydantic would warn because BaseModel already has a .json() method, so
    # we store under ``json_path`` but keep ``json`` on the wire for
    # backward compatibility with the v0.4.x manifest format.
    json_path: str = Field(alias="json")

    model_config = {"populate_by_name": True}


class NpcEntry(BaseModel):
    """All artefacts produced for one NPC in this run."""

    sheet_hash: str
    walk_up: NpcWalkUpEntry | None = None
    barks: list[BarkTriggerEntry] = Field(default_factory=list)


class WorldEntry(BaseModel):
    """The master ``world.yarn`` node (only emitted on a full walk-up run)."""

    yarn: str
    yarn_hash: str


class LinesExport(BaseModel):
    """Summary of the audio / VO / localisation ``lines.csv`` export."""

    csv: str = Field(
        ..., description="Filename (inside out/) of the lines export."
    )
    total: int = Field(
        ..., description="Number of LineRecord rows written to the CSV."
    )


class Manifest(BaseModel):
    """Top-level manifest written to ``out/manifest.json``."""

    version: str
    generated_at: str
    provider: str
    model: str | None = None
    mode: str
    npcs: dict[str, NpcEntry] = Field(default_factory=dict)
    world: WorldEntry | None = None
    lint: LintSummary
    lines: LinesExport | None = Field(
        default=None,
        description=(
            "Lines CSV export summary (v0.7+). Null when the run did not "
            "produce dialogue lines (e.g. barks-only builds still emit one)."
        ),
    )
    elapsed_seconds: float = 0.0
    voice_scoring_enabled: bool = False
