"""Agent-tool contracts.

Every feature npcforge exposes to the outside world is modelled here as a
typed async function: Pydantic input model in, Pydantic output model out.
This is the **single contract** the CLI and MCP server both call — no
feature lives only in the CLI.

Why this exists:
    - Agent frameworks (Claude, OpenAI tools, Cursor, Cline) can import and
      register these directly. Each tool has a JSON Schema courtesy of
      Pydantic.
    - The CLI is a thin dispatcher; its parsers convert argv to the input
      models and print the outputs.
    - The MCP server is a one-file wrapper that registers every tool by
      name.

Pattern for adding a new tool:
    1. Define ``<Name>Input`` and ``<Name>Output`` Pydantic models here.
    2. Implement ``async def <name>(input: <Name>Input) -> <Name>Output``
       here; delegate actual work to a feature module.
    3. Register the name in :data:`TOOL_REGISTRY` at the bottom of this file.
    4. Add a CLI subcommand in :mod:`npcforge.cli` and an MCP binding in
       :mod:`npcforge.mcp_server`.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal

from pydantic import BaseModel, Field

from .generation import (
    gen_barks as _gen_barks_impl,
    gen_intents as _gen_intents_impl,
    gen_npcs as _gen_npcs_impl,
    gen_repeat_greeting_node as _gen_repeat_greet_impl,
    gen_time_of_day_greetings as _gen_greetings_impl,
    resolve_stubs as _resolve_stubs_impl,
)
from .engines import SyncAction, SyncResult, get_adapter, supported_engines
from .manifest import Manifest
from .pipeline import run_all as _run_all_impl
from .state import ProjectVariable, VariableType, load_variables
from .schemas import (
    BarksConfig,
    BarkTrigger,
    NpcSheet,
    NpcStub,
    PlayerIntent,
    load_barks_config,
    load_intents,
    load_npcs,
    load_npcs_with_stubs,
    load_world_bible,
    resolve_intents_for_npc,
)
from .world_profile import (
    WorldProfile,
    cache_path_for,
    infer_world_profile as _infer_world_profile_impl,
    load_cached_profile,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared model-provider options
# ---------------------------------------------------------------------------


class _LLMOptions(BaseModel):
    """Fields shared by every tool that calls an LLM."""

    api_key: str = Field(..., description="LLM provider API key.")
    provider: Literal["gemini", "openai", "deepseek", "openrouter", "local"] = Field(
        default="gemini",
        description="LLM provider for this invocation.",
    )
    model: str | None = Field(
        default=None,
        description="Model name override; falls back to afterimage's default.",
    )


# ---------------------------------------------------------------------------
# Tool 1: infer_world_profile
# ---------------------------------------------------------------------------


class InferWorldProfileInput(_LLMOptions):
    """Infer (or refresh) the world profile cache from ``lore/*.md``."""

    demo_dir: Path = Field(..., description="Project directory (contains lore/).")
    overwrite_cache: bool = Field(
        default=False,
        description=(
            "When true, ignore an existing .npcforge/world_profile.json and "
            "re-run the inference. Otherwise returns the cached value."
        ),
    )


class InferWorldProfileOutput(BaseModel):
    profile: WorldProfile
    cache_path: Path = Field(
        ..., description="Where the inferred profile was written."
    )
    cache_hit: bool = Field(
        ...,
        description="True when the cached profile was returned without an LLM call.",
    )


async def infer_world_profile(input: InferWorldProfileInput) -> InferWorldProfileOutput:
    """Run inference if needed, return the profile plus cache status."""
    pre_cached = load_cached_profile(input.demo_dir)
    cache_hit = pre_cached is not None and not input.overwrite_cache
    profile = await _infer_world_profile_impl(
        demo_dir=input.demo_dir,
        api_key=input.api_key,
        provider=input.provider,
        model=input.model,
        overwrite_cache=input.overwrite_cache,
    )
    return InferWorldProfileOutput(
        profile=profile,
        cache_path=cache_path_for(input.demo_dir),
        cache_hit=cache_hit,
    )


# ---------------------------------------------------------------------------
# Tool 2: show_world_profile (no LLM)
# ---------------------------------------------------------------------------


class ShowWorldProfileInput(BaseModel):
    """Read-only view of the cached world profile."""

    demo_dir: Path = Field(..., description="Project directory.")


class ShowWorldProfileOutput(BaseModel):
    profile: WorldProfile | None = Field(
        default=None,
        description="Null when no cached profile exists yet.",
    )
    cache_path: Path
    exists: bool


async def show_world_profile(input: ShowWorldProfileInput) -> ShowWorldProfileOutput:
    """Return the cached profile without calling the LLM."""
    profile = load_cached_profile(input.demo_dir)
    return ShowWorldProfileOutput(
        profile=profile,
        cache_path=cache_path_for(input.demo_dir),
        exists=profile is not None,
    )


# ---------------------------------------------------------------------------
# Tool 3: list_npcs (no LLM)
# ---------------------------------------------------------------------------


class ListNpcsInput(BaseModel):
    demo_dir: Path = Field(..., description="Project directory.")


class ListNpcsOutput(BaseModel):
    npcs: list[NpcSheet]
    count: int


async def list_npcs(input: ListNpcsInput) -> ListNpcsOutput:
    path = input.demo_dir / "characters.yaml"
    npcs = load_npcs(path) if path.exists() else []
    return ListNpcsOutput(npcs=npcs, count=len(npcs))


# ---------------------------------------------------------------------------
# Tool 4: gen_npcs
# ---------------------------------------------------------------------------


class GenNpcsInput(_LLMOptions):
    """Generate new NPCs and append them to ``characters.yaml``."""

    demo_dir: Path = Field(..., description="Project directory.")
    n: int = Field(
        default=5,
        ge=1,
        le=25,
        description="How many NPCs to generate when ``roles`` is empty.",
    )
    brief: str | None = Field(
        default=None,
        description=(
            "Free-text description of the cast or specific NPC. Applied to "
            "every generated NPC when ``roles`` is empty, or combined with "
            "each role when ``roles`` is given."
        ),
    )
    roles: list[str] = Field(
        default_factory=list,
        description=(
            "Optional list of role descriptions — one NPC per role. When "
            "provided, len(roles) wins over ``n``."
        ),
    )
    append: bool = Field(
        default=True,
        description=(
            "When true (default), append generated NPCs to characters.yaml "
            "and return them. When false, return without writing so the "
            "caller can review first."
        ),
    )
    concurrency: int = Field(
        default=3,
        ge=1,
        le=8,
        description="Max parallel LLM calls while generating the cast.",
    )


class GenNpcsOutput(BaseModel):
    added: list[NpcSheet] = Field(
        ..., description="Newly generated NPCs (also written to characters.yaml)."
    )
    existing_count: int = Field(
        ...,
        description="How many NPCs were already in characters.yaml at call time.",
    )
    characters_yaml: Path
    wrote: bool


async def gen_npcs(input: GenNpcsInput) -> GenNpcsOutput:
    """Infer / load the world profile, generate NPCs, append to disk."""
    # Reuse the profile cache when present; refresh on demand only.
    profile = load_cached_profile(input.demo_dir)
    if profile is None:
        profile = await _infer_world_profile_impl(
            demo_dir=input.demo_dir,
            api_key=input.api_key,
            provider=input.provider,
            model=input.model,
            overwrite_cache=False,
        )

    world_bible = load_world_bible(input.demo_dir / "lore")
    intents_path = input.demo_dir / "player_intents.yaml"
    intent_ids = (
        [i.id for i in load_intents(intents_path)] if intents_path.exists() else []
    )
    characters_yaml = input.demo_dir / "characters.yaml"
    existing_count = len(load_npcs(characters_yaml)) if characters_yaml.exists() else 0

    added = await _gen_npcs_impl(
        demo_dir=input.demo_dir,
        profile=profile,
        world_bible=world_bible,
        api_key=input.api_key,
        n=input.n,
        brief=input.brief,
        roles=input.roles,
        intent_ids=intent_ids,
        provider=input.provider,
        model=input.model,
        concurrency=input.concurrency,
        append=input.append,
    )
    return GenNpcsOutput(
        added=added,
        existing_count=existing_count,
        characters_yaml=characters_yaml,
        wrote=input.append and bool(added),
    )


# ---------------------------------------------------------------------------
# Tool 5: gen_intents
# ---------------------------------------------------------------------------


class GenIntentsInput(_LLMOptions):
    """Generate new player intents and append them to ``player_intents.yaml``."""

    demo_dir: Path = Field(..., description="Project directory.")
    n: int = Field(default=8, ge=1, le=30)
    brief: str | None = Field(
        default=None,
        description="Optional free-text description of the intents you want.",
    )
    append: bool = Field(
        default=True,
        description="Write results to player_intents.yaml. False returns only.",
    )
    concurrency: int = Field(default=3, ge=1, le=8)


class GenIntentsOutput(BaseModel):
    added: list[PlayerIntent]
    existing_count: int
    intents_yaml: Path
    wrote: bool


async def gen_intents(input: GenIntentsInput) -> GenIntentsOutput:
    profile = load_cached_profile(input.demo_dir)
    if profile is None:
        profile = await _infer_world_profile_impl(
            demo_dir=input.demo_dir,
            api_key=input.api_key,
            provider=input.provider,
            model=input.model,
            overwrite_cache=False,
        )
    intents_yaml = input.demo_dir / "player_intents.yaml"
    existing_count = len(load_intents(intents_yaml)) if intents_yaml.exists() else 0

    added = await _gen_intents_impl(
        demo_dir=input.demo_dir,
        profile=profile,
        api_key=input.api_key,
        n=input.n,
        brief=input.brief,
        provider=input.provider,
        model=input.model,
        concurrency=input.concurrency,
        append=input.append,
    )
    return GenIntentsOutput(
        added=added,
        existing_count=existing_count,
        intents_yaml=intents_yaml,
        wrote=input.append and bool(added),
    )


# ---------------------------------------------------------------------------
# Tool 6: gen_barks (trigger proposals)
# ---------------------------------------------------------------------------


class GenBarksInput(_LLMOptions):
    """Generate new bark triggers for one or more NPCs.

    This produces trigger *proposals* — the (id, description, n) triples
    that feed ``build_pipeline --mode barks``. The actual 1-line bark
    utterances are still generated by the build pipeline.
    """

    demo_dir: Path = Field(..., description="Project directory.")
    only_npcs: list[str] = Field(
        default_factory=list,
        description=(
            "NPC ids to generate triggers for. Empty = every NPC in "
            "characters.yaml. Naming matches build_pipeline.only_npcs."
        ),
    )
    n_per_npc: int = Field(default=3, ge=1, le=15)
    brief: str | None = Field(
        default=None,
        description="Optional free-text hint about which triggers to focus on.",
    )
    append: bool = Field(
        default=True,
        description="Write results to barks.yaml. False returns only.",
    )
    concurrency: int = Field(default=3, ge=1, le=8)


class _NpcTriggersAdded(BaseModel):
    npc: str
    triggers: list[BarkTrigger]


class GenBarksOutput(BaseModel):
    added: list[_NpcTriggersAdded]
    barks_yaml: Path
    wrote: bool


async def gen_barks(input: GenBarksInput) -> GenBarksOutput:
    profile = load_cached_profile(input.demo_dir)
    if profile is None:
        profile = await _infer_world_profile_impl(
            demo_dir=input.demo_dir,
            api_key=input.api_key,
            provider=input.provider,
            model=input.model,
            overwrite_cache=False,
        )
    result = await _gen_barks_impl(
        demo_dir=input.demo_dir,
        profile=profile,
        api_key=input.api_key,
        for_npcs=input.only_npcs or None,
        n_per_npc=input.n_per_npc,
        brief=input.brief,
        provider=input.provider,
        model=input.model,
        concurrency=input.concurrency,
        append=input.append,
    )
    return GenBarksOutput(
        added=[_NpcTriggersAdded(npc=k, triggers=v) for k, v in result.items()],
        barks_yaml=input.demo_dir / "barks.yaml",
        wrote=input.append and bool(result),
    )


# ---------------------------------------------------------------------------
# Tool 7: resolve_stubs
# ---------------------------------------------------------------------------


class ResolveStubsInput(_LLMOptions):
    """Expand every ``_generate: true`` entry in characters.yaml into full sheets."""

    demo_dir: Path = Field(..., description="Project directory.")
    only_ids: list[str] = Field(
        default_factory=list,
        description=(
            "Restrict resolution to a subset of stub ids. Empty = resolve all."
        ),
    )
    write: bool = Field(
        default=True,
        description=(
            "Rewrite characters.yaml in place. False returns resolved sheets "
            "without touching the file."
        ),
    )
    concurrency: int = Field(default=3, ge=1, le=8)


class ResolveStubsOutput(BaseModel):
    resolved: list[NpcSheet]
    unresolved_ids: list[str]
    characters_yaml: Path
    wrote: bool


async def resolve_stubs(input: ResolveStubsInput) -> ResolveStubsOutput:
    profile = load_cached_profile(input.demo_dir)
    if profile is None:
        profile = await _infer_world_profile_impl(
            demo_dir=input.demo_dir,
            api_key=input.api_key,
            provider=input.provider,
            model=input.model,
            overwrite_cache=False,
        )
    world_bible = load_world_bible(input.demo_dir / "lore")
    intents_path = input.demo_dir / "player_intents.yaml"
    intent_ids = (
        [i.id for i in load_intents(intents_path)] if intents_path.exists() else []
    )

    resolved, unresolved = await _resolve_stubs_impl(
        demo_dir=input.demo_dir,
        profile=profile,
        world_bible=world_bible,
        api_key=input.api_key,
        only_ids=input.only_ids or None,
        intent_ids=intent_ids,
        provider=input.provider,
        model=input.model,
        concurrency=input.concurrency,
        write=input.write,
    )
    return ResolveStubsOutput(
        resolved=resolved,
        unresolved_ids=unresolved,
        characters_yaml=input.demo_dir / "characters.yaml",
        wrote=input.write and bool(resolved),
    )


# ---------------------------------------------------------------------------
# Tool 8: gen_greetings (state-aware time-of-day variants)
# ---------------------------------------------------------------------------


class GenGreetingsInput(_LLMOptions):
    """Generate one greeting per value of an enum variable, per NPC.

    The output is a per-NPC Yarn node that plays the right greeting based
    on the current value of the chosen project variable (most commonly
    ``time_of_day``). Drop ``variables.yaml`` in the project directory
    first — the tool requires a declared enum variable to key against.
    """

    demo_dir: Path = Field(..., description="Project directory.")
    variable_id: str = Field(
        default="time_of_day",
        description=(
            "Project-variable id to key greetings on. Must be declared in "
            "variables.yaml and must have type=enum."
        ),
    )
    only_npcs: list[str] = Field(
        default_factory=list,
        description=(
            "NPC ids to generate greetings for. Empty = every NPC in "
            "characters.yaml."
        ),
    )
    concurrency: int = Field(default=4, ge=1, le=8)
    write: bool = Field(
        default=True,
        description=(
            "Write greeting nodes to <demo_dir>/out/. False returns the "
            "variants without touching disk."
        ),
    )


class _NpcGreetingsAdded(BaseModel):
    npc: str
    variable_id: str
    variants: list[tuple[str, str]] = Field(
        default_factory=list,
        description="Ordered (variable_value, greeting_text) pairs.",
    )


class GenGreetingsOutput(BaseModel):
    added: list[_NpcGreetingsAdded]
    variable_id: str
    out_dir: Path
    wrote: bool


async def gen_greetings(input: GenGreetingsInput) -> GenGreetingsOutput:
    variables_cfg = load_variables(input.demo_dir / "variables.yaml")
    variable = next(
        (v for v in variables_cfg.variables if v.id == input.variable_id), None
    )
    if variable is None:
        raise ValueError(
            f"No variable '{input.variable_id}' in "
            f"{input.demo_dir / 'variables.yaml'}. Declare it first."
        )
    if variable.type != VariableType.ENUM:
        raise ValueError(
            f"Variable '{input.variable_id}' must be type=enum "
            f"(got {variable.type.value}). gen_greetings keys on enum values."
        )

    profile = load_cached_profile(input.demo_dir)
    if profile is None:
        profile = await _infer_world_profile_impl(
            demo_dir=input.demo_dir,
            api_key=input.api_key,
            provider=input.provider,
            model=input.model,
            overwrite_cache=False,
        )

    result = await _gen_greetings_impl(
        demo_dir=input.demo_dir,
        profile=profile,
        variable=variable,
        variables=variables_cfg.variables,
        npc_ids=input.only_npcs or None,
        api_key=input.api_key,
        provider=input.provider,
        model=input.model,
        concurrency=input.concurrency,
        write=input.write,
    )

    added = [
        _NpcGreetingsAdded(npc=npc_id, variable_id=input.variable_id, variants=variants)
        for npc_id, variants in result.items()
    ]
    return GenGreetingsOutput(
        added=added,
        variable_id=input.variable_id,
        out_dir=input.demo_dir / "out",
        wrote=input.write and bool(result),
    )


# ---------------------------------------------------------------------------
# Tool 9: gen_repeat_greeting (visit-count gated greetings)
# ---------------------------------------------------------------------------


class GenRepeatGreetingInput(_LLMOptions):
    """Generate visit-gated greeting variants for one or more NPCs.

    Emits a Yarn node keyed on ``visited_count()``: the first ``n-1``
    variants play on visits 0 .. n-2, and the final variant is an
    ``<<else>>`` fallback played on every subsequent visit.
    """

    demo_dir: Path = Field(..., description="Project directory.")
    n: int = Field(
        default=3,
        ge=2,
        le=8,
        description=(
            "Total number of greeting variants. Must be >= 2. Last variant "
            "is the else-fallback for all visits >= n-1."
        ),
    )
    only_npcs: list[str] = Field(
        default_factory=list,
        description="Restrict to a subset of NPC ids (default: all).",
    )
    concurrency: int = Field(default=4, ge=1, le=8)
    write: bool = Field(
        default=True,
        description=(
            "Write greeting nodes to <demo_dir>/out/. False returns only."
        ),
    )


class _NpcRepeatGreetingAdded(BaseModel):
    npc: str
    variants: list[str] = Field(default_factory=list)


class GenRepeatGreetingOutput(BaseModel):
    added: list[_NpcRepeatGreetingAdded]
    out_dir: Path
    wrote: bool


async def gen_repeat_greeting(input: GenRepeatGreetingInput) -> GenRepeatGreetingOutput:
    profile = load_cached_profile(input.demo_dir)
    if profile is None:
        profile = await _infer_world_profile_impl(
            demo_dir=input.demo_dir,
            api_key=input.api_key,
            provider=input.provider,
            model=input.model,
            overwrite_cache=False,
        )

    result = await _gen_repeat_greet_impl(
        demo_dir=input.demo_dir,
        profile=profile,
        api_key=input.api_key,
        n=input.n,
        npc_ids=input.only_npcs or None,
        provider=input.provider,
        model=input.model,
        concurrency=input.concurrency,
        write=input.write,
    )

    added = [
        _NpcRepeatGreetingAdded(npc=npc_id, variants=variants)
        for npc_id, variants in result.items()
    ]
    return GenRepeatGreetingOutput(
        added=added,
        out_dir=input.demo_dir / "out",
        wrote=input.write and bool(result),
    )


# ---------------------------------------------------------------------------
# Tool 10: engine_sync (copy generated output into an engine's tree)
# ---------------------------------------------------------------------------


class EngineSyncInput(BaseModel):
    """Copy ``<demo_dir>/out/`` into a game engine's expected project layout."""

    demo_dir: Path = Field(
        ..., description="npcforge project directory. Must contain an out/ sibling."
    )
    project_dir: Path = Field(
        ...,
        description=(
            "Target engine project root. For Unity this is the folder that "
            "contains `Assets/`; for Unreal the one with `Content/`; for "
            "Godot the folder with `project.godot`."
        ),
    )
    engine: Literal["unity", "godot", "unreal"] = Field(
        ..., description="Target engine."
    )
    source_dir: Path | None = Field(
        default=None,
        description=(
            "Override the source directory. Defaults to <demo_dir>/out. Use "
            "this to sync a frozen snapshot (e.g. sample_output/)."
        ),
    )
    install_scripts: bool = Field(
        default=False,
        description=(
            "Also copy the engine's runtime glue scripts on first sync "
            "(currently Unity-only: the C# drop-in from "
            "examples/unity_integration)."
        ),
    )
    scripts_source_dir: Path | None = Field(
        default=None,
        description=(
            "Override the source directory for runtime glue scripts. Default "
            "is discovered from the repo checkout."
        ),
    )
    dry_run: bool = Field(
        default=False,
        description="Plan the sync without writing anything.",
    )


class _SyncActionOut(BaseModel):
    action: str
    destination: str
    source: str | None = None
    reason: str = ""


class EngineSyncOutput(BaseModel):
    engine: str
    project_dir: Path
    source_dir: Path
    dry_run: bool
    marker_path: Path | None
    total_files: int
    actions: list[_SyncActionOut]
    errors: list[str] = Field(default_factory=list)


def _action_to_out(action: SyncAction) -> _SyncActionOut:
    return _SyncActionOut(
        action=action.action,
        destination=str(action.destination),
        source=str(action.source) if action.source else None,
        reason=action.reason,
    )


async def engine_sync(input: EngineSyncInput) -> EngineSyncOutput:
    adapter = get_adapter(input.engine)
    source_dir = input.source_dir or (input.demo_dir / "out")
    result = adapter.sync(
        source_out_dir=source_dir,
        project_dir=input.project_dir,
        install_scripts=input.install_scripts,
        scripts_source_dir=input.scripts_source_dir,
        dry_run=input.dry_run,
    )
    return EngineSyncOutput(
        engine=result.engine,
        project_dir=input.project_dir,
        source_dir=source_dir,
        dry_run=result.dry_run,
        marker_path=result.marker_path,
        total_files=result.total_files,
        actions=[_action_to_out(a) for a in result.actions],
        errors=list(result.errors),
    )


# ---------------------------------------------------------------------------
# Tool 11: build_pipeline (walk_up + barks)
# ---------------------------------------------------------------------------


class BuildPipelineInput(_LLMOptions):
    """Run the full walk-up / barks pipeline for a project."""

    demo_dir: Path = Field(..., description="Project directory.")
    mode: Literal["walk_up", "barks", "all"] = Field(
        default="walk_up", description="Which stage(s) to run."
    )
    only_npcs: list[str] = Field(
        default_factory=list,
        description="Restrict to a subset of NPC ids (default: all).",
    )
    max_turns: int = Field(default=3, ge=1, le=12)
    intent_concurrency: int = Field(default=3, ge=1, le=8)
    bark_concurrency: int = Field(default=4, ge=1, le=8)
    score_voice: bool = Field(
        default=False,
        description=(
            "Opt-in per-branch voice-consistency score (embedding distance "
            "between assistant turns and sample_lines). Adds one batched "
            "embedding call per NPC; surfaced in manifest.json."
        ),
    )
    out_dir: Path | None = Field(
        default=None,
        description="Output directory. Defaults to <demo_dir>/out.",
    )


class BuildPipelineOutput(BaseModel):
    manifest: Manifest
    out_dir: Path


async def build_pipeline(input: BuildPipelineInput) -> BuildPipelineOutput:
    npcs = load_npcs(input.demo_dir / "characters.yaml")
    intents = load_intents(input.demo_dir / "player_intents.yaml")
    barks_cfg = load_barks_config(input.demo_dir / "barks.yaml")
    variables_cfg = load_variables(input.demo_dir / "variables.yaml")
    world_bible = load_world_bible(input.demo_dir / "lore")
    out_dir = input.out_dir or (input.demo_dir / "out")
    manifest = await _run_all_impl(
        npcs=npcs,
        intents=intents,
        world_bible=world_bible,
        api_key=input.api_key,
        out_dir=out_dir,
        barks_config=barks_cfg,
        variables=variables_cfg.variables,
        mode=input.mode,
        only_npcs=input.only_npcs or None,
        model_provider_name=input.provider,
        model_name=input.model,
        max_turns=input.max_turns,
        intent_concurrency=input.intent_concurrency,
        bark_concurrency=input.bark_concurrency,
        score_voice=input.score_voice,
        progress=False,
    )
    return BuildPipelineOutput(manifest=manifest, out_dir=out_dir)


# ---------------------------------------------------------------------------
# Registry — the agent surface
# ---------------------------------------------------------------------------


class ToolSpec(BaseModel):
    """Metadata for one tool in the registry."""

    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]


def _spec(
    name: str,
    description: str,
    input_model: type[BaseModel],
    output_model: type[BaseModel],
) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=description.strip(),
        input_schema=input_model.model_json_schema(),
        output_schema=output_model.model_json_schema(),
    )


ToolFn = Callable[[BaseModel], Awaitable[BaseModel]]

# name -> (async fn, Input class, Output class, description)
TOOL_REGISTRY: dict[str, tuple[ToolFn, type[BaseModel], type[BaseModel], str]] = {
    "infer_world_profile": (
        infer_world_profile,
        InferWorldProfileInput,
        InferWorldProfileOutput,
        """Infer or refresh the world profile from lore/*.md. Runs one LLM
        structured call and caches to <demo_dir>/.npcforge/world_profile.json
        unless a cache is already present (and overwrite_cache is false).""",
    ),
    "show_world_profile": (
        show_world_profile,
        ShowWorldProfileInput,
        ShowWorldProfileOutput,
        """Return the cached world profile without calling the LLM. Use this
        to check what npcforge currently understands about the setting.""",
    ),
    "list_npcs": (
        list_npcs,
        ListNpcsInput,
        ListNpcsOutput,
        """Read-only view of the NPCs currently declared in characters.yaml.""",
    ),
    "gen_npcs": (
        gen_npcs,
        GenNpcsInput,
        GenNpcsOutput,
        """Generate new NPC sheets from lore + brief (+ optional roles) and
        append them to characters.yaml. Additive: existing entries are never
        modified. Caller can set append=false to review before persisting.""",
    ),
    "gen_intents": (
        gen_intents,
        GenIntentsInput,
        GenIntentsOutput,
        """Generate new player intents consistent with the world and the
        existing intent catalogue. Appended to player_intents.yaml; existing
        entries are never modified. One LLM call per intent.""",
    ),
    "gen_barks": (
        gen_barks,
        GenBarksInput,
        GenBarksOutput,
        """Generate bark trigger proposals (id + situational description + n)
        for one or more NPCs. Appended to barks.yaml. Actual bark lines are
        still produced by build_pipeline --mode barks.""",
    ),
    "resolve_stubs": (
        resolve_stubs,
        ResolveStubsInput,
        ResolveStubsOutput,
        """Expand every _generate: true entry in characters.yaml into a full
        NpcSheet. Honours role_hint / voice_hint / name seeds. Rewrites the
        yaml in place unless write=false.""",
    ),
    "gen_greetings": (
        gen_greetings,
        GenGreetingsInput,
        GenGreetingsOutput,
        """Generate one greeting per value of an enum project variable
        (typically time_of_day), per NPC. Emits a per-NPC Yarn node with
        an <<if>> chain keyed on the variable — the first state-aware
        output npcforge produces. Requires a variables.yaml declaring the
        chosen variable.""",
    ),
    "gen_repeat_greeting": (
        gen_repeat_greeting,
        GenRepeatGreetingInput,
        GenRepeatGreetingOutput,
        """Generate visit-count-gated greeting variants for one or more
        NPCs. Emits a per-NPC Yarn node keyed on visited_count(): visits
        0..n-2 play distinct greetings; the final variant is an <<else>>
        fallback for every subsequent visit. No schema changes required.""",
    ),
    "engine_sync": (
        engine_sync,
        EngineSyncInput,
        EngineSyncOutput,
        """Copy the generated dialogue + lines.csv from <demo_dir>/out into
        a game engine's expected project layout (Unity, Godot, Unreal).
        Skips files whose contents are unchanged; writes a
        .npcforge-sync.json marker so subsequent runs are incremental.
        Optionally installs the engine's runtime glue scripts on first
        sync (Unity only as of v0.7.1).""",
    ),
    "build_pipeline": (
        build_pipeline,
        BuildPipelineInput,
        BuildPipelineOutput,
        """Run the walk-up / bark / all pipeline for a project. Writes Yarn
        files, a lint report, and a manifest.json into out/.""",
    ),
}


def list_tool_specs() -> list[ToolSpec]:
    """Return a JSON-Schema-ready description of every registered tool."""
    return [
        _spec(name, desc, in_model, out_model)
        for name, (_, in_model, out_model, desc) in TOOL_REGISTRY.items()
    ]
