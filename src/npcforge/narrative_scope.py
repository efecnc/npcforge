"""Optional narrative scope — worlds within worlds, levels, districts.

Writers may add ``layers.yaml`` beside ``characters.yaml`` declaring a
hierarchy of :class:`WorldLayer` nodes (region → town → interior, …).
Each :class:`~npcforge.schemas.NpcSheet` can list ``scope_tags`` (ids
from that file) plus an optional ``narrative_scope_note`` so dialogue
generators treat first-hand knowledge as local to those slices.

This module is intentionally small: it loads YAML, formats prompt text,
and filters NPC lists for ``build_pipeline`` / CLI.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator

from .schemas import NpcSheet


class WorldLayer(BaseModel):
    """One node in the world's spatial / narrative hierarchy."""

    id: str = Field(
        ...,
        description="lower_snake_case id — referenced from NpcSheet.scope_tags.",
    )
    parent: str | None = Field(
        default=None,
        description="Parent layer id, or null for a root layer.",
    )
    name: str = Field(default="", description="Human-readable place or beat name.")
    summary: str = Field(
        default="",
        description="What exists here; what an NPC native to this layer plausibly knows first-hand.",
    )


class LayersConfig(BaseModel):
    """Top-level ``layers.yaml`` shape."""

    layers: list[WorldLayer] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_ids(self) -> LayersConfig:  # noqa: D401 — pydantic hook
        seen: set[str] = set()
        for layer in self.layers:
            if layer.id in seen:
                raise ValueError(f"Duplicate layer id {layer.id!r} in layers.yaml")
            seen.add(layer.id)
        return self


def layers_yaml_path(demo_dir: Path) -> Path:
    return demo_dir / "layers.yaml"


def load_layers_config(path: Path) -> LayersConfig:
    """Load ``layers.yaml`` or return an empty config when missing."""
    if not path.exists():
        return LayersConfig()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must be a YAML mapping at the top level")
    layers_raw = raw.get("layers")
    if layers_raw is None:
        return LayersConfig()
    if not isinstance(layers_raw, list):
        raise ValueError(f"{path}: 'layers' must be a list")
    layers = [WorldLayer.model_validate(item) for item in layers_raw]
    return LayersConfig(layers=layers)


def _by_id(cfg: LayersConfig) -> dict[str, WorldLayer]:
    return {layer.id: layer for layer in cfg.layers}


def layer_lineage(layer_id: str, cfg: LayersConfig) -> list[WorldLayer]:
    """Return layers from root → leaf for ``layer_id``, if declared."""
    table = _by_id(cfg)
    chain: list[WorldLayer] = []
    cur: WorldLayer | None = table.get(layer_id)
    seen: set[str] = set()
    while cur is not None and cur.id not in seen:
        seen.add(cur.id)
        chain.append(cur)
        pid = cur.parent
        cur = table.get(pid) if pid else None
    chain.reverse()
    return chain


def format_layers_catalog_block(cfg: LayersConfig) -> str:
    """Dense catalog for NPC-generation prompts (empty if no layers)."""
    if not cfg.layers:
        return ""
    lines = [
        "### World layers (assign new NPCs to the narrowest tag that fits)",
        "Pick ``scope_tags`` from the ids below. A miner who only knows the "
        "pit uses the mine layer; the tavernkeeper uses the tavern + town tags.",
    ]
    for layer in cfg.layers:
        parent_note = f"  parent: `{layer.parent}`" if layer.parent else "  (root)"
        summ = layer.summary.strip() or "(no summary)"
        lines.append(f"- **{layer.id}** — {layer.name or layer.id}\n  {summ}\n{parent_note}")
    return "\n".join(lines) + "\n"


def format_npc_scope_section(npc: NpcSheet, cfg: LayersConfig | None) -> str:
    """Markdown-ish block injected under the character sheet in dialogue prompts."""
    cfg = cfg or LayersConfig()
    chunks: list[str] = []
    if npc.scope_tags:
        chunks.append(
            "This character is grounded to these **scope tags** "
            "(place / arc / mission slice — ids from layers.yaml or freeform writer tags):"
        )
        for tag in npc.scope_tags:
            lineage = layer_lineage(tag, cfg)
            if lineage:
                path_str = " → ".join(L.name.strip() or L.id for L in lineage)
                leaf = lineage[-1]
                summ = (leaf.summary or "").strip() or "(see layers.yaml)"
                chunks.append(f"- `{tag}` — path: _{path_str}_ — {summ}")
            else:
                chunks.append(
                    f"- `{tag}` — (no layer row with this id; treat as a writer tag — "
                    "still respect as geographic / narrative scope)"
                )
    note = (npc.narrative_scope_note or "").strip()
    if note:
        chunks.append(f"Writer scope note: {note}")
    if not chunks:
        return ""
    rules = (
        "Scope rules: first-hand knowledge and casual detail belong **inside** "
        "this scope. Outside it, speak in rumours, profession-level guesses, or "
        "honest ignorance — not omniscient lore dumps — unless a structured "
        "Knowledge item on the sheet explicitly grants broader facts."
    )
    return "### Narrative scope\n" + "\n".join(chunks) + "\n\n" + rules + "\n"


def filter_npcs_by_scope_tags(
    npcs: list[NpcSheet],
    tags: list[str] | None,
    *,
    include_unscoped: bool = False,
) -> list[NpcSheet]:
    """Keep NPCs whose ``scope_tags`` intersect ``tags``.

    When ``tags`` is empty or None, returns ``npcs`` unchanged.
    """
    if not tags:
        return npcs
    allow = {t.strip() for t in tags if t.strip()}
    if not allow:
        return npcs
    out: list[NpcSheet] = []
    for npc in npcs:
        st = set(npc.scope_tags)
        if st & allow:
            out.append(npc)
            continue
        if include_unscoped and not npc.scope_tags:
            out.append(npc)
    return out
