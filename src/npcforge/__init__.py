"""npcforge — branching NPC dialogue generator with Yarn Spinner export.

Powered by :mod:`afterimage`. Takes a world bible plus NPC character sheets
and produces game-engine-ready dialogue where every player archetype becomes
a different branch inside every NPC's Yarn node.
"""

from .schemas import (
    NpcSheet,
    PlayerArchetype,
    load_archetypes,
    load_npcs,
    load_world_bible,
)
from .pipeline import (
    Branch,
    generate_branch,
    generate_for_npc,
    run_all,
)
from .prompts import (
    build_npc_respondent_prompt,
    render_character_sheet,
    render_player_archetype,
)
from .yarn import (
    render_world_start_node,
    render_yarn_branch,
    render_yarn_node_for_npc,
    yarn_escape_line,
    yarn_safe_title,
)

__version__ = "0.1.0"

__all__ = [
    "NpcSheet",
    "PlayerArchetype",
    "Branch",
    "load_archetypes",
    "load_npcs",
    "load_world_bible",
    "generate_branch",
    "generate_for_npc",
    "run_all",
    "build_npc_respondent_prompt",
    "render_character_sheet",
    "render_player_archetype",
    "render_world_start_node",
    "render_yarn_branch",
    "render_yarn_node_for_npc",
    "yarn_escape_line",
    "yarn_safe_title",
    "__version__",
]
