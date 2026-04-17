"""npcforge — branching NPC dialogue + bark libraries for Yarn Spinner.

Powered by :mod:`afterimage`. v0.2.0 adds bark generation, player intents
(finer-grained than archetypes), voice-ceiling constraints, a content manifest,
a lint report, and optional ``ysc`` compile validation.
"""

from .lint import ForbiddenHit, LintReport, lint_barks, lint_text, lint_walk_up_branches
from .pipeline import (
    Mode,
    generate_barks_for_npc_trigger,
    generate_branch,
    generate_for_npc,
    run_all,
)
from .prompts import (
    build_bark_respondent_prompt,
    build_npc_respondent_prompt,
    render_character_sheet,
    render_player_intent,
)
from .schemas import (
    BarkLine,
    BarksConfig,
    BarkTrigger,
    NpcBarkConfig,
    NpcSheet,
    PlayerIntent,
    VocabularyCeiling,
    load_barks_config,
    load_intents,
    load_npcs,
    load_world_bible,
    resolve_intents_for_npc,
)
from .validate import CompileResult, compile_yarn_files, ysc_available
from .yarn import (
    Branch,
    DialogTurn,
    bark_node_title,
    render_bark_node,
    render_world_start_node,
    render_yarn_branch,
    render_yarn_node_for_npc,
    yarn_escape_line,
    yarn_safe_title,
)

__version__ = "0.2.0"

__all__ = [
    # types
    "NpcSheet",
    "PlayerIntent",
    "VocabularyCeiling",
    "BarkLine",
    "BarkTrigger",
    "NpcBarkConfig",
    "BarksConfig",
    "Branch",
    "DialogTurn",
    "ForbiddenHit",
    "LintReport",
    "CompileResult",
    "Mode",
    # loaders
    "load_npcs",
    "load_intents",
    "load_barks_config",
    "load_world_bible",
    "resolve_intents_for_npc",
    # pipeline
    "generate_branch",
    "generate_for_npc",
    "generate_barks_for_npc_trigger",
    "run_all",
    # prompts
    "build_npc_respondent_prompt",
    "build_bark_respondent_prompt",
    "render_character_sheet",
    "render_player_intent",
    # yarn
    "render_world_start_node",
    "render_yarn_branch",
    "render_yarn_node_for_npc",
    "render_bark_node",
    "bark_node_title",
    "yarn_escape_line",
    "yarn_safe_title",
    # lint
    "lint_text",
    "lint_walk_up_branches",
    "lint_barks",
    # validate
    "ysc_available",
    "compile_yarn_files",
    "__version__",
]
