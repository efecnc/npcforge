"""Per-project narrative knobs: topology, depth, experimental flags.

Reads ``npcforge_project.yaml`` beside ``characters.yaml``. Backward
compatible with the legacy ``narrative_preset``-only file — that key still
maps to sensible ``topology`` + ``depth`` when the new keys are absent.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

TopologyId = Literal[
    "ambient_indie",
    "quest_rpg",
    "open_world_systemic",
    "cinematic_adventure",
    "social_sim",
    "immersive_sim",
]

DepthId = Literal["lean", "standard", "cinematic"]

TOPOLOGY_IDS: frozenset[str] = frozenset(
    (
        "ambient_indie",
        "quest_rpg",
        "open_world_systemic",
        "cinematic_adventure",
        "social_sim",
        "immersive_sim",
    )
)
DEPTH_IDS: frozenset[str] = frozenset(("lean", "standard", "cinematic"))

PROJECT_FILE = "npcforge_project.yaml"

# Legacy narrative_preset → (topology, depth)
_LEGACY_MAP: dict[str, tuple[str, str]] = {
    "indie_minimal": ("ambient_indie", "lean"),
    "rpg_standard": ("quest_rpg", "standard"),
    "cinematic_rpg": ("cinematic_adventure", "cinematic"),
}


@dataclass(frozen=True)
class ProjectConfig:
    """Resolved project-level narrative configuration."""

    topology: TopologyId
    depth: DepthId
    experimental: tuple[str, ...]
    review_workflow: bool

    def legacy_narrative_preset_id(self) -> Literal["indie_minimal", "rpg_standard", "cinematic_rpg"]:
        """Map depth (and topology hint) to the three legacy prompt packs."""
        if self.depth == "lean":
            return "indie_minimal"
        if self.depth == "cinematic":
            return "cinematic_rpg"
        return "rpg_standard"


def _coerce_topology(raw: object) -> str | None:
    if isinstance(raw, str) and raw.strip() in TOPOLOGY_IDS:
        return raw.strip()
    return None


def _coerce_depth(raw: object) -> str | None:
    if isinstance(raw, str) and raw.strip() in DEPTH_IDS:
        return raw.strip()
    return None


def _parse_experimental(raw: object) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, list):
        return tuple(str(x).strip() for x in raw if str(x).strip())
    return ()


def load_project_config(
    demo_dir: Path,
    *,
    narrative_preset_override: str | None = None,
    topology_override: str | None = None,
    depth_override: str | None = None,
) -> ProjectConfig:
    """Load ``npcforge_project.yaml`` with CLI overrides.

    Precedence: per-field CLI override > YAML field > legacy ``narrative_preset``
    mapping > defaults (``quest_rpg`` + ``standard``).
    """
    path = demo_dir / PROJECT_FILE
    data: dict = {}
    if path.exists():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if isinstance(loaded, dict):
            data = loaded

    legacy = None
    if isinstance(data.get("narrative_preset"), str):
        legacy = data["narrative_preset"].strip()
        if legacy and legacy not in _LEGACY_MAP:
            legacy = None

    topo: str | None = None
    depth: str | None = None

    if topology_override and str(topology_override).strip():
        t = str(topology_override).strip()
        if t not in TOPOLOGY_IDS:
            raise ValueError(
                f"Unknown topology {t!r}. Use one of: {', '.join(sorted(TOPOLOGY_IDS))}."
            )
        topo = t
    else:
        topo = _coerce_topology(data.get("topology"))

    if depth_override and str(depth_override).strip():
        d = str(depth_override).strip()
        if d not in DEPTH_IDS:
            raise ValueError(
                f"Unknown depth {d!r}. Use one of: {', '.join(sorted(DEPTH_IDS))}."
            )
        depth = d
    else:
        depth = _coerce_depth(data.get("depth"))

    # Legacy narrative_preset from CLI (highest priority for old flag)
    if narrative_preset_override and str(narrative_preset_override).strip():
        key = str(narrative_preset_override).strip()
        if key not in _LEGACY_MAP:
            raise ValueError(
                f"Unknown narrative_preset {key!r}. "
                f"Use one of: {', '.join(sorted(_LEGACY_MAP))}."
            )
        lt, ld = _LEGACY_MAP[key]
        if topo is None:
            topo = lt
        if depth is None:
            depth = ld
    elif legacy and legacy in _LEGACY_MAP:
        lt, ld = _LEGACY_MAP[legacy]
        if topo is None:
            topo = lt
        if depth is None:
            depth = ld

    if topo is None:
        topo = "quest_rpg"
    if depth is None:
        depth = "standard"

    experimental = _parse_experimental(data.get("experimental"))
    rw = data.get("review_workflow", False)
    review_workflow = bool(rw) if isinstance(rw, (bool, int)) else False

    return ProjectConfig(
        topology=topo,  # type: ignore[arg-type]
        depth=depth,  # type: ignore[arg-type]
        experimental=experimental,
        review_workflow=review_workflow,
    )


def depth_writer_addon(depth: DepthId) -> str:
    """Extra system guidance for narrative depth (detail / beat length)."""
    if depth == "lean":
        return (
            "DEPTH: lean — minimal sheet bulk, short dialogue beats, "
            "shipping-first cast discipline."
        )
    if depth == "cinematic":
        return (
            "DEPTH: cinematic — richer detail where it serves scenes; "
            "dialogue may breathe with subtext and pacing."
        )
    return (
        "DEPTH: standard — balanced detail for a typical adventure / CRPG cast."
    )


def npc_generation_prompt_suffix(cfg: ProjectConfig) -> str:
    """Full narrative addon block for NPC sheet generation / stub resolution."""
    from .narrative_preset import npc_generation_addon

    preset = cfg.legacy_narrative_preset_id()
    return (
        f"{npc_generation_addon(preset)}\n\n"
        f"{topology_writer_addon(cfg.topology)}\n\n"
        f"{depth_writer_addon(cfg.depth)}"
    )


def dialogue_respondent_prompt_suffix(cfg: ProjectConfig) -> str:
    """Full style addon for walk-up respondent prompts."""
    from .narrative_preset import dialogue_respondent_addon

    preset = cfg.legacy_narrative_preset_id()
    return (
        f"{dialogue_respondent_addon(preset)}\n\n"
        f"{topology_writer_addon(cfg.topology)}\n\n"
        f"{depth_writer_addon(cfg.depth)}"
    )


def topology_writer_addon(topology: TopologyId) -> str:
    """Extra system guidance keyed by narrative topology (production shape)."""
    guides: dict[str, str] = {
        "ambient_indie": (
            "TOPOLOGY: ambient_indie — small cast, low plot pressure, slice-of-life. "
            "Favour grounded banter, repeatable beats, and low spoiler surface."
        ),
        "quest_rpg": (
            "TOPOLOGY: quest_rpg — hub NPCs, quest hooks, clear player verbs. "
            "Each NPC should earn their screen time with a role in the player's goals."
        ),
        "open_world_systemic": (
            "TOPOLOGY: open_world_systemic — many NPCs, light touch per encounter. "
            "Avoid unique backstory dumps unless the brief marks a spotlight NPC."
        ),
        "cinematic_adventure": (
            "TOPOLOGY: cinematic_adventure — scene-led, subtext-heavy. "
            "Voice and dramatic tension outweigh lore quantity."
        ),
        "social_sim": (
            "TOPOLOGY: social_sim — relationship and schedule-driven. "
            "NPCs should feel habitual; intents skew social/economic."
        ),
        "immersive_sim": (
            "TOPOLOGY: immersive_sim — player agency, environmental storytelling. "
            "NPCs hint at systems without explaining them; deflect to in-world voice."
        ),
    }
    return guides.get(topology, guides["quest_rpg"])
