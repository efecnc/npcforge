"""Project-level narrative preset — shapes NPC generation and walk-up tone.

Writers drop ``npcforge_project.yaml`` in the demo directory::

    narrative_preset: indie_minimal  # or rpg_standard, cinematic_rpg

CLI / tools may override with an explicit flag. When the file is missing,
``rpg_standard`` is used so existing projects behave as before.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml

NarrativePresetId = Literal["indie_minimal", "rpg_standard", "cinematic_rpg"]

PROJECT_FILE = "npcforge_project.yaml"

_VALID: set[str] = {"indie_minimal", "rpg_standard", "cinematic_rpg"}

DEFAULT_PRESET: NarrativePresetId = "rpg_standard"


def _coerce(raw: object) -> NarrativePresetId | None:
    if raw is None:
        return None
    if isinstance(raw, str) and raw.strip() in _VALID:
        return raw.strip()  # type: ignore[return-value]
    return None


def load_narrative_preset_file(demo_dir: Path) -> NarrativePresetId | None:
    """Return preset from ``npcforge_project.yaml`` if valid; else ``None``."""
    path = demo_dir / PROJECT_FILE
    if not path.exists():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return None
    return _coerce(data.get("narrative_preset"))


def load_effective_narrative_preset(
    demo_dir: Path,
    override: str | None,
) -> NarrativePresetId:
    """Resolve preset: CLI override wins, then project file, then default.

    Delegates to :func:`project_config.load_project_config` so ``topology`` /
    ``depth`` in ``npcforge_project.yaml`` stay in sync with the three legacy
    prompt packs.
    """
    from .project_config import load_project_config

    o = str(override).strip() if override is not None else None
    o = o or None
    return load_project_config(
        demo_dir,
        narrative_preset_override=o,
    ).legacy_narrative_preset_id()


def npc_generation_addon(preset: NarrativePresetId) -> str:
    """Extra system rules for ``gen_npcs`` / stub resolution."""
    if preset == "indie_minimal":
        return (
            "NARRATIVE PRESET: indie_minimal (small-team shipping focus)\n"
            "- Keep sheets lean: at most 2 motivations, 2 speech_quirks, "
            "3 sample_lines.\n"
            "- allowed_intents: pick 4–6 that cover shop talk, local rumour, "
            "quest hook, and farewell — skip rare social axes unless the brief "
            "demands them.\n"
            "- background: 2–4 short sentences; secret: one concrete sentence.\n"
            "- Do NOT pad with extra archetypes; one clear hook beats a cast bible.\n"
        )
    if preset == "cinematic_rpg":
        return (
            "NARRATIVE PRESET: cinematic_rpg (cast-first, higher detail)\n"
            "- Richer voice: up to 4 sentences with rhythm, subtext, and verbal tics.\n"
            "- 3–4 motivations; 3–4 speech_quirks; 4 sample_lines that sound distinct.\n"
            "- allowed_intents: 6–10 where the role justifies breadth (investigation, "
            "politics, intimacy, intimidation).\n"
            "- background may run longer if it seeds future scenes; secret stays one "
            "sharp fact the NPC would never say outright.\n"
        )
    # rpg_standard
    return (
        "NARRATIVE PRESET: rpg_standard (balanced CRPG / adventure cast)\n"
        "- Follow the base NPC rules as written; aim for 4–8 allowed_intents.\n"
        "- 2–4 motivations; 2–3 speech_quirks; 3–4 sample_lines.\n"
        "- Voice stays the anchor; relationships/knowledge stay optional unless "
        "the brief implies a named tie to the existing cast.\n"
    )


def dialogue_respondent_addon(preset: NarrativePresetId) -> str:
    """Appended to the walk-up respondent system prompt (build_npc_respondent)."""
    if preset == "indie_minimal":
        return (
            "PRESET DIALOGUE STYLE (indie_minimal)\n"
            "- Keep each assistant turn short (1–3 sentences) unless the player "
            "asks for depth.\n"
            "- Prefer concrete props and local colour over lore dumps.\n"
            "- End beats cleanly; avoid cliffhanger stacking in one branch.\n"
        )
    if preset == "cinematic_rpg":
        return (
            "PRESET DIALOGUE STYLE (cinematic_rpg)\n"
            "- Allow slightly longer beats when emotion or subtext warrants it.\n"
            "- Let silence, deflection, and implication carry weight — not every "
            "question deserves a full answer in one turn.\n"
            "- Honour voice shifts from arc / state when present.\n"
        )
    return (
        "PRESET DIALOGUE STYLE (rpg_standard)\n"
        "- Balance clarity with character: answer the player's intent without "
        "exposition dumps.\n"
        "- Match vocabulary_ceiling and forbidden_words strictly.\n"
    )
