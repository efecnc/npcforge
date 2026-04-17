"""Command-line entrypoint for npcforge.

Installed as the ``npcforge`` console script via ``pyproject.toml``.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from .pipeline import run_all
from .schemas import load_archetypes, load_npcs, load_world_bible


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


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="npcforge",
        description=(
            "Generate Yarn Spinner branching NPC dialogue from a world bible, "
            "character sheets, and player archetypes."
        ),
    )
    parser.add_argument(
        "--demo-dir",
        type=Path,
        required=True,
        help="Directory containing lore/, characters.yaml, player_archetypes.yaml",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output directory for .jsonl and .yarn files (default: <demo-dir>/out)",
    )
    parser.add_argument(
        "--turns",
        type=int,
        default=3,
        help="Max back-and-forth turns per archetype branch (default: 3)",
    )
    parser.add_argument(
        "--archetype-concurrency",
        type=int,
        default=3,
        help="Max parallel archetype generations per NPC (default: 3)",
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
    archetypes = load_archetypes(demo_dir / "player_archetypes.yaml")

    api_key = resolve_api_key(args.provider, args.api_key_env)

    if not args.quiet:
        print(
            f"Loaded {len(npcs)} NPCs, {len(archetypes)} archetypes. "
            f"One branch per archetype per NPC via {args.provider}."
        )

    await run_all(
        npcs=npcs,
        archetypes=archetypes,
        world_bible=world_bible,
        api_key=api_key,
        out_dir=out_dir,
        model_provider_name=args.provider,
        model_name=args.model,
        max_turns=args.turns,
        archetype_concurrency=args.archetype_concurrency,
        progress=not args.quiet,
    )
    return 0


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
