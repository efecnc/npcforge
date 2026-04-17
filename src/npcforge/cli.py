"""Command-line entrypoint for npcforge.

Installed as the ``npcforge`` console script via ``pyproject.toml``.

Single subcommand (``build``) handles walk-up dialogue, barks, or both —
select with ``--mode``. ``--only-npcs`` restricts a run to a subset of IDs
for iteration speed.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from .pipeline import run_all
from .schemas import load_barks_config, load_intents, load_npcs, load_world_bible
from .validate import compile_yarn_files, ysc_available


_DEFAULT_ENV = {
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "local": "LOCAL_API_KEY",
}


def resolve_api_key(provider: str, env_override: str | None) -> str:
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


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="npcforge",
        description=(
            "Generate Yarn Spinner branching NPC dialogue (+ bark libraries) "
            "from a world bible, character sheets, player intents, and optional "
            "bark triggers."
        ),
    )
    parser.add_argument(
        "--demo-dir",
        type=Path,
        required=True,
        help="Directory containing lore/, characters.yaml, player_intents.yaml, optional barks.yaml",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output directory (default: <demo-dir>/out)",
    )
    parser.add_argument(
        "--mode",
        choices=["walk_up", "barks", "all"],
        default="walk_up",
        help="Which pipeline to run (default: walk_up)",
    )
    parser.add_argument(
        "--only-npcs",
        default=None,
        help="Comma-separated NPC ids to restrict the run (default: all)",
    )
    parser.add_argument(
        "--turns",
        type=int,
        default=3,
        help="Max back-and-forth turns per intent branch (default: 3)",
    )
    parser.add_argument(
        "--intent-concurrency",
        type=int,
        default=3,
        help="Max parallel intent generations per NPC (default: 3)",
    )
    parser.add_argument(
        "--bark-concurrency",
        type=int,
        default=4,
        help="Max parallel bark generations per (NPC, trigger) (default: 4)",
    )
    parser.add_argument(
        "--provider",
        default="gemini",
        choices=["gemini", "openai", "deepseek", "openrouter", "local"],
        help="LLM provider (default: gemini)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model name override (default: provider's afterimage default)",
    )
    parser.add_argument(
        "--api-key-env",
        default=None,
        help="Env var holding the API key. Default: GEMINI_API_KEY / OPENAI_API_KEY / etc.",
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip the post-run ysc compile check even if ysc is on PATH",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress output",
    )
    return parser


async def _run(args: argparse.Namespace) -> int:
    demo_dir: Path = args.demo_dir
    out_dir: Path = args.out or (demo_dir / "out")

    world_bible = load_world_bible(demo_dir / "lore")
    npcs = load_npcs(demo_dir / "characters.yaml")
    intents = load_intents(demo_dir / "player_intents.yaml")
    barks_cfg = load_barks_config(demo_dir / "barks.yaml")
    only = _split_csv(args.only_npcs) or None

    api_key = resolve_api_key(args.provider, args.api_key_env)

    if not args.quiet:
        print(
            f"Loaded {len(npcs)} NPCs, {len(intents)} intents, "
            f"{sum(len(b.triggers) for b in barks_cfg.barks)} bark triggers. "
            f"Mode: {args.mode} via {args.provider}."
        )

    await run_all(
        npcs=npcs,
        intents=intents,
        world_bible=world_bible,
        api_key=api_key,
        out_dir=out_dir,
        barks_config=barks_cfg,
        mode=args.mode,
        only_npcs=only,
        model_provider_name=args.provider,
        model_name=args.model,
        max_turns=args.turns,
        intent_concurrency=args.intent_concurrency,
        bark_concurrency=args.bark_concurrency,
        progress=not args.quiet,
    )

    if not args.no_validate:
        result = compile_yarn_files(out_dir)
        if result.ran and not args.quiet:
            print(
                "ysc compile: "
                + ("OK" if result.ok else f"FAIL ({result.note})")
            )
            if result.stdout:
                print(result.stdout.strip())
            if result.stderr:
                print(result.stderr.strip(), file=sys.stderr)
        elif not ysc_available() and not args.quiet:
            print(f"Note: {result.note}")
    return 0


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
