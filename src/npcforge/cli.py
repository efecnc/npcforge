"""Command-line entrypoint for npcforge.

Subcommand-based CLI that is a thin dispatcher over :mod:`npcforge.tools`.
Every subcommand builds a tool input model, calls the tool, and renders the
output. Business logic lives in ``tools.py``; this file is pure plumbing.

Subcommands:

    npcforge build           walk-up / bark pipeline (writes .yarn + manifest)
    npcforge world infer     infer the world profile from lore/*.md
    npcforge world show      print the cached world profile
    npcforge list-npcs       list NPCs currently in characters.yaml
    npcforge gen npcs        generate new NPCs (additive)
    npcforge mcp             start the MCP server (stdio transport)

CLI breaking change from v0.2.x: the top-level flags now live under
``npcforge build``. ``npcforge --demo-dir X --mode all`` becomes
``npcforge build --demo-dir X --mode all``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from .game import GameConfig, run_game
from .play import play_barks, play_greetings, play_repeat_greeting, play_walk_up
from .tools import (
    BuildPipelineInput,
    EngineSyncInput,
    GenBarksInput,
    GenGreetingsInput,
    GenIntentsInput,
    GenNpcsInput,
    GenRepeatGreetingInput,
    InferWorldProfileInput,
    ListNpcsInput,
    ResolveStubsInput,
    ShowWorldProfileInput,
    build_pipeline,
    engine_sync,
    gen_barks,
    gen_greetings,
    gen_intents,
    gen_npcs,
    gen_repeat_greeting,
    infer_world_profile,
    list_npcs,
    resolve_stubs,
    show_world_profile,
)
from .project_config import TOPOLOGY_IDS
from .validate import compile_yarn_files, ysc_available
from .world_profile import format_profile_for_prompt


_DEFAULT_ENV = {
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "local": "LOCAL_API_KEY",
}


def _resolve_api_key(provider: str, env_override: str | None) -> str:
    env_name = env_override or _DEFAULT_ENV[provider]
    key = os.environ.get(env_name)
    if not key:
        raise SystemExit(
            f"Missing API key. Set the '{env_name}' environment variable "
            "(or pass --api-key-env)."
        )
    return key


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


def _add_topology_depth_flags(sub: argparse.ArgumentParser) -> None:
    """Optional overrides for ``npcforge_project.yaml`` topology / depth."""
    sub.add_argument(
        "--topology",
        default=None,
        choices=sorted(TOPOLOGY_IDS),
        help="Override npcforge_project.yaml topology for this run.",
    )
    sub.add_argument(
        "--depth",
        default=None,
        choices=["lean", "standard", "cinematic"],
        help="Override npcforge_project.yaml depth for this run.",
    )


def _add_llm_flags(sub: argparse.ArgumentParser) -> None:
    sub.add_argument(
        "--provider",
        default="gemini",
        choices=["gemini", "openai", "deepseek", "openrouter", "local"],
    )
    sub.add_argument("--model", default=None)
    sub.add_argument(
        "--api-key-env",
        default=None,
        help="Env var holding the API key (default: provider's canonical var).",
    )


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


async def _cmd_build(args: argparse.Namespace) -> int:
    key = _resolve_api_key(args.provider, args.api_key_env)
    input_ = BuildPipelineInput(
        demo_dir=args.demo_dir,
        mode=args.mode,
        only_npcs=_split_csv(args.only_npcs),
        only_scope_tags=_split_csv(args.only_scope_tags),
        include_unscoped=args.include_unscoped,
        max_turns=args.turns,
        intent_concurrency=args.intent_concurrency,
        bark_concurrency=args.bark_concurrency,
        score_voice=args.score_voice,
        out_dir=args.out,
        provider=args.provider,
        model=args.model,
        api_key=key,
        narrative_preset=args.narrative_preset,
        topology=args.topology,
        depth=args.depth,
    )

    if not args.quiet:
        print(
            f"build: mode={input_.mode} demo_dir={input_.demo_dir} "
            f"only_npcs={input_.only_npcs or 'all'} "
            f"only_scope_tags={input_.only_scope_tags or 'all'}"
        )

    result = await build_pipeline(input_)
    manifest = result.manifest
    if not args.quiet:
        print(
            f"done: elapsed={manifest.elapsed_seconds}s "
            f"lint_hits={manifest.lint.total_hits} out={result.out_dir}"
        )
        if manifest.voice_scoring_enabled:
            scored = [
                (nid, e.walk_up.voice_scores)
                for nid, e in manifest.npcs.items()
                if e.walk_up and e.walk_up.voice_scores
            ]
            for nid, scores in scored:
                avg = sum(scores.values()) / len(scores)
                print(f"voice[{nid}] avg={avg:.3f}  branches={len(scores)}")

    if not args.no_validate:
        v = compile_yarn_files(result.out_dir)
        if v.ran:
            print("ysc compile: " + ("OK" if v.ok else f"FAIL ({v.note})"))
            if v.stderr:
                print(v.stderr, file=sys.stderr)
        elif not ysc_available() and not args.quiet:
            print(f"Note: {v.note}")
    return 0


async def _cmd_world_infer(args: argparse.Namespace) -> int:
    key = _resolve_api_key(args.provider, args.api_key_env)
    result = await infer_world_profile(
        InferWorldProfileInput(
            demo_dir=args.demo_dir,
            overwrite_cache=args.refresh,
            provider=args.provider,
            model=args.model,
            api_key=key,
        )
    )
    tag = "cached" if result.cache_hit else "inferred"
    print(f"world profile ({tag}) -> {result.cache_path}")
    print(format_profile_for_prompt(result.profile))
    return 0


async def _cmd_world_show(args: argparse.Namespace) -> int:
    result = await show_world_profile(ShowWorldProfileInput(demo_dir=args.demo_dir))
    if not result.exists or result.profile is None:
        print(f"No cached profile at {result.cache_path}")
        print("Run 'npcforge world infer --demo-dir <dir>' first.")
        return 1
    if args.json:
        print(result.profile.model_dump_json(indent=2))
    else:
        print(format_profile_for_prompt(result.profile))
    return 0


async def _cmd_list_npcs(args: argparse.Namespace) -> int:
    result = await list_npcs(ListNpcsInput(demo_dir=args.demo_dir))
    if args.json:
        print(
            json.dumps(
                {
                    "count": result.count,
                    "npcs": [n.model_dump(exclude_none=True) for n in result.npcs],
                },
                indent=2,
            )
        )
        return 0
    if not result.npcs:
        print(f"No NPCs declared in {args.demo_dir}/characters.yaml.")
        return 0
    print(f"{result.count} NPC{'s' if result.count != 1 else ''}:")
    for npc in result.npcs:
        intents = ", ".join(npc.allowed_intents) if npc.allowed_intents else "(all)"
        print(
            f"  - {npc.id:25s} {npc.name}  [{npc.role}]  "
            f"intents={intents}"
        )
    return 0


async def _cmd_gen_npcs(args: argparse.Namespace) -> int:
    key = _resolve_api_key(args.provider, args.api_key_env)
    result = await gen_npcs(
        GenNpcsInput(
            demo_dir=args.demo_dir,
            n=args.n,
            brief=args.brief,
            roles=_split_csv(args.roles),
            append=not args.dry_run,
            concurrency=args.concurrency,
            provider=args.provider,
            model=args.model,
            api_key=key,
            narrative_preset=args.narrative_preset,
            topology=args.topology,
            depth=args.depth,
        )
    )
    print(
        f"generated: {len(result.added)} new NPC(s) "
        f"(existing={result.existing_count}, wrote={result.wrote})"
    )
    for npc in result.added:
        print(f"  + {npc.id:25s} {npc.name}  [{npc.role}]")
    if args.dry_run and result.added:
        print()
        print("--- dry-run preview (not written) ---")
        for npc in result.added:
            print(
                npc.model_dump_json(indent=2, exclude_none=True)
            )
    return 0


async def _cmd_gen_intents(args: argparse.Namespace) -> int:
    key = _resolve_api_key(args.provider, args.api_key_env)
    result = await gen_intents(
        GenIntentsInput(
            demo_dir=args.demo_dir,
            n=args.n,
            brief=args.brief,
            append=not args.dry_run,
            concurrency=args.concurrency,
            provider=args.provider,
            model=args.model,
            api_key=key,
        )
    )
    print(
        f"generated: {len(result.added)} new intent(s) "
        f"(existing={result.existing_count}, wrote={result.wrote})"
    )
    for intent in result.added:
        print(f"  + {intent.id:30s} {intent.name}")
    return 0


async def _cmd_gen_barks(args: argparse.Namespace) -> int:
    key = _resolve_api_key(args.provider, args.api_key_env)
    result = await gen_barks(
        GenBarksInput(
            demo_dir=args.demo_dir,
            only_npcs=_split_csv(args.only_npcs),
            only_scope_tags=_split_csv(args.only_scope_tags),
            include_unscoped=args.include_unscoped,
            n_per_npc=args.n,
            brief=args.brief,
            append=not args.dry_run,
            concurrency=args.concurrency,
            provider=args.provider,
            model=args.model,
            api_key=key,
        )
    )
    total = sum(len(e.triggers) for e in result.added)
    print(f"generated: {total} trigger(s) across {len(result.added)} NPC(s) "
          f"(wrote={result.wrote})")
    for entry in result.added:
        for trig in entry.triggers:
            print(f"  + {entry.npc:25s} {trig.id:20s} n={trig.n}")
    return 0


async def _cmd_resolve_stubs(args: argparse.Namespace) -> int:
    key = _resolve_api_key(args.provider, args.api_key_env)
    result = await resolve_stubs(
        ResolveStubsInput(
            demo_dir=args.demo_dir,
            only_ids=_split_csv(args.only_ids),
            write=not args.dry_run,
            concurrency=args.concurrency,
            provider=args.provider,
            model=args.model,
            api_key=key,
            narrative_preset=args.narrative_preset,
            topology=args.topology,
            depth=args.depth,
        )
    )
    print(
        f"resolved: {len(result.resolved)} stub(s) "
        f"(unresolved={len(result.unresolved_ids)}, wrote={result.wrote})"
    )
    for npc in result.resolved:
        print(f"  = {npc.id:25s} {npc.name}  [{npc.role}]")
    if result.unresolved_ids:
        print(f"retry: {','.join(result.unresolved_ids)}")
    return 0


async def _cmd_init(args: argparse.Namespace) -> int:
    from .project_init import scaffold_npcforge_project

    return scaffold_npcforge_project(
        args.demo_dir,
        topology=args.topology,
        depth=args.depth,
        force=args.force,
    )


async def _cmd_doctor(args: argparse.Namespace) -> int:
    from .doctor import run_doctor

    errors, warnings = run_doctor(args.demo_dir)
    for line in errors:
        print(f"error: {line}", file=sys.stderr)
    for line in warnings:
        print(f"warn: {line}")
    return 1 if errors else 0


async def _cmd_export_cast(args: argparse.Namespace) -> int:
    from .export_cast import export_cast_csv

    path = export_cast_csv(args.demo_dir, args.out)
    print(str(path))
    return 0


async def _cmd_gen_greetings(args: argparse.Namespace) -> int:
    key = _resolve_api_key(args.provider, args.api_key_env)
    result = await gen_greetings(
        GenGreetingsInput(
            demo_dir=args.demo_dir,
            variable_id=args.variable,
            only_npcs=_split_csv(args.only_npcs),
            concurrency=args.concurrency,
            write=not args.dry_run,
            provider=args.provider,
            model=args.model,
            api_key=key,
        )
    )
    total = sum(len(e.variants) for e in result.added)
    print(
        f"generated: {total} greeting variant(s) across "
        f"{len(result.added)} NPC(s) for '${result.variable_id}' "
        f"(wrote={result.wrote})"
    )
    for entry in result.added:
        print(f"  = {entry.npc}")
        for value, text in entry.variants:
            print(f"      [{value:>10s}] {text}")
    return 0


async def _cmd_gen_repeat_greet(args: argparse.Namespace) -> int:
    key = _resolve_api_key(args.provider, args.api_key_env)
    result = await gen_repeat_greeting(
        GenRepeatGreetingInput(
            demo_dir=args.demo_dir,
            n=args.n,
            only_npcs=_split_csv(args.only_npcs),
            concurrency=args.concurrency,
            write=not args.dry_run,
            provider=args.provider,
            model=args.model,
            api_key=key,
        )
    )
    total = sum(len(e.variants) for e in result.added)
    print(
        f"generated: {total} visit-gated variant(s) across "
        f"{len(result.added)} NPC(s)  (wrote={result.wrote})"
    )
    for entry in result.added:
        print(f"  = {entry.npc}")
        for idx, text in enumerate(entry.variants):
            label = f"visit {idx}" if idx < len(entry.variants) - 1 else "else"
            print(f"      [{label}] {text}")
    return 0


async def _cmd_play(args: argparse.Namespace) -> int:
    if args.bark:
        return play_barks(
            demo_dir=args.demo_dir,
            npc_id=args.npc,
            trigger=args.bark,
            out=args.out,
            tempo=args.tempo,
            wait=args.wait,
        )
    if args.greet:
        return play_greetings(
            demo_dir=args.demo_dir,
            npc_id=args.npc,
            variable_id=args.greet,
            out=args.out,
            tempo=args.tempo,
            wait=args.wait,
        )
    if args.repeat_greet:
        return play_repeat_greeting(
            demo_dir=args.demo_dir,
            npc_id=args.npc,
            out=args.out,
            tempo=args.tempo,
            wait=args.wait,
        )
    return play_walk_up(
        demo_dir=args.demo_dir,
        npc_id=args.npc,
        intent=args.intent,
        out=args.out,
        tempo=args.tempo,
        wait=args.wait,
    )


async def _cmd_engine_sync(args: argparse.Namespace) -> int:
    result = await engine_sync(
        EngineSyncInput(
            demo_dir=args.demo_dir,
            project_dir=args.project_dir,
            engine=args.engine,
            source_dir=args.source_dir,
            install_scripts=args.install_scripts,
            scripts_source_dir=args.scripts_source_dir,
            dry_run=args.dry_run,
        )
    )
    prefix = "[dry-run] " if result.dry_run else ""
    print(
        f"{prefix}engine={result.engine}  project={result.project_dir}  "
        f"source={result.source_dir}  files_written={result.total_files}"
    )
    if args.verbose:
        for a in result.actions:
            loc = a.destination
            src = f"  <- {a.source}" if a.source else ""
            print(f"  {a.action:6s}  {loc}{src}  ({a.reason})")
    if result.errors:
        for err in result.errors:
            print(f"error: {err}", file=sys.stderr)
        return 1
    if result.marker_path:
        print(f"marker: {result.marker_path}")
    return 0


async def _cmd_game(args: argparse.Namespace) -> int:
    return run_game(GameConfig(demo_dir=args.demo_dir, tempo=args.tempo))


async def _cmd_tape_game(args: argparse.Namespace) -> int:
    """Minimal tavern loop + optional GIF (see :mod:`npcforge.tape_game`)."""
    from .tape_game import TapeSessionConfig, run_tape_session

    cfg = TapeSessionConfig(
        demo_dir=args.demo_dir,
        gif_path=args.gif,
        auto_turns=args.auto_turns,
        follow_quest=args.follow_quest,
        frame_ms=args.frame_ms,
        regenerate=args.regenerate,
        provider=args.provider,
        model=args.model,
        api_key_env=args.api_key_env,
        width=args.tape_width,
        height=args.tape_height,
    )
    return await run_tape_session(cfg)


async def _cmd_mcp(args: argparse.Namespace) -> int:
    # Deferred import keeps the mcp package optional for users who only need
    # the CLI. Any ImportError is surfaced with a clear install hint.
    try:
        from .mcp_server import run_stdio
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            f"MCP server requires the 'mcp' package. Install with "
            f"'pip install mcp'. Underlying error: {exc}"
        )
    await run_stdio()
    return 0


# ---------------------------------------------------------------------------
# v0.9.0 — social graph + memory commands
# ---------------------------------------------------------------------------


async def _cmd_gen_scene(args: argparse.Namespace) -> int:
    """Generate one multi-NPC scene and write it to out/scene_<id>.yarn."""
    from .memory import MemoryStore
    from .narrative_scope import load_layers_config, layers_yaml_path
    from .pipeline import generate_scene, write_scene_yarn
    from .scenes import Scene
    from .schemas import (
        load_factions,
        load_npcs,
        validate_npc_factions,
    )

    demo_dir: Path = args.demo_dir
    npcs = load_npcs(demo_dir / "characters.yaml")
    factions = load_factions(demo_dir / "factions.yaml")
    validate_npc_factions(npcs, factions)

    memory_path = demo_dir / "memory.json"
    store = MemoryStore.load(memory_path) if memory_path.exists() else None

    scene = Scene(
        id=args.id,
        location=args.location,
        participants=_split_csv(args.npcs),
        setup=args.setup,
        player_present=not args.no_player,
        max_lines=args.lines,
    )

    api_key = _resolve_api_key(args.provider, args.api_key_env)
    layers_cfg = load_layers_config(layers_yaml_path(demo_dir))
    dialogue, warnings = await generate_scene(
        scene=scene,
        cast=npcs,
        factions=factions,
        memory_store=store,
        api_key=api_key,
        model_name=args.model,
        model_provider_name=args.provider,
        temperature=args.temperature,
        layers=layers_cfg,
    )
    for w in warnings:
        print(f"warn: {w}", file=sys.stderr)
    if dialogue is None:
        print("Scene generation failed — see warnings above.", file=sys.stderr)
        return 1

    out_dir = args.out or (demo_dir / "out")
    path = write_scene_yarn(
        scene, dialogue, npcs, out_dir=out_dir, end_node=args.end_node,
    )
    print(f"scene written: {path}")
    print(f"  main lines: {len(dialogue.main)}")
    print(f"  player choices: {len(dialogue.choices)}")
    return 0


async def _cmd_list_factions(args: argparse.Namespace) -> int:
    """List factions from ``factions.yaml`` with membership counts."""
    from .schemas import load_factions, load_npcs

    demo_dir: Path = args.demo_dir
    factions = load_factions(demo_dir / "factions.yaml")
    npcs = load_npcs(demo_dir / "characters.yaml")
    if not factions.factions:
        print(f"No factions.yaml at {demo_dir / 'factions.yaml'}.")
        return 0

    counts: dict[str, int] = {f.id: 0 for f in factions.factions}
    for n in npcs:
        if n.faction_id and n.faction_id in counts:
            counts[n.faction_id] += 1
        if n.secondary_faction_id and n.secondary_faction_id in counts:
            counts[n.secondary_faction_id] += 1

    if args.json:
        print(json.dumps({
            "factions": [
                {
                    **f.model_dump(),
                    "member_count": counts.get(f.id, 0),
                }
                for f in factions.factions
            ],
        }, indent=2))
        return 0

    for f in factions.factions:
        rivals = f", rivals: {', '.join(f.rivals)}" if f.rivals else ""
        allies = f", allies: {', '.join(f.allies)}" if f.allies else ""
        print(f"{f.id}  [{counts[f.id]} members]")
        print(f"  {f.name}")
        if f.description.strip():
            print(f"    {f.description.strip()}")
        if allies or rivals:
            print(f"   {allies}{rivals}")
    return 0


async def _cmd_memory_show(args: argparse.Namespace) -> int:
    """Print what npcforge remembers — full store or filtered by NPC."""
    from .memory import MemoryStore, summarize_for_npc
    from .schemas import load_npcs

    demo_dir: Path = args.demo_dir
    path = demo_dir / "memory.json"
    store = MemoryStore.load(path)
    print(f"memory store: {path} (current_turn={store.current_turn}, "
          f"{len(store.events)} events)")

    if args.npc:
        npcs = {n.id: n for n in load_npcs(demo_dir / "characters.yaml")}
        if args.npc not in npcs:
            print(f"Unknown npc id: {args.npc}", file=sys.stderr)
            return 1
        block = summarize_for_npc(npcs[args.npc], store, max_lines=args.max)
        print(block or "(no events for this NPC)")
        return 0

    if args.json:
        print(store.to_json())
        return 0

    for e in sorted(store.events, key=lambda x: x.turn, reverse=True)[:args.max]:
        faction = f"[{e.faction_id}] " if e.faction_id else ""
        print(f"turn {e.turn:>4}  {e.salience:<8}  {faction}{e.npc_id}  "
              f"{e.event_type}  — {e.summary}")
    return 0


async def _cmd_quest_list(args: argparse.Namespace) -> int:
    """List declared quests + their current stage."""
    from .quests import QuestTracker
    from .schemas import load_quests

    demo_dir: Path = args.demo_dir
    cfg = load_quests(demo_dir / "quests.yaml")
    tracker = QuestTracker.load(demo_dir / "quest_state.json")
    if not cfg.quests:
        print(f"no quests declared at {demo_dir / 'quests.yaml'}")
        return 0
    for q in cfg.quests:
        current = tracker.current_stages.get(q.id)
        status = current or "(not started)"
        print(f"{q.id}: {q.name}")
        print(f"  current: {status}")
        for i, s in enumerate(q.stages):
            marker = "★" if s.id == current else " "
            print(f"  {marker} [{i}] {s.label} ({s.id})")
    return 0


async def _cmd_quest_show(args: argparse.Namespace) -> int:
    """Show one quest in detail (every stage + current)."""
    from .quests import QuestTracker
    from .schemas import load_quests

    demo_dir: Path = args.demo_dir
    cfg = load_quests(demo_dir / "quests.yaml")
    tracker = QuestTracker.load(demo_dir / "quest_state.json")
    q = cfg.by_id(args.id)
    if q is None:
        print(f"unknown quest id: {args.id}", file=sys.stderr)
        return 1
    current = tracker.current_stages.get(q.id)
    print(f"{q.id}: {q.name}")
    if q.description.strip():
        print(f"  {q.description.strip()}")
    print(f"  current: {current or '(not started)'}")
    print()
    for i, s in enumerate(q.stages):
        marker = "★" if s.id == current else " "
        print(f"  {marker} [{i}] {s.label} ({s.id})")
        if s.description.strip():
            print(f"        {s.description.strip()}")
        if s.known_to:
            print(f"        known_to: {', '.join(s.known_to)}")
    return 0


async def _cmd_quest_set(args: argparse.Namespace) -> int:
    """Set a quest to a specific stage (advance or rewind)."""
    from .quests import QuestTracker
    from .schemas import load_quests

    demo_dir: Path = args.demo_dir
    cfg = load_quests(demo_dir / "quests.yaml")
    path = demo_dir / "quest_state.json"
    tracker = QuestTracker.load(path)
    try:
        tracker.set_stage(args.id, args.stage, cfg)
    except KeyError as exc:
        print(f"{exc}", file=sys.stderr)
        return 1
    tracker.save(path)
    print(f"set {args.id} -> {args.stage}")
    return 0


async def _cmd_quest_advance(args: argparse.Namespace) -> int:
    """Advance a quest to the next stage."""
    from .quests import QuestTracker
    from .schemas import load_quests

    demo_dir: Path = args.demo_dir
    cfg = load_quests(demo_dir / "quests.yaml")
    path = demo_dir / "quest_state.json"
    tracker = QuestTracker.load(path)
    try:
        new_stage = tracker.advance(args.id, cfg)
    except KeyError as exc:
        print(f"{exc}", file=sys.stderr)
        return 1
    tracker.save(path)
    if new_stage is None:
        print(f"{args.id} already at final stage")
    else:
        print(f"advanced {args.id} -> {new_stage}")
    return 0


async def _cmd_emotion_show(args: argparse.Namespace) -> int:
    """Show an NPC's currently-derived emotional state."""
    from .emotion import compute_emotion_state, summarize_emotion_state
    from .memory import MemoryStore
    from .schemas import load_npcs

    demo_dir: Path = args.demo_dir
    npcs = {n.id: n for n in load_npcs(demo_dir / "characters.yaml")}
    if args.npc not in npcs:
        print(f"Unknown npc id: {args.npc}", file=sys.stderr)
        return 1
    npc = npcs[args.npc]
    store = MemoryStore.load(demo_dir / "memory.json")
    state = compute_emotion_state(
        npc, store, decay_per_turn=args.decay_per_turn,
    )
    if args.json:
        print(json.dumps({
            "npc_id": npc.id,
            "turn": store.current_turn,
            "axes": state.axes,
            "dominant": state.dominant(),
        }, indent=2))
        return 0

    print(f"{npc.id}: turn={store.current_turn}, "
          f"decay_per_turn={args.decay_per_turn}")
    if not state.axes:
        print("  (calm — no emotions above threshold)")
        return 0
    for axis, v in sorted(state.axes.items(), key=lambda kv: kv[1], reverse=True):
        bar = "█" * int(v * 20)
        print(f"  {axis:<13}  {v:0.2f}  {bar}")
    print()
    print(summarize_emotion_state(state))
    return 0


async def _cmd_trajectory_show(args: argparse.Namespace) -> int:
    """Show an NPC's current relationship-trajectory waypoint."""
    from .memory import MemoryStore
    from .schemas import load_npcs
    from .trajectory import evaluate_trajectory, summarize_trajectory

    demo_dir: Path = args.demo_dir
    npcs = {n.id: n for n in load_npcs(demo_dir / "characters.yaml")}
    if args.npc not in npcs:
        print(f"Unknown npc id: {args.npc}", file=sys.stderr)
        return 1
    npc = npcs[args.npc]
    if npc.trajectory is None:
        print(f"{npc.id} has no trajectory declared.")
        return 0

    store = MemoryStore.load(demo_dir / "memory.json")
    reading = evaluate_trajectory(npc, store)
    if reading is None:
        print(f"{npc.id}: (no trajectory)")
        return 0

    if args.json:
        print(json.dumps({
            "npc_id": npc.id,
            "score": reading.score,
            "current": (
                reading.current.model_dump() if reading.current else None
            ),
            "next": (
                reading.next_waypoint.model_dump()
                if reading.next_waypoint else None
            ),
            "distance_to_next": reading.distance_to_next,
            "top_events": [
                {"event_type": t, "summary": s, "delta": d}
                for t, s, d in reading.top_events
            ],
            "waypoints": [w.model_dump() for w in npc.trajectory.waypoints],
        }, indent=2))
        return 0

    print(f"{npc.id}: score {reading.score:+.3f}")
    print(f"  waypoints:")
    sorted_wps = sorted(npc.trajectory.waypoints, key=lambda w: w.min_score)
    for w in sorted_wps:
        marker = "★" if reading.current and w.id == reading.current.id else " "
        print(f"    {marker} [{w.min_score:+.2f}] {w.label} ({w.id})")
    if reading.current is None:
        print(f"  current: (below lowest — score {reading.score:+.3f} "
              f"< min {sorted_wps[0].min_score:+.2f})")
    else:
        print(f"  current: {reading.current.label}")
    if reading.next_waypoint:
        print(f"  next: {reading.next_waypoint.label} "
              f"(needs +{reading.distance_to_next:.2f})")
    if reading.top_events:
        print(f"  top-weighted events:")
        for e, s, d in reading.top_events:
            print(f"    {d:+.3f}  {e} — {s.strip()}")
    return 0


async def _cmd_trajectory_simulate(args: argparse.Namespace) -> int:
    """Preview where an NPC would land given synthetic events."""
    from .memory import MemoryStore
    from .schemas import load_npcs
    from .trajectory import evaluate_trajectory

    demo_dir: Path = args.demo_dir
    npcs = {n.id: n for n in load_npcs(demo_dir / "characters.yaml")}
    if args.npc not in npcs:
        print(f"Unknown npc id: {args.npc}", file=sys.stderr)
        return 1
    npc = npcs[args.npc]
    if npc.trajectory is None:
        print(f"{npc.id} has no trajectory declared.")
        return 0

    store = MemoryStore()
    turn = 0
    for event_type in _split_csv(args.events or ""):
        turn += 1
        store.record(
            npc_id=npc.id, event_type=event_type,
            summary=f"synthetic {event_type}",
            salience="notable", turn=turn,
        )
    store.current_turn = turn
    reading = evaluate_trajectory(npc, store)
    print(f"simulated {npc.id} with events: {args.events}")
    print(f"  score: {reading.score:+.3f}")
    print(f"  current: {reading.current.label if reading.current else '(below lowest)'}")
    if reading.next_waypoint:
        print(f"  next: {reading.next_waypoint.label} "
              f"(needs +{reading.distance_to_next:.2f})")
    return 0


async def _cmd_ethics_judge(args: argparse.Namespace) -> int:
    """Preview the NPC's ethical reading of the player against the
    current memory store. Read-only — writes nothing."""
    from .ethics import evaluate_player_against_npc, summarize_ethical_reading
    from .memory import MemoryStore
    from .schemas import load_npcs

    demo_dir: Path = args.demo_dir
    npcs = {n.id: n for n in load_npcs(demo_dir / "characters.yaml")}
    if args.npc not in npcs:
        print(f"Unknown npc id: {args.npc}", file=sys.stderr)
        return 1
    npc = npcs[args.npc]
    if npc.ethical_profile is None:
        print(f"{npc.id} has no ethical_profile declared.")
        return 0

    store = MemoryStore.load(demo_dir / "memory.json")
    reading = evaluate_player_against_npc(npc, store)

    if args.json:
        print(json.dumps({
            "npc_id": npc.id,
            "profile": npc.ethical_profile.model_dump(),
            "score": reading.score,
            "by_axis": reading.by_axis,
            "top_events": [
                {"event_type": t, "summary": s, "delta": d}
                for t, s, d in reading.top_events
            ],
        }, indent=2))
        return 0

    dominant = npc.ethical_profile.dominant_axes()
    dom = ", ".join(dominant) if dominant else "(no dominant axis)"
    verdict = (
        "net approving" if reading.score > 0.1 else
        "net disapproving" if reading.score < -0.1 else
        "mixed"
    )
    print(f"{npc.id}: {verdict} (score {reading.score:+.3f})")
    print(f"  dominant axes: {dom}")
    if reading.by_axis:
        print("  per-axis contribution:")
        for axis, contrib in sorted(
            reading.by_axis.items(), key=lambda kv: abs(kv[1]), reverse=True
        ):
            print(f"    {axis:<14}  {contrib:+.3f}")
    if reading.top_events:
        print("  top-weighted events:")
        for event_type, summary, delta in reading.top_events:
            print(f"    {delta:+.3f}  {event_type}  — {summary.strip()}")
    print()
    print(summarize_ethical_reading(npc, reading))
    return 0


async def _cmd_unseen_list(args: argparse.Namespace) -> int:
    from .unseen import UnseenRegistry
    demo_dir: Path = args.demo_dir
    path = demo_dir / "unseen.json"
    reg = UnseenRegistry.load(path)
    if not reg.characters:
        print(f"no unseen slots declared at {path}")
        return 0
    if args.json:
        print(reg.to_json())
        return 0
    print(f"unseen registry: {path} ({len(reg.characters)} slots)")
    for cid, u in reg.characters.items():
        status = "materialized" if u.materialized_as else "unseen"
        print(f"  {cid}  [{status}]  {u.display_name_hint or '(no name hint)'}"
              + (f" → {u.materialized_as}" if u.materialized_as else ""))
        print(f"    role_hint: {u.role_hint or '(none)'}")
        print(f"    mentions: {len(u.mention_records)}")
    return 0


async def _cmd_unseen_show(args: argparse.Namespace) -> int:
    from .unseen import UnseenRegistry, summarize_canon
    demo_dir: Path = args.demo_dir
    reg = UnseenRegistry.load(demo_dir / "unseen.json")
    if args.id not in reg.characters:
        print(f"unknown unseen id: {args.id}", file=sys.stderr)
        return 1
    u = reg.characters[args.id]
    print(f"canonical_id: {u.canonical_id}")
    print(f"display_name_hint: {u.display_name_hint or '(none)'}")
    print(f"role_hint: {u.role_hint or '(none)'}")
    print(f"materialized_as: {u.materialized_as or '(still unseen)'}")
    print()
    canon = summarize_canon(u)
    if canon:
        print(canon)
    else:
        print("(no mentions accumulated yet)")
    return 0


async def _cmd_unseen_declare(args: argparse.Namespace) -> int:
    from .unseen import UnseenRegistry
    demo_dir: Path = args.demo_dir
    path = demo_dir / "unseen.json"
    reg = UnseenRegistry.load(path)
    existed = args.id in reg.characters
    reg.declare(args.id, display_name_hint=args.name or "",
                role_hint=args.role or "")
    reg.save(path)
    print(f"{'updated' if existed else 'declared'}: {args.id}")
    return 0


async def _cmd_unseen_record(args: argparse.Namespace) -> int:
    from .unseen import UnseenRegistry
    demo_dir: Path = args.demo_dir
    path = demo_dir / "unseen.json"
    reg = UnseenRegistry.load(path)
    if args.id not in reg.characters:
        print(f"unknown unseen id '{args.id}'. Declare it first with "
              f"`npcforge unseen declare`.", file=sys.stderr)
        return 1
    reg.record_mention(
        args.id,
        source_npc_id=args.source,
        context=args.context,
        turn=args.turn,
        scene_context=args.scene or "",
    )
    reg.save(path)
    print(f"recorded mention of '{args.id}' from {args.source}")
    return 0


async def _cmd_unseen_materialize(args: argparse.Namespace) -> int:
    """Generate a full NpcSheet for an unseen slot. Writes YAML preview
    to stdout unless --commit (then appends to characters.yaml)."""
    import yaml as _yaml
    from .schemas import (
        load_factions, load_npcs, load_world_bible, validate_npc_factions,
    )
    from .unseen import UnseenRegistry, materialize

    demo_dir: Path = args.demo_dir
    reg = UnseenRegistry.load(demo_dir / "unseen.json")
    if args.id not in reg.characters:
        print(f"unknown unseen id: {args.id}", file=sys.stderr)
        return 1
    unseen = reg.characters[args.id]

    existing = load_npcs(demo_dir / "characters.yaml")
    factions = load_factions(demo_dir / "factions.yaml")
    validate_npc_factions(existing, factions)
    world_bible = load_world_bible(demo_dir / "lore")

    key = _resolve_api_key(args.provider, args.api_key_env)
    sheet = await materialize(
        unseen=unseen,
        world_bible=world_bible,
        existing_cast=existing,
        factions=factions,
        api_key=key,
        model_name=args.model,
        model_provider_name=args.provider,
        temperature=args.temperature,
        override_id=args.new_id or "",
    )
    if sheet is None:
        print("materialisation failed — see log warnings.", file=sys.stderr)
        return 1

    # Emit the sheet as YAML for the writer to review.
    dumped = sheet.model_dump(exclude_none=True, exclude_defaults=True)
    yaml_text = _yaml.safe_dump([dumped], sort_keys=False,
                                 default_flow_style=False, width=88)
    print(yaml_text)

    if args.commit:
        chars_path = demo_dir / "characters.yaml"
        chars_text = chars_path.read_text(encoding="utf-8")
        # Append the new entry under the npcs: list. We look for the
        # last `  - id:` entry and insert after its block by appending
        # to the file with '  - id: ...' shape.
        appendable = _yaml.safe_dump([dumped], sort_keys=False,
                                      default_flow_style=False, width=88)
        # YAML safe_dump renders with `- id: foo` at col 0; indent by 2.
        indented = "\n".join(
            ("  " + line) if line.strip() else line
            for line in appendable.splitlines()
        ) + "\n"
        if not chars_text.endswith("\n"):
            chars_text += "\n"
        chars_path.write_text(chars_text + indented, encoding="utf-8")
        reg.characters[args.id].materialized_as = sheet.id
        reg.save(demo_dir / "unseen.json")
        print(f"committed: appended to {chars_path} and marked "
              f"'{args.id}' as materialized_as={sheet.id}")
    else:
        print("(dry-run — pass --commit to append to characters.yaml + "
              "mark the slot materialised)")
    return 0


async def _cmd_voice_show(args: argparse.Namespace) -> int:
    """Show an NPC's voice lenses and which would be active."""
    from .schemas import (
        load_npcs, resolve_active_lenses, validate_npc_voice_lenses,
    )

    demo_dir: Path = args.demo_dir
    npcs = {n.id: n for n in load_npcs(demo_dir / "characters.yaml")}
    validate_npc_voice_lenses(list(npcs.values()))
    if args.npc not in npcs:
        print(f"Unknown npc id: {args.npc}", file=sys.stderr)
        return 1
    npc = npcs[args.npc]
    if not npc.voice_lenses:
        print(f"{npc.id} has no voice lenses declared.")
        return 0

    active = set(_split_csv(args.active)) if args.active else set()
    active_resolved = {l.id for l in resolve_active_lenses(npc, active)}

    print(f"{npc.id}: {len(npc.voice_lenses)} lenses")
    for l in npc.voice_lenses:
        marker = "★" if l.id in active_resolved else " "
        print(f"  {marker} [{l.kind:8}] {l.label} ({l.id})")
        print(f"      cadence: {l.cadence_shift.strip()}")
        if l.extra_forbidden_words:
            print(f"      extra forbidden: {', '.join(l.extra_forbidden_words)}")
        if l.extra_accent_markers:
            print(f"      extra accent markers:")
            for m in l.extra_accent_markers:
                print(f"        - {m}")
    return 0


async def _cmd_player_show(args: argparse.Namespace) -> int:
    """Print the player profile. Top axes first, weights rounded."""
    from .player_profile import PlayerProfile

    demo_dir: Path = args.demo_dir
    path = demo_dir / "player_profile.json"
    profile = PlayerProfile.load(path)
    if args.json:
        print(profile.to_json())
        return 0
    print(f"player profile: {path} (updated_at_turn={profile.updated_at_turn})")
    if not profile.axes:
        print("  (no observations yet)")
        return 0
    for axis, weight in sorted(profile.axes.items(), key=lambda kv: kv[1], reverse=True):
        bar = "█" * int(weight * 20)
        print(f"  {axis:<14}  {weight:0.2f}  {bar}")
    return 0


async def _cmd_player_rebuild(args: argparse.Namespace) -> int:
    """Regenerate the profile from scratch against the memory store."""
    from .memory import MemoryStore
    from .player_profile import rebuild_from_store

    demo_dir: Path = args.demo_dir
    store = MemoryStore.load(demo_dir / "memory.json")
    profile = rebuild_from_store(
        store.events,
        decay_rate=args.decay_rate,
    )
    profile.updated_at_turn = store.current_turn
    path = demo_dir / "player_profile.json"
    profile.save(path)
    print(f"player profile rebuilt from {len(store.events)} events → {path}")
    if profile.axes:
        for axis, weight in sorted(
            profile.axes.items(), key=lambda kv: kv[1], reverse=True
        ):
            print(f"  {axis:<14}  {weight:0.2f}")
    return 0


async def _cmd_player_update(args: argparse.Namespace) -> int:
    """Apply one event to the profile. Useful for scripting demos."""
    from .player_profile import DEFAULT_AXIS_DELTAS, PlayerProfile, apply_event

    demo_dir: Path = args.demo_dir
    path = demo_dir / "player_profile.json"
    profile = PlayerProfile.load(path)
    if args.event_type not in DEFAULT_AXIS_DELTAS:
        print(
            f"warn: event_type '{args.event_type}' has no default axis delta — "
            f"profile unchanged. Known types: "
            f"{sorted(DEFAULT_AXIS_DELTAS)}",
            file=sys.stderr,
        )
        return 1
    apply_event(profile, args.event_type)
    profile.save(path)
    print(f"applied {args.event_type}. axes now:")
    for axis, weight in sorted(profile.axes.items(), key=lambda kv: kv[1], reverse=True):
        print(f"  {axis:<14}  {weight:0.2f}")
    return 0


async def _cmd_export_improv_context(args: argparse.Namespace) -> int:
    """Emit a JSON context bundle one NPC needs for improv at runtime.

    The Unity-side NpcForgeImprovClient reads this file, does retrieval
    against the lore bundle locally, and hands the composed prompt to
    a user-supplied LLM delegate. Keeping the character sheet rendering
    on the Python side means the Unity runtime doesn't need to port
    NpcSheet / Faction / KnowledgeItem rendering.
    """
    from .improv import build_improv_system_prompt
    from .schemas import (
        load_factions,
        load_npcs,
        load_world_bible,
        validate_npc_factions,
    )
    from .prompts import render_character_sheet

    demo_dir: Path = args.demo_dir
    npcs = {n.id: n for n in load_npcs(demo_dir / "characters.yaml")}
    factions = load_factions(demo_dir / "factions.yaml")
    validate_npc_factions(list(npcs.values()), factions)
    if args.npc not in npcs:
        print(f"Unknown npc id: {args.npc}", file=sys.stderr)
        return 1
    npc = npcs[args.npc]
    world_bible = load_world_bible(demo_dir / "lore")

    # Pre-render the character-sheet-only part of the system prompt
    # (everything BUT the per-query lore snippets, which Unity retrieves
    # per-query). Callers on Unity will concatenate this with the
    # retrieved lore snippets + rules block at runtime.
    character_sheet_block = render_character_sheet(npc, factions=factions)

    # The rules block is invariant across queries — produced once by
    # building an improv prompt with no lore and stripping the sheet
    # + snippets sections. We just inline the canonical rules text.
    rules_block = (
        "You are answering a question that wasn't pre-scripted for this "
        "character. Produce ONE short in-character reply. Constraints:\n"
        "1. Stay fully in character. First-person dialogue only. No "
        "narration, no stage directions.\n"
        "2. Ground every factual claim in the lore snippets above OR in "
        "your character sheet. If the question lands outside both, "
        "deflect in-character — do not invent.\n"
        "3. Your 'Knowledge' block lists facts you possess. Honour gates: "
        "reveal only when the player's question clearly satisfies the "
        "gate, otherwise deflect using the tone of the sample "
        "deflection lines.\n"
        "4. One to three short sentences. At most 60 words.\n"
        "5. Honour your vocabulary ceiling, forbidden words, and speech "
        "quirks. Apply any active arc-stage voice shifts.\n"
        "6. Do not quote the lore snippets verbatim or cite their [source] "
        "tags. Translate any facts you use into your own voice."
    )

    context = {
        "schema_version": "1",
        "npc_id": npc.id,
        "npc_name": npc.name,
        "character_sheet_block": character_sheet_block,
        "world_bible": world_bible,
        "rules_block": rules_block,
    }
    out_path = args.out or (demo_dir / "out" / f"{npc.id}_improv_context.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(context, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"improv context written: {out_path}")
    print(f"  character sheet: {len(character_sheet_block)} chars")
    print(f"  world bible: {len(world_bible)} chars")
    return 0


async def _cmd_improv(args: argparse.Namespace) -> int:
    """One-shot improv call — ask an NPC something off-script."""
    from .improv import build_improv_system_prompt, improv_query, retrieve_lore_chunks
    from .memory import MemoryStore
    from .player_profile import PlayerProfile, summarize_for_observer
    from .schemas import (
        load_factions,
        load_npcs,
        load_world_bible,
        validate_npc_factions,
    )

    demo_dir: Path = args.demo_dir
    npcs = {n.id: n for n in load_npcs(demo_dir / "characters.yaml")}
    factions = load_factions(demo_dir / "factions.yaml")
    validate_npc_factions(list(npcs.values()), factions)
    if args.npc not in npcs:
        print(f"Unknown npc id: {args.npc}", file=sys.stderr)
        return 1
    npc = npcs[args.npc]
    world_bible = load_world_bible(demo_dir / "lore")

    store = MemoryStore.load(demo_dir / "memory.json")
    if store.events == [] and (demo_dir / "memory.json").exists() is False:
        store = None  # fully absent vs. empty-on-disk

    profile_path = demo_dir / "player_profile.json"
    profile = PlayerProfile.load(profile_path)
    player_profile_block = (
        summarize_for_observer(profile) if profile.axes else ""
    )

    # Retrieve + compose + call. Done with improv_query helper, but we
    # override the system prompt so the observer block can thread through.
    chunks = retrieve_lore_chunks(args.query, world_bible, top_k=args.top_k_lore)
    # When profile block is non-empty AND npc is an observer, use the
    # full builder so the block lands correctly.
    system_prompt = build_improv_system_prompt(
        npc,
        lore_chunks=chunks,
        factions=factions,
        memory_store=store,
        player_profile_block=player_profile_block,
    )
    _ = system_prompt  # kept for diagnostic; improv_query rebuilds internally
    from .schemas import resolve_active_lenses
    active_lenses = (
        resolve_active_lenses(npc, _split_csv(args.lenses))
        if args.lenses else []
    )

    from .ethics import evaluate_player_against_npc, summarize_ethical_reading
    ethical_reading_block = ""
    if store is not None and npc.ethical_profile is not None:
        reading = evaluate_player_against_npc(npc, store)
        ethical_reading_block = summarize_ethical_reading(npc, reading)

    from .trajectory import evaluate_trajectory, summarize_trajectory
    trajectory_block = ""
    if store is not None and npc.trajectory is not None:
        t_reading = evaluate_trajectory(npc, store)
        trajectory_block = summarize_trajectory(npc, t_reading)

    from .emotion import compute_emotion_state, summarize_emotion_state
    emotion_block = ""
    if store is not None:
        e_state = compute_emotion_state(npc, store)
        emotion_block = summarize_emotion_state(e_state)

    from .quests import QuestTracker, summarize_active_quests
    from .schemas import load_quests
    quests_cfg = load_quests(demo_dir / "quests.yaml")
    quest_tracker = QuestTracker.load(demo_dir / "quest_state.json")
    active_quests_block = summarize_active_quests(
        npc.id, quest_tracker, quests_cfg,
    )

    reply = await improv_query(
        npc=npc,
        query=args.query,
        world_bible=world_bible,
        factions=factions,
        memory_store=store,
        api_key=_resolve_api_key(args.provider, args.api_key_env),
        model_name=args.model,
        model_provider_name=args.provider,
        top_k_lore=args.top_k_lore,
        temperature=args.temperature,
        player_profile_block=player_profile_block,
        active_lenses=active_lenses,
        ethical_reading_block=ethical_reading_block,
        trajectory_block=trajectory_block,
        emotion_block=emotion_block,
        active_quests_block=active_quests_block,
    )
    if reply is None:
        print("improv failed — see log warnings.", file=sys.stderr)
        return 1
    print(f"{npc.name}: {reply.text}")
    if reply.used_gate_id:
        print(f"  (revealed gated knowledge: {reply.used_gate_id})")
    if reply.declined_reason:
        print(f"  (declined: {reply.declined_reason})")
    return 0


async def _cmd_gen_lines(args: argparse.Namespace) -> int:
    """Generate a disposition-curated line bank for one NPC + slot."""
    from .line_bank import LineBank, LineSlot, bank_coverage_report
    from .pipeline import generate_line_bank
    from .schemas import load_factions, load_npcs, validate_npc_factions

    demo_dir: Path = args.demo_dir
    npcs = {n.id: n for n in load_npcs(demo_dir / "characters.yaml")}
    factions = load_factions(demo_dir / "factions.yaml")
    validate_npc_factions(list(npcs.values()), factions)
    if args.npc not in npcs:
        print(f"Unknown npc id: {args.npc}", file=sys.stderr)
        return 1
    npc = npcs[args.npc]

    slot = LineSlot(
        id=args.slot_id,
        description=args.slot_description,
        default_text=args.default_text or "",
    )

    axes: dict[str, list[str]] = {}
    for spec in args.axes or []:
        if "=" not in spec:
            raise SystemExit(
                f"Invalid axis spec '{spec}'. Use dim=v1,v2,v3 (e.g. "
                f"disposition_tier=wary,trusted)."
            )
        dim, values = spec.split("=", 1)
        axes[dim.strip()] = [v.strip() for v in values.split(",") if v.strip()]

    bank_path = args.out or (demo_dir / "out" / f"{npc.id}_lines.json")
    existing = LineBank.load(bank_path) if bank_path.exists() else None

    key = _resolve_api_key(args.provider, args.api_key_env)
    bank = await generate_line_bank(
        npc=npc,
        slot=slot,
        axes=axes,
        variants_per_combo=args.n,
        factions=factions,
        existing=existing,
        api_key=key,
        model_name=args.model,
        model_provider_name=args.provider,
        max_concurrency=args.concurrency,
        temperature=args.temperature,
    )
    if args.dry_run:
        print(f"(dry-run) would write {bank.variant_count(slot.id)} "
              f"variants to {bank_path}")
        return 0
    bank.save(bank_path)
    print(f"line bank written: {bank_path}")
    for slot_id, counts in bank_coverage_report(bank).items():
        total = counts.pop("_total")
        print(f"  slot '{slot_id}': {total} variants")
        for k, v in sorted(counts.items()):
            print(f"    {k}: {v}")
    return 0


async def _cmd_arc_show(args: argparse.Namespace) -> int:
    """Display one NPC's arc and which stages are currently active."""
    from .arcs import evaluate_arc, newly_latched_stages
    from .memory import MemoryStore
    from .schemas import (
        load_factions,
        load_npcs,
        validate_npc_arcs,
        validate_npc_factions,
    )

    demo_dir: Path = args.demo_dir
    npcs = {n.id: n for n in load_npcs(demo_dir / "characters.yaml")}
    factions = load_factions(demo_dir / "factions.yaml")
    validate_npc_factions(list(npcs.values()), factions)
    validate_npc_arcs(list(npcs.values()))

    if args.npc not in npcs:
        print(f"Unknown npc id: {args.npc}", file=sys.stderr)
        return 1
    npc = npcs[args.npc]
    if npc.arc is None:
        print(f"{npc.id} has no arc declared.")
        return 0

    store = MemoryStore.load(demo_dir / "memory.json")
    standings = _parse_standing_arg(args.standing)
    active = evaluate_arc(npc, store=store, standings=standings)
    newly = newly_latched_stages(npc, store, standings=standings)

    if args.json:
        print(json.dumps({
            "npc_id": npc.id,
            "arc_description": npc.arc.description,
            "stages": [s.model_dump() for s in npc.arc.stages],
            "active": [
                {"id": a.stage.id, "label": a.stage.label,
                 "index": a.index, "latched": a.latched}
                for a in active
            ],
            "newly_latchable": [a.stage.id for a in newly],
        }, indent=2))
        return 0

    print(f"{npc.id}: {len(npc.arc.stages)} stages")
    if npc.arc.description.strip():
        print(f"  {npc.arc.description.strip()}")
    active_ids = {a.stage.id for a in active}
    for i, stage in enumerate(npc.arc.stages):
        marker = "★" if stage.id in active_ids else " "
        latched = next((a.latched for a in active if a.stage.id == stage.id), False)
        tag = " [latched]" if latched else ""
        print(f"  {marker} [{i}] {stage.label} ({stage.id}){tag}")
        print(f"      voice: {stage.voice_shift.strip()}")
        trig = stage.trigger
        constraints: list[str] = []
        if trig.min_total_events:
            constraints.append(f"min_total_events={trig.min_total_events}")
        if trig.min_pivotal_events:
            constraints.append(f"min_pivotal_events={trig.min_pivotal_events}")
        if trig.required_event_types:
            constraints.append(
                f"required_types={','.join(trig.required_event_types)}"
            )
        if trig.min_standing:
            constraints.append(
                "min_standing=" + ",".join(
                    f"{k}>={v}" for k, v in trig.min_standing.items()
                )
            )
        if trig.max_standing:
            constraints.append(
                "max_standing=" + ",".join(
                    f"{k}<={v}" for k, v in trig.max_standing.items()
                )
            )
        if constraints:
            print("      trigger: " + "; ".join(constraints))
        if trig.custom_condition.strip():
            print(f"      narrative: {trig.custom_condition.strip()}")
    if newly:
        print(f"  Newly latchable this turn: {[a.stage.id for a in newly]}")
    return 0


async def _cmd_arc_simulate(args: argparse.Namespace) -> int:
    """Preview which arc stages would be active given a hypothetical memory
    state. Does not write anything."""
    from .arcs import evaluate_arc
    from .memory import MemoryStore
    from .schemas import load_npcs, validate_npc_arcs

    demo_dir: Path = args.demo_dir
    npcs = {n.id: n for n in load_npcs(demo_dir / "characters.yaml")}
    validate_npc_arcs(list(npcs.values()))
    if args.npc not in npcs:
        print(f"Unknown npc id: {args.npc}", file=sys.stderr)
        return 1
    npc = npcs[args.npc]
    if npc.arc is None:
        print(f"{npc.id} has no arc declared.")
        return 0

    store = MemoryStore()
    for i in range(args.pivotal):
        store.record(npc_id=npc.id, event_type="synthetic",
                     summary=f"synthetic pivotal {i}",
                     salience="pivotal", turn=i)
    offset = args.pivotal
    for i in range(args.notable):
        store.record(npc_id=npc.id, event_type="synthetic",
                     summary=f"synthetic notable {i}",
                     salience="notable", turn=offset + i)
    for t in _split_csv(args.types):
        store.record(npc_id=npc.id, event_type=t,
                     summary=f"synthetic {t}",
                     salience="pivotal", turn=offset + args.notable)
    standings = _parse_standing_arg(args.standing)
    active = evaluate_arc(npc, store=store, standings=standings)
    print(f"Simulated for {npc.id} with {args.pivotal} pivotal + "
          f"{args.notable} notable events")
    if standings:
        pairs = ", ".join(f"{k}={v}" for k, v in standings.items())
        print(f"  standings: {pairs}")
    print(f"  active stages: {[a.stage.id for a in active]}")
    return 0


def _parse_standing_arg(raw: str | None) -> dict[str, float]:
    """Parse '--standing lantern_regulars=20,miners=-5' into a dict."""
    if not raw:
        return {}
    out: dict[str, float] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair:
            continue
        if "=" not in pair:
            raise SystemExit(
                f"Invalid --standing entry '{pair}'. Use faction_id=value."
            )
        key, value = pair.split("=", 1)
        try:
            out[key.strip()] = float(value.strip())
        except ValueError:
            raise SystemExit(f"--standing value must be numeric: {value!r}")
    return out


async def _cmd_memory_record(args: argparse.Namespace) -> int:
    """Record one event — useful for scripting demos + tests."""
    from .memory import MemoryStore

    demo_dir: Path = args.demo_dir
    path = demo_dir / "memory.json"
    store = MemoryStore.load(path)
    if args.advance > 0:
        store.advance_turn(args.advance)
    event = store.record(
        npc_id=args.npc,
        event_type=args.type,
        summary=args.summary,
        salience=args.salience,
        faction_id=args.faction or "",
    )
    store.save(path)
    print(f"recorded event at turn {event.turn}: {event.event_type} / {event.npc_id}")
    return 0


async def _cmd_eval(args: argparse.Namespace) -> int:
    """Run the dialogue-quality eval suite against a demo."""
    from .evals import (
        EvalCase,
        default_rusted_lantern_cases,
        render_markdown_report,
        run_suite,
    )

    demo_dir: Path = args.demo_dir
    api_key = _resolve_api_key(args.provider, args.api_key_env)

    if args.suite:
        raw = json.loads(args.suite.read_text(encoding="utf-8"))
        cases = [EvalCase(**c) for c in raw]
    else:
        cases = default_rusted_lantern_cases()

    if args.only_ids:
        keep = set(_split_csv(args.only_ids))
        cases = [c for c in cases if c.id in keep]
    if args.limit > 0:
        cases = cases[: args.limit]

    if not cases:
        print("no cases to run (check --only-ids / --suite filters)", file=sys.stderr)
        return 1

    print(
        f"eval: cases={len(cases)} demo_dir={demo_dir} "
        f"provider={args.provider} model={args.model or '(default)'}"
    )
    report = await run_suite(
        cases,
        demo_dir=demo_dir,
        api_key=api_key,
        provider=args.provider,
        model=args.model,
    )

    out_dir: Path = args.out or (demo_dir / "out")
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "eval_report.md"
    json_path = out_dir / "eval_report.json"
    md_path.write_text(render_markdown_report(report), encoding="utf-8")
    json_path.write_text(
        report.model_dump_json(indent=2), encoding="utf-8",
    )

    print(
        f"done: passed={report.passed}/{report.total} "
        f"({report.pass_rate * 100:.0f}%)  voice_avg={report.voice_avg:.3f}  "
        f"lint_total={report.lint_total}  "
        f"length_fail={report.length_failures}  "
        f"register_fail={report.register_failures}"
    )
    print(f"wrote {md_path}")
    print(f"wrote {json_path}")
    return 0 if report.passed == report.total else 2


# ---------------------------------------------------------------------------
# Parser construction
# ---------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="npcforge",
        description=(
            "Generate branching NPC dialogue + bark libraries + whole casts "
            "from lore. Every subcommand calls a typed tool — the same tools "
            "the MCP server exposes."
        ),
    )
    subs = root.add_subparsers(dest="command", required=True)

    # ---- build ----
    p = subs.add_parser("build", help="Run the walk-up / bark pipeline.")
    p.add_argument("--demo-dir", type=Path, required=True)
    p.add_argument("--out", type=Path, default=None)
    p.add_argument(
        "--mode", choices=["walk_up", "barks", "all"], default="walk_up"
    )
    p.add_argument("--only-npcs", default=None)
    p.add_argument(
        "--only-scope-tags",
        default=None,
        help=(
            "Comma-separated scope tag ids (see layers.yaml + NpcSheet.scope_tags). "
            "When set, only NPCs whose scope_tags intersect this list are built."
        ),
    )
    p.add_argument(
        "--include-unscoped",
        action="store_true",
        help=(
            "With --only-scope-tags, also include NPCs that have no scope_tags "
            "(legacy sheets)."
        ),
    )
    p.add_argument("--turns", type=int, default=3)
    p.add_argument("--intent-concurrency", type=int, default=3)
    p.add_argument("--bark-concurrency", type=int, default=4)
    p.add_argument(
        "--score-voice",
        action="store_true",
        help=(
            "Compute per-branch voice-consistency scores via embedding "
            "distance from sample_lines. Adds one batched embedding call "
            "per NPC; scores appear in manifest.json."
        ),
    )
    p.add_argument("--no-validate", action="store_true")
    p.add_argument("--quiet", action="store_true")
    p.add_argument(
        "--narrative-preset",
        dest="narrative_preset",
        default=None,
        choices=["indie_minimal", "rpg_standard", "cinematic_rpg"],
        help=(
            "Override npcforge_project.yaml narrative_preset for walk-up "
            "dialogue tone."
        ),
    )
    _add_topology_depth_flags(p)
    _add_llm_flags(p)
    p.set_defaults(func=_cmd_build)

    # ---- init ----
    p_init = subs.add_parser(
        "init",
        help="Write npcforge_project.yaml with topology + depth defaults.",
    )
    p_init.add_argument("--demo-dir", type=Path, required=True)
    p_init.add_argument(
        "--topology",
        default="quest_rpg",
        choices=sorted(TOPOLOGY_IDS),
        help="Narrative topology id (default: quest_rpg).",
    )
    p_init.add_argument(
        "--depth",
        default="standard",
        choices=["lean", "standard", "cinematic"],
        help="Narrative depth (default: standard).",
    )
    p_init.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing npcforge_project.yaml.",
    )
    p_init.set_defaults(func=_cmd_init)

    # ---- doctor ----
    p_doc = subs.add_parser(
        "doctor",
        help="Sanity-check a project (YAML, npcforge_project, cast load).",
    )
    p_doc.add_argument("--demo-dir", type=Path, required=True)
    p_doc.set_defaults(func=_cmd_doctor)

    # ---- world (nested) ----
    p_world = subs.add_parser("world", help="World-profile tools.")
    p_world_sub = p_world.add_subparsers(dest="world_command", required=True)

    p_wi = p_world_sub.add_parser(
        "infer", help="Infer world profile from lore/*.md (LLM call)."
    )
    p_wi.add_argument("--demo-dir", type=Path, required=True)
    p_wi.add_argument(
        "--refresh",
        action="store_true",
        help="Ignore the cached profile and re-infer.",
    )
    _add_llm_flags(p_wi)
    p_wi.set_defaults(func=_cmd_world_infer)

    p_ws = p_world_sub.add_parser(
        "show", help="Print the cached world profile (no LLM)."
    )
    p_ws.add_argument("--demo-dir", type=Path, required=True)
    p_ws.add_argument("--json", action="store_true")
    p_ws.set_defaults(func=_cmd_world_show)

    # ---- list-npcs ----
    p_ln = subs.add_parser("list-npcs", help="List NPCs currently declared.")
    p_ln.add_argument("--demo-dir", type=Path, required=True)
    p_ln.add_argument("--json", action="store_true")
    p_ln.set_defaults(func=_cmd_list_npcs)

    # ---- gen (nested) ----
    p_gen = subs.add_parser("gen", help="Additive content generators.")
    p_gen_sub = p_gen.add_subparsers(dest="gen_command", required=True)

    p_gn = p_gen_sub.add_parser("npcs", help="Generate new NPCs (append).")
    p_gn.add_argument("--demo-dir", type=Path, required=True)
    p_gn.add_argument("--n", type=int, default=5)
    p_gn.add_argument(
        "--brief",
        default=None,
        help="Free-text description of the cast or target NPC.",
    )
    p_gn.add_argument(
        "--roles",
        default=None,
        help=(
            "Comma-separated role descriptions. One NPC per role. "
            "Overrides --n when given."
        ),
    )
    p_gn.add_argument("--concurrency", type=int, default=3)
    p_gn.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate without writing to characters.yaml.",
    )
    p_gn.add_argument(
        "--narrative-preset",
        dest="narrative_preset",
        default=None,
        choices=["indie_minimal", "rpg_standard", "cinematic_rpg"],
        help="Override npcforge_project.yaml for NPC sheet generation.",
    )
    _add_topology_depth_flags(p_gn)
    _add_llm_flags(p_gn)
    p_gn.set_defaults(func=_cmd_gen_npcs)

    p_gi = p_gen_sub.add_parser("intents", help="Generate new player intents (append).")
    p_gi.add_argument("--demo-dir", type=Path, required=True)
    p_gi.add_argument("--n", type=int, default=8)
    p_gi.add_argument("--brief", default=None)
    p_gi.add_argument("--concurrency", type=int, default=3)
    p_gi.add_argument("--dry-run", action="store_true")
    _add_llm_flags(p_gi)
    p_gi.set_defaults(func=_cmd_gen_intents)

    p_gb = p_gen_sub.add_parser(
        "barks",
        help="Generate new bark trigger proposals for one or more NPCs (append).",
    )
    p_gb.add_argument("--demo-dir", type=Path, required=True)
    p_gb.add_argument(
        "--only-npcs",
        default=None,
        help=(
            "Comma-separated NPC ids. Default: every NPC in characters.yaml. "
            "(Previously --for-npcs; same meaning, renamed for consistency "
            "with build.)"
        ),
    )
    p_gb.add_argument(
        "--only-scope-tags",
        default=None,
        help="Comma-separated scope tag ids; intersects NpcSheet.scope_tags.",
    )
    p_gb.add_argument(
        "--include-unscoped",
        action="store_true",
        help="With --only-scope-tags, also run NPCs with empty scope_tags.",
    )
    p_gb.add_argument(
        "--n", type=int, default=3, help="Triggers to propose per NPC."
    )
    p_gb.add_argument("--brief", default=None)
    p_gb.add_argument("--concurrency", type=int, default=3)
    p_gb.add_argument("--dry-run", action="store_true")
    _add_llm_flags(p_gb)
    p_gb.set_defaults(func=_cmd_gen_barks)

    p_gg = p_gen_sub.add_parser(
        "greetings",
        help=(
            "Generate one greeting per enum-value of a project variable "
            "(typically time_of_day), per NPC. Emits state-aware Yarn "
            "nodes using <<if $var == \"value\">> chains."
        ),
    )
    p_gg.add_argument("--demo-dir", type=Path, required=True)
    p_gg.add_argument(
        "--variable",
        default="time_of_day",
        help="Project-variable id to key greetings on (default: time_of_day).",
    )
    p_gg.add_argument(
        "--only-npcs",
        default=None,
        help="Comma-separated NPC ids. Default: every NPC in characters.yaml.",
    )
    p_gg.add_argument("--concurrency", type=int, default=4)
    p_gg.add_argument("--dry-run", action="store_true")
    _add_llm_flags(p_gg)
    p_gg.set_defaults(func=_cmd_gen_greetings)

    p_rg = p_gen_sub.add_parser(
        "repeat-greeting",
        help=(
            "Generate visit-count-gated greeting variants per NPC (first "
            "visit / second visit / ... / else fallback). Uses Yarn's "
            "visited_count() builtin — no project variable required."
        ),
    )
    p_rg.add_argument("--demo-dir", type=Path, required=True)
    p_rg.add_argument(
        "--n",
        type=int,
        default=3,
        help=(
            "Total variants per NPC (last one is the else-fallback). Min 2."
        ),
    )
    p_rg.add_argument(
        "--only-npcs",
        default=None,
        help="Comma-separated NPC ids. Default: every NPC in characters.yaml.",
    )
    p_rg.add_argument("--concurrency", type=int, default=4)
    p_rg.add_argument("--dry-run", action="store_true")
    _add_llm_flags(p_rg)
    p_rg.set_defaults(func=_cmd_gen_repeat_greet)

    # ---- gen scene (v0.9.0) ----
    p_sc = p_gen_sub.add_parser(
        "scene",
        help=(
            "Generate one multi-NPC scene — two or more cast members "
            "trade lines with optional player-interjection branches. "
            "Output lands at out/scene_<id>.yarn."
        ),
    )
    p_sc.add_argument("--demo-dir", type=Path, required=True)
    p_sc.add_argument("--id", required=True,
                      help="Unique scene id (lower_snake_case).")
    p_sc.add_argument("--location", required=True,
                      help="Short phrase: 'rusted lantern common room'.")
    p_sc.add_argument("--npcs", required=True,
                      help="Comma-separated NPC ids (2+).")
    p_sc.add_argument("--setup", required=True,
                      help="One-sentence situational beat.")
    p_sc.add_argument("--no-player", action="store_true",
                      help="Generate a pure NPC-to-NPC scene (no interjections).")
    p_sc.add_argument("--lines", type=int, default=8,
                      help="Target main-line count (4-14). Default 8.")
    p_sc.add_argument("--end-node", default=None,
                      help="Yarn node to jump to after the scene.")
    p_sc.add_argument("--out", type=Path, default=None)
    p_sc.add_argument("--temperature", type=float, default=0.9)
    _add_llm_flags(p_sc)
    p_sc.set_defaults(func=_cmd_gen_scene)

    # ---- list-factions (v0.9.0) ----
    p_lf = subs.add_parser(
        "list-factions",
        help=(
            "List factions from factions.yaml with NPC membership counts."
        ),
    )
    p_lf.add_argument("--demo-dir", type=Path, required=True)
    p_lf.add_argument("--json", action="store_true")
    p_lf.set_defaults(func=_cmd_list_factions)

    # ---- memory (v0.9.0) ----
    p_mem = subs.add_parser(
        "memory",
        help="Inspect / edit the per-project memory store (memory.json).",
    )
    p_mem_sub = p_mem.add_subparsers(dest="memory_command", required=True)

    p_ms = p_mem_sub.add_parser(
        "show",
        help=(
            "Show stored events. With --npc <id>, render the memory block "
            "that would be injected into that NPC's prompt."
        ),
    )
    p_ms.add_argument("--demo-dir", type=Path, required=True)
    p_ms.add_argument("--npc", default=None)
    p_ms.add_argument("--max", type=int, default=20,
                      help="Limit on events rendered.")
    p_ms.add_argument("--json", action="store_true")
    p_ms.set_defaults(func=_cmd_memory_show)

    p_mr = p_mem_sub.add_parser(
        "record",
        help=(
            "Record one event — typically the runtime does this, but useful "
            "for scripting demos + tests."
        ),
    )
    p_mr.add_argument("--demo-dir", type=Path, required=True)
    p_mr.add_argument("--npc", required=True, help="NPC id the event is about.")
    p_mr.add_argument("--type", required=True,
                      help="Event tag: 'player_lied', 'gift_given', etc.")
    p_mr.add_argument("--summary", required=True,
                      help="One-sentence description from the NPC's POV.")
    p_mr.add_argument("--salience",
                      choices=["trivial", "notable", "pivotal"],
                      default="notable")
    p_mr.add_argument("--faction", default=None,
                      help="Optional faction tag — event is shared with every member.")
    p_mr.add_argument("--advance", type=int, default=0,
                      help="Advance turn counter before recording (default 0).")
    p_mr.set_defaults(func=_cmd_memory_record)

    # ---- quest (v0.21.0) ----
    p_q = subs.add_parser(
        "quest",
        help="Manage quests + story-state gating declared in quests.yaml.",
    )
    p_q_sub = p_q.add_subparsers(dest="quest_command", required=True)

    p_q_list = p_q_sub.add_parser("list", help="List all quests + current stages.")
    p_q_list.add_argument("--demo-dir", type=Path, required=True)
    p_q_list.set_defaults(func=_cmd_quest_list)

    p_q_show = p_q_sub.add_parser("show", help="Show one quest in detail.")
    p_q_show.add_argument("--demo-dir", type=Path, required=True)
    p_q_show.add_argument("--id", required=True)
    p_q_show.set_defaults(func=_cmd_quest_show)

    p_q_set = p_q_sub.add_parser(
        "set",
        help="Set a quest to a specific stage (advance or rewind).",
    )
    p_q_set.add_argument("--demo-dir", type=Path, required=True)
    p_q_set.add_argument("--id", required=True)
    p_q_set.add_argument("--stage", required=True)
    p_q_set.set_defaults(func=_cmd_quest_set)

    p_q_adv = p_q_sub.add_parser(
        "advance",
        help="Advance a quest to the next stage.",
    )
    p_q_adv.add_argument("--demo-dir", type=Path, required=True)
    p_q_adv.add_argument("--id", required=True)
    p_q_adv.set_defaults(func=_cmd_quest_advance)

    # ---- emotion (v0.20.0) ----
    p_em = subs.add_parser(
        "emotion",
        help="Inspect an NPC's current emotional state derived from memory.",
    )
    p_em_sub = p_em.add_subparsers(dest="emotion_command", required=True)
    p_em_show = p_em_sub.add_parser(
        "show",
        help="Print the derived Plutchik intensities + dominant emotion.",
    )
    p_em_show.add_argument("--demo-dir", type=Path, required=True)
    p_em_show.add_argument("--npc", required=True)
    p_em_show.add_argument("--decay-per-turn", type=float, default=0.05)
    p_em_show.add_argument("--json", action="store_true")
    p_em_show.set_defaults(func=_cmd_emotion_show)

    # ---- eval (v0.22.0) ----
    p_ev = subs.add_parser(
        "eval",
        help=(
            "Score dialogue quality for an NPC cast against a curated case "
            "suite. Writes markdown + JSON reports. Exit 0 = all-pass, "
            "2 = at least one case failed."
        ),
    )
    p_ev.add_argument("--demo-dir", type=Path, required=True)
    p_ev.add_argument(
        "--suite",
        type=Path,
        default=None,
        help=(
            "JSON file with a list of EvalCase objects. Default: the "
            "built-in Rusted Lantern suite (20 cases)."
        ),
    )
    p_ev.add_argument(
        "--only-ids",
        default=None,
        help="Comma-separated case ids to run (filters the suite).",
    )
    p_ev.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Cap on cases after filtering (0 = no cap). Useful for smoke tests.",
    )
    p_ev.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Directory for eval_report.md + eval_report.json (default <demo-dir>/out).",
    )
    _add_llm_flags(p_ev)
    p_ev.set_defaults(func=_cmd_eval)

    # ---- trajectory (v0.17.0) ----
    p_t = subs.add_parser(
        "trajectory",
        help=(
            "Inspect / simulate an NPC's relationship trajectory with "
            "the player — current waypoint, score, distance to next."
        ),
    )
    p_t_sub = p_t.add_subparsers(dest="trajectory_command", required=True)

    p_t_show = p_t_sub.add_parser(
        "show",
        help="Print the NPC's trajectory + current waypoint against memory.json.",
    )
    p_t_show.add_argument("--demo-dir", type=Path, required=True)
    p_t_show.add_argument("--npc", required=True)
    p_t_show.add_argument("--json", action="store_true")
    p_t_show.set_defaults(func=_cmd_trajectory_show)

    p_t_sim = p_t_sub.add_parser(
        "simulate",
        help=(
            "Preview where the NPC would land given a sequence of "
            "hypothetical event_types — useful for tuning thresholds."
        ),
    )
    p_t_sim.add_argument("--demo-dir", type=Path, required=True)
    p_t_sim.add_argument("--npc", required=True)
    p_t_sim.add_argument(
        "--events", required=True,
        help="Comma-separated event_types: 'gift_given,secret_shared,player_lied'.",
    )
    p_t_sim.set_defaults(func=_cmd_trajectory_simulate)

    # ---- ethics (v0.16.0) ----
    p_e = subs.add_parser(
        "ethics",
        help=(
            "Inspect the NPC's ethical reading of the player — how the "
            "memory store's accumulated events land through that NPC's "
            "own hidden moral profile."
        ),
    )
    p_e_sub = p_e.add_subparsers(dest="ethics_command", required=True)

    p_e_judge = p_e_sub.add_parser(
        "judge",
        help="Print the NPC's score + per-axis breakdown + top events.",
    )
    p_e_judge.add_argument("--demo-dir", type=Path, required=True)
    p_e_judge.add_argument("--npc", required=True)
    p_e_judge.add_argument("--json", action="store_true")
    p_e_judge.set_defaults(func=_cmd_ethics_judge)

    # ---- unseen (v0.15.0) ----
    p_u = subs.add_parser(
        "unseen",
        help=(
            "Manage unseen-character slots — mentioned-but-never-met "
            "NPCs whose canon accumulates until the player encounters "
            "them, at which point materialise a full sheet from canon."
        ),
    )
    p_u_sub = p_u.add_subparsers(dest="unseen_command", required=True)

    p_u_list = p_u_sub.add_parser("list", help="List every unseen slot.")
    p_u_list.add_argument("--demo-dir", type=Path, required=True)
    p_u_list.add_argument("--json", action="store_true")
    p_u_list.set_defaults(func=_cmd_unseen_list)

    p_u_show = p_u_sub.add_parser(
        "show",
        help="Show one slot's accumulated canon block.",
    )
    p_u_show.add_argument("--demo-dir", type=Path, required=True)
    p_u_show.add_argument("--id", required=True)
    p_u_show.set_defaults(func=_cmd_unseen_show)

    p_u_decl = p_u_sub.add_parser(
        "declare",
        help=(
            "Create (or update) an unseen-character slot. Idempotent — "
            "running twice doesn't reset accumulated mentions."
        ),
    )
    p_u_decl.add_argument("--demo-dir", type=Path, required=True)
    p_u_decl.add_argument("--id", required=True,
        help="Lower_snake_case stable id (becomes the NPC id on materialise).")
    p_u_decl.add_argument("--name", default=None, help="Display name hint.")
    p_u_decl.add_argument("--role", default=None, help="Role hint (one phrase).")
    p_u_decl.set_defaults(func=_cmd_unseen_declare)

    p_u_rec = p_u_sub.add_parser(
        "record",
        help="Record a mention against a declared slot.",
    )
    p_u_rec.add_argument("--demo-dir", type=Path, required=True)
    p_u_rec.add_argument("--id", required=True, help="Unseen canonical id.")
    p_u_rec.add_argument("--source", required=True,
        help="NPC id who spoke the mention.")
    p_u_rec.add_argument("--context", required=True,
        help="One-sentence canon paraphrase.")
    p_u_rec.add_argument("--turn", type=int, default=0)
    p_u_rec.add_argument("--scene", default=None,
        help="Optional scene-context tag.")
    p_u_rec.set_defaults(func=_cmd_unseen_record)

    p_u_mat = p_u_sub.add_parser(
        "materialize",
        help=(
            "Generate a full NpcSheet from the accumulated canon. "
            "Prints YAML; pass --commit to append to characters.yaml + "
            "flag the slot materialised."
        ),
    )
    p_u_mat.add_argument("--demo-dir", type=Path, required=True)
    p_u_mat.add_argument("--id", required=True)
    p_u_mat.add_argument("--new-id", default=None,
        help="Override the resulting NPC id (defaults to canonical_id).")
    p_u_mat.add_argument("--commit", action="store_true",
        help="Append to characters.yaml + mark the slot materialised.")
    p_u_mat.add_argument("--temperature", type=float, default=0.85)
    _add_llm_flags(p_u_mat)
    p_u_mat.set_defaults(func=_cmd_unseen_materialize)

    # ---- voice (v0.14.0) ----
    p_v = subs.add_parser(
        "voice",
        help="Inspect an NPC's voice lenses and preview active compositions.",
    )
    p_v_sub = p_v.add_subparsers(dest="voice_command", required=True)

    p_v_show = p_v_sub.add_parser(
        "show",
        help=(
            "List an NPC's voice lenses; pass --active to mark which "
            "would be on in a given scene."
        ),
    )
    p_v_show.add_argument("--demo-dir", type=Path, required=True)
    p_v_show.add_argument("--npc", required=True)
    p_v_show.add_argument(
        "--active", default=None,
        help="Comma-separated lens ids the runtime would have active.",
    )
    p_v_show.set_defaults(func=_cmd_voice_show)

    # ---- player (v0.13.0) ----
    p_pl = subs.add_parser(
        "player",
        help=(
            "Inspect / update / rebuild the player behavioural profile "
            "(player_profile.json). Observer NPCs receive this block."
        ),
    )
    p_pl_sub = p_pl.add_subparsers(dest="player_command", required=True)

    p_pl_show = p_pl_sub.add_parser("show",
        help="Print the current profile with axis bars.")
    p_pl_show.add_argument("--demo-dir", type=Path, required=True)
    p_pl_show.add_argument("--json", action="store_true")
    p_pl_show.set_defaults(func=_cmd_player_show)

    p_pl_rebuild = p_pl_sub.add_parser(
        "rebuild",
        help=(
            "Regenerate the profile from scratch against the memory "
            "store's event_types — useful when writers change the "
            "axis-delta map mid-campaign."
        ),
    )
    p_pl_rebuild.add_argument("--demo-dir", type=Path, required=True)
    p_pl_rebuild.add_argument(
        "--decay-rate", type=float, default=0.0,
        help="Per-event decay in [0, 1]. 0 = no decay (default).",
    )
    p_pl_rebuild.set_defaults(func=_cmd_player_rebuild)

    p_pl_up = p_pl_sub.add_parser("update",
        help="Apply one event (by event_type) to the profile.")
    p_pl_up.add_argument("--demo-dir", type=Path, required=True)
    p_pl_up.add_argument("--event-type", required=True,
        help="e.g. 'threat', 'gift_given', 'player_lied'.")
    p_pl_up.set_defaults(func=_cmd_player_update)

    # ---- export (v0.12.0) ----
    p_exp = subs.add_parser(
        "export",
        help="Emit derived data bundles for runtime integration.",
    )
    p_exp_sub = p_exp.add_subparsers(dest="export_command", required=True)

    p_exp_ic = p_exp_sub.add_parser(
        "improv-context",
        help=(
            "Write a JSON bundle one NPC needs at runtime for "
            "lore-consistent improvisation (character sheet block + "
            "world bible + rules). The Unity NpcForgeImprovClient reads "
            "this, does retrieval locally, and hands the prompt to a "
            "user-supplied LLM delegate."
        ),
    )
    p_exp_ic.add_argument("--demo-dir", type=Path, required=True)
    p_exp_ic.add_argument("--npc", required=True)
    p_exp_ic.add_argument("--out", type=Path, default=None)
    p_exp_ic.set_defaults(func=_cmd_export_improv_context)

    p_exp_cast = p_exp_sub.add_parser(
        "cast",
        help="Write cast.csv (id, name, role, tier, status, voice summary).",
    )
    p_exp_cast.add_argument("--demo-dir", type=Path, required=True)
    p_exp_cast.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output path (default: <demo-dir>/out/cast.csv).",
    )
    p_exp_cast.set_defaults(func=_cmd_export_cast)

    # ---- improv (v0.12.0) ----
    p_imp = subs.add_parser(
        "improv",
        help=(
            "Ask an NPC an off-script question. Lore-retrieval-augmented, "
            "single-turn, structured output. Uses one LLM call per query."
        ),
    )
    p_imp.add_argument("--demo-dir", type=Path, required=True)
    p_imp.add_argument("--npc", required=True)
    p_imp.add_argument("--query", required=True,
                       help="The player's question.")
    p_imp.add_argument("--top-k-lore", type=int, default=3,
                       help="Number of lore chunks to retrieve (default 3).")
    p_imp.add_argument("--temperature", type=float, default=0.8)
    p_imp.add_argument(
        "--lenses", default=None,
        help=(
            "Comma-separated voice lens ids to activate for this query: "
            "'tipsy,grindholt_formal'. Ids that don't resolve on the "
            "NPC are silently ignored."
        ),
    )
    _add_llm_flags(p_imp)
    p_imp.set_defaults(func=_cmd_improv)

    # ---- gen lines (v0.11.0) ----
    p_gl = p_gen_sub.add_parser(
        "lines",
        help=(
            "Generate a disposition-curated line bank for one NPC + slot. "
            "Produces N variants per tag combo, tagged for runtime "
            "context-aware selection."
        ),
    )
    p_gl.add_argument("--demo-dir", type=Path, required=True)
    p_gl.add_argument("--npc", required=True)
    p_gl.add_argument("--slot-id", required=True,
                      help="Lower_snake_case slot id ('greeting', 'ack_gift').")
    p_gl.add_argument("--slot-description", required=True,
                      help="One-line description: 'A greeting when the player walks up.'")
    p_gl.add_argument("--default-text", default=None,
                      help="Fallback string if no variant matches at runtime.")
    p_gl.add_argument(
        "--axes",
        nargs="*",
        default=None,
        help=(
            "Dimension axes to vary: 'disposition_tier=wary,trusted' "
            "'time_of_day=morning,dusk'. Omit an axis to leave it unvaried."
        ),
    )
    p_gl.add_argument("--n", type=int, default=2,
                      help="Variants per tag combo (default 2).")
    p_gl.add_argument("--concurrency", type=int, default=4)
    p_gl.add_argument("--temperature", type=float, default=0.95)
    p_gl.add_argument("--out", type=Path, default=None,
                      help="Override default output path (demo-dir/out/<npc>_lines.json).")
    p_gl.add_argument("--dry-run", action="store_true")
    _add_llm_flags(p_gl)
    p_gl.set_defaults(func=_cmd_gen_lines)

    # ---- arc (v0.10.0) ----
    p_arc = subs.add_parser(
        "arc",
        help="Inspect / simulate campaign-scale character arcs.",
    )
    p_arc_sub = p_arc.add_subparsers(dest="arc_command", required=True)

    p_arc_show = p_arc_sub.add_parser(
        "show",
        help=(
            "Show an NPC's declared arc and which stages are currently "
            "active given the project's memory.json + provided standings."
        ),
    )
    p_arc_show.add_argument("--demo-dir", type=Path, required=True)
    p_arc_show.add_argument("--npc", required=True)
    p_arc_show.add_argument(
        "--standing",
        default=None,
        help=(
            "Faction standings: 'lantern_regulars=20,miners=-5'. Only "
            "relevant for arcs that gate on standing."
        ),
    )
    p_arc_show.add_argument("--json", action="store_true")
    p_arc_show.set_defaults(func=_cmd_arc_show)

    p_arc_sim = p_arc_sub.add_parser(
        "simulate",
        help=(
            "Preview which arc stages would be active given a synthetic "
            "memory state + standings. Writes nothing — read-only."
        ),
    )
    p_arc_sim.add_argument("--demo-dir", type=Path, required=True)
    p_arc_sim.add_argument("--npc", required=True)
    p_arc_sim.add_argument("--pivotal", type=int, default=0,
                           help="Synthetic pivotal events to inject.")
    p_arc_sim.add_argument("--notable", type=int, default=0,
                           help="Synthetic notable events to inject.")
    p_arc_sim.add_argument(
        "--types", default=None,
        help=(
            "Comma-separated event_type tags to inject as pivotal events — "
            "useful for triggers that require specific event types "
            "(e.g. 'secret_shared,gift_given')."
        ),
    )
    p_arc_sim.add_argument(
        "--standing", default=None,
        help="Faction standings: 'lantern_regulars=20,miners=-5'.",
    )
    p_arc_sim.set_defaults(func=_cmd_arc_simulate)

    # ---- resolve (nested) ----
    p_res = subs.add_parser(
        "resolve", help="Fill in placeholder / stub entries."
    )
    p_res_sub = p_res.add_subparsers(dest="resolve_command", required=True)

    p_rs = p_res_sub.add_parser(
        "stubs",
        help="Expand every '_generate: true' NPC stub into a full sheet.",
    )
    p_rs.add_argument("--demo-dir", type=Path, required=True)
    p_rs.add_argument(
        "--only-ids",
        default=None,
        help="Comma-separated stub ids to resolve. Default: all stubs.",
    )
    p_rs.add_argument("--concurrency", type=int, default=3)
    p_rs.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve but do not rewrite characters.yaml.",
    )
    p_rs.add_argument(
        "--narrative-preset",
        dest="narrative_preset",
        default=None,
        choices=["indie_minimal", "rpg_standard", "cinematic_rpg"],
        help="Override npcforge_project.yaml for stub expansion.",
    )
    _add_topology_depth_flags(p_rs)
    _add_llm_flags(p_rs)
    p_rs.set_defaults(func=_cmd_resolve_stubs)

    # ---- engine-sync ----
    p_es = subs.add_parser(
        "engine-sync",
        help=(
            "Copy generated .yarn + lines.csv into a game engine's project "
            "tree (Unity / Unreal)."
        ),
    )
    p_es.add_argument("--demo-dir", type=Path, required=True)
    p_es.add_argument(
        "--project-dir",
        type=Path,
        required=True,
        help=(
            "Engine project root. Unity: folder with Assets/. Unreal: "
            "folder with Content/."
        ),
    )
    p_es.add_argument(
        "--engine",
        required=True,
        choices=["unity", "unreal"],
    )
    p_es.add_argument(
        "--source-dir",
        type=Path,
        default=None,
        help=(
            "Source directory to sync from. Defaults to <demo-dir>/out. "
            "Use to sync a frozen snapshot (e.g. sample_output/)."
        ),
    )
    p_es.add_argument(
        "--install-scripts",
        action="store_true",
        help=(
            "Also copy the engine's runtime glue scripts (Unity-only as of "
            "v0.7.1: the C# drop-in from examples/unity_integration)."
        ),
    )
    p_es.add_argument(
        "--scripts-source",
        dest="scripts_source_dir",
        type=Path,
        default=None,
        help="Override source directory for runtime glue scripts.",
    )
    p_es.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan the sync without writing anything.",
    )
    p_es.add_argument(
        "--verbose",
        action="store_true",
        help="Log every file action.",
    )
    p_es.set_defaults(func=_cmd_engine_sync)

    # ---- play ----
    p_play = subs.add_parser(
        "play",
        help=(
            "Terminal playback of generated Yarn files (walk-up branches or "
            "bark libraries)."
        ),
    )
    p_play.add_argument("--demo-dir", type=Path, required=True)
    p_play.add_argument("--npc", required=True, help="NPC id to play.")
    p_play.add_argument(
        "--intent",
        default=None,
        help=(
            "Play only one intent branch (matches the Yarn option label "
            "case-insensitively; partial match allowed)."
        ),
    )
    p_play.add_argument(
        "--bark",
        default=None,
        help=(
            "Play the bark library for this trigger id (e.g. greet_patron). "
            "Mutually exclusive with --intent / --greet / --repeat-greet."
        ),
    )
    p_play.add_argument(
        "--greet",
        default=None,
        metavar="VARIABLE",
        help=(
            "Play the enum-keyed greeting node for the given variable id "
            "(default target: time_of_day). Shows one line per enum value."
        ),
    )
    p_play.add_argument(
        "--repeat-greet",
        action="store_true",
        help=(
            "Play the visit-count-gated greeting node for this NPC. "
            "Mutually exclusive with --intent / --bark / --greet."
        ),
    )
    p_play.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Directory containing .yarn files (default: <demo-dir>/out).",
    )
    p_play.add_argument(
        "--tempo",
        type=float,
        default=0.0,
        help=(
            "Pacing multiplier — 0 = print instantly, 1.0 = ~speaking pace "
            "(80 ms/word)."
        ),
    )
    p_play.add_argument(
        "--wait",
        action="store_true",
        help="Pause for Enter between each line.",
    )
    p_play.set_defaults(func=_cmd_play)

    # ---- game ----
    p_game = subs.add_parser(
        "game",
        help=(
            "Interactive CLI game: approach NPCs, pick intents, watch "
            "relationships shift. Uses pre-built walk-up Yarn files."
        ),
    )
    p_game.add_argument("--demo-dir", type=Path, required=True)
    p_game.add_argument(
        "--tempo",
        type=float,
        default=0.35,
        help="Seconds between dialogue lines (0 = instant).",
    )
    p_game.set_defaults(func=_cmd_game)

    # ---- tape-game (demo loop + GIF) ----
    p_tape = subs.add_parser(
        "tape-game",
        help=(
            "Tiny CLI visual-novel loop over pre-built walk-up Yarn; "
            "optional GIF recording (pip install 'npcforge[tape]')."
        ),
    )
    p_tape.add_argument("--demo-dir", type=Path, required=True)
    p_tape.add_argument(
        "--gif",
        type=Path,
        default=None,
        help="Write an animated GIF of each screen (requires Pillow).",
    )
    p_tape.add_argument(
        "--auto-turns",
        type=int,
        default=0,
        help=(
            "Non-interactive: play this many conversation rounds "
            "(0 = interactive stdin)."
        ),
    )
    p_tape.add_argument(
        "--follow-quest",
        action="store_true",
        help=(
            "Play tape_auto.yaml beats in order (best for demos with "
            "tape_quest.yaml + GIF)."
        ),
    )
    p_tape.add_argument(
        "--frame-ms",
        type=int,
        default=750,
        help="Milliseconds per GIF frame (default 750).",
    )
    p_tape.add_argument(
        "--tape-width",
        type=int,
        default=80,
        metavar="COLS",
        help="Wrap width for terminal + GIF text (default 80).",
    )
    p_tape.add_argument(
        "--tape-height",
        type=int,
        default=52,
        metavar="ROWS",
        help=(
            "Rows per GIF page; taller screens become multiple GIF frames "
            "(default 52)."
        ),
    )
    p_tape.add_argument(
        "--regenerate",
        action="store_true",
        help="Run walk_up build_pipeline first (needs LLM API key).",
    )
    _add_llm_flags(p_tape)
    p_tape.set_defaults(func=_cmd_tape_game)

    # ---- mcp ----
    p_mcp = subs.add_parser(
        "mcp", help="Start the MCP server over stdio."
    )
    p_mcp.set_defaults(func=_cmd_mcp)

    return root


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    return asyncio.run(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
