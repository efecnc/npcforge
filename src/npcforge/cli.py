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

from .tools import (
    BuildPipelineInput,
    GenBarksInput,
    GenIntentsInput,
    GenNpcsInput,
    InferWorldProfileInput,
    ListNpcsInput,
    ResolveStubsInput,
    ShowWorldProfileInput,
    build_pipeline,
    gen_barks,
    gen_intents,
    gen_npcs,
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
        lint_total = manifest.get("lint", {}).get("total_hits", 0)
        print(
            f"done: elapsed={manifest.get('elapsed_seconds')}s "
            f"lint_hits={lint_total} out={result.out_dir}"
        )

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
            for_npcs=_split_csv(args.for_npcs),
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
        "--for-npcs",
        default=None,
        help=(
            "Comma-separated NPC ids. Default: every NPC in characters.yaml."
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
