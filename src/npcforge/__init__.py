"""npcforge — NPC dialogue + bark libraries + cast generation, agent-ready.

v0.3.0 introduces a tools layer (:mod:`npcforge.tools`) with typed Pydantic
contracts. Every capability — world-profile inference, NPC generation, the
walk-up/bark pipeline — is exposed as a single async function that the CLI
and the MCP server both call. Agent frameworks can import and register
these directly.
"""

from .generation import append_npcs_to_yaml, gen_npcs as gen_npcs_impl
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
from .tools import (
    TOOL_REGISTRY,
    BuildPipelineInput,
    BuildPipelineOutput,
    GenNpcsInput,
    GenNpcsOutput,
    InferWorldProfileInput,
    InferWorldProfileOutput,
    ListNpcsInput,
    ListNpcsOutput,
    ShowWorldProfileInput,
    ShowWorldProfileOutput,
    ToolSpec,
    build_pipeline,
    gen_npcs,
    infer_world_profile,
    list_npcs,
    list_tool_specs,
    show_world_profile,
)
from .validate import CompileResult, compile_yarn_files, ysc_available
from .world_profile import (
    WorldProfile,
    cache_path_for,
    format_profile_for_prompt,
    load_cached_profile,
    save_profile,
)
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

__version__ = "0.3.0"

__all__ = [
    # Version
    "__version__",
    # Schemas
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
    "WorldProfile",
    # Loaders
    "load_npcs",
    "load_intents",
    "load_barks_config",
    "load_world_bible",
    "resolve_intents_for_npc",
    "load_cached_profile",
    "save_profile",
    "cache_path_for",
    "format_profile_for_prompt",
    # Tools layer (agent contracts)
    "TOOL_REGISTRY",
    "ToolSpec",
    "list_tool_specs",
    "InferWorldProfileInput",
    "InferWorldProfileOutput",
    "ShowWorldProfileInput",
    "ShowWorldProfileOutput",
    "ListNpcsInput",
    "ListNpcsOutput",
    "GenNpcsInput",
    "GenNpcsOutput",
    "BuildPipelineInput",
    "BuildPipelineOutput",
    "infer_world_profile",
    "show_world_profile",
    "list_npcs",
    "gen_npcs",
    "build_pipeline",
    # Generation (library)
    "gen_npcs_impl",
    "append_npcs_to_yaml",
    # Pipeline
    "generate_branch",
    "generate_for_npc",
    "generate_barks_for_npc_trigger",
    "run_all",
    # Prompts
    "build_npc_respondent_prompt",
    "build_bark_respondent_prompt",
    "render_character_sheet",
    "render_player_intent",
    # Yarn
    "render_world_start_node",
    "render_yarn_branch",
    "render_yarn_node_for_npc",
    "render_bark_node",
    "bark_node_title",
    "yarn_escape_line",
    "yarn_safe_title",
    # Lint
    "lint_text",
    "lint_walk_up_branches",
    "lint_barks",
    # Validate
    "ysc_available",
    "compile_yarn_files",
]
