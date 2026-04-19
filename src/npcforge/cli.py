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
        max_turns=args.turns,
        intent_concurrency=args.intent_concurrency,
        bark_concurrency=args.bark_concurrency,
        score_voice=args.score_voice,
        out_dir=args.out,
        provider=args.provider,
        model=args.model,
        api_key=key,
    )

    if not args.quiet:
        print(
            f"build: mode={input_.mode} demo_dir={input_.demo_dir} "
            f"only={input_.only_npcs or 'all'}"
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
    dialogue, warnings = await generate_scene(
        scene=scene,
        cast=npcs,
        factions=factions,
        memory_store=store,
        api_key=api_key,
        model_name=args.model,
        model_provider_name=args.provider,
        temperature=args.temperature,
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
    _add_llm_flags(p)
    p.set_defaults(func=_cmd_build)

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
    _add_llm_flags(p_rs)
    p_rs.set_defaults(func=_cmd_resolve_stubs)

    # ---- engine-sync ----
    p_es = subs.add_parser(
        "engine-sync",
        help=(
            "Copy generated .yarn + lines.csv into a game engine's project "
            "tree (Unity / Godot / Unreal)."
        ),
    )
    p_es.add_argument("--demo-dir", type=Path, required=True)
    p_es.add_argument(
        "--project-dir",
        type=Path,
        required=True,
        help=(
            "Engine project root. Unity: folder with Assets/. Unreal: "
            "folder with Content/. Godot: folder with project.godot."
        ),
    )
    p_es.add_argument(
        "--engine",
        required=True,
        choices=["unity", "godot", "unreal"],
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
