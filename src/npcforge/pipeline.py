"""Generation pipeline — one branch per (NPC, archetype) over afterimage.

Each call to :func:`generate_branch` runs an independent afterimage
``ConversationGenerator`` with a **single-archetype** persona pool, which
guarantees deterministic coverage (unlike relying on afterimage's internal
persona cycling under concurrent calls).

Parallelism lives in :func:`generate_for_npc`, which fans out archetypes for
one NPC via ``asyncio.gather`` with a configurable semaphore.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from afterimage import (
    ConversationGenerator,
    InMemoryDocumentProvider,
    PersonaInstructionGeneratorCallback,
)
from afterimage.storage import JSONLStorage
from afterimage.types import PersonaEntry

from .prompts import (
    build_npc_respondent_prompt,
    render_character_sheet,
    render_player_archetype,
)
from .schemas import NpcSheet, PlayerArchetype
from .yarn import (
    Branch,
    DialogTurn,
    render_world_start_node,
    render_yarn_node_for_npc,
)


# ---------------------------------------------------------------------------
# afterimage wiring
# ---------------------------------------------------------------------------


def _build_provider(
    world_bible: str,
    npc: NpcSheet,
    archetype: PlayerArchetype,
) -> InMemoryDocumentProvider:
    """Single-document provider seeded with exactly one archetype persona."""
    doc_text = f"{world_bible}\n\n---\n\n{render_character_sheet(npc)}"
    provider = InMemoryDocumentProvider([doc_text])
    doc = provider.get_all()[0]
    doc.personas = [
        PersonaEntry(
            descriptions=[render_player_archetype(archetype)],
            metadata={"generation_depth": 0},
        )
    ]
    return provider


async def generate_branch(
    *,
    npc: NpcSheet,
    archetype: PlayerArchetype,
    world_bible: str,
    api_key: str,
    model_name: str | None,
    model_provider_name: str,
    max_turns: int,
    out_path: Path,
) -> Branch:
    """Run one Correspondent↔Respondent loop for (NPC, archetype).

    Appends the raw conversation to ``out_path`` (shared across archetypes
    for this NPC) and returns the archetype plus its turn list.
    """
    provider = _build_provider(world_bible, npc, archetype)

    instruction_cb = PersonaInstructionGeneratorCallback(
        api_key=api_key,
        documents=provider,
        model_name=model_name,
        model_provider_name=model_provider_name,
        num_random_contexts=1,
        n_instructions=1,
    )

    storage = JSONLStorage(conversations_path=str(out_path))

    generator = ConversationGenerator(
        respondent_prompt=build_npc_respondent_prompt(npc),
        api_key=api_key,
        model_name=model_name,
        model_provider_name=model_provider_name,
        instruction_generator_callback=instruction_cb,
        storage=storage,
    )

    await generator.generate(
        num_dialogs=1,
        max_turns=max_turns,
        max_concurrency=1,
    )

    # Storage file is append-only and shared across archetypes for this NPC —
    # walk it backwards and pick the most recent row whose persona matches.
    conversations = generator.load_conversations()
    turns: list[DialogTurn] = []
    for conv in reversed(conversations):
        persona_text = (getattr(conv, "persona", "") or "").lower()
        if archetype.id.lower() in persona_text or archetype.name.lower() in persona_text:
            turns = [{"role": t.role, "content": t.content} for t in conv.conversations]
            break
    return archetype, turns


async def generate_for_npc(
    *,
    npc: NpcSheet,
    archetypes: list[PlayerArchetype],
    world_bible: str,
    api_key: str,
    model_name: str | None,
    model_provider_name: str,
    max_turns: int,
    max_concurrency: int,
    out_path: Path,
) -> list[Branch]:
    """Generate one branch per archetype in parallel, bounded by a semaphore."""
    out_path.unlink(missing_ok=True)

    semaphore = asyncio.Semaphore(max(max_concurrency, 1))

    async def _bounded(archetype: PlayerArchetype) -> Branch:
        async with semaphore:
            return await generate_branch(
                npc=npc,
                archetype=archetype,
                world_bible=world_bible,
                api_key=api_key,
                model_name=model_name,
                model_provider_name=model_provider_name,
                max_turns=max_turns,
                out_path=out_path,
            )

    results = await asyncio.gather(*(_bounded(a) for a in archetypes))
    return [r for r in results if r[1]]


# ---------------------------------------------------------------------------
# Top-level driver (used by the CLI; importable from tests / notebooks)
# ---------------------------------------------------------------------------


async def run_all(
    *,
    npcs: list[NpcSheet],
    archetypes: list[PlayerArchetype],
    world_bible: str,
    api_key: str,
    out_dir: Path,
    model_provider_name: str = "gemini",
    model_name: str | None = None,
    max_turns: int = 3,
    archetype_concurrency: int = 3,
    progress: bool = True,
) -> dict[str, Path]:
    """Run the full pipeline for every NPC and write all Yarn files.

    Returns a map of NPC id -> path of the produced ``.yarn`` file. A
    ``world.yarn`` master node is also written and included under the key
    ``"__world__"``.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    for npc in npcs:
        jsonl_path = out_dir / f"{npc.id}.jsonl"
        yarn_path = out_dir / f"{npc.id}.yarn"
        if progress:
            print(f"[{npc.id}] generating {len(archetypes)} branches ...")
        branches = await generate_for_npc(
            npc=npc,
            archetypes=archetypes,
            world_bible=world_bible,
            api_key=api_key,
            model_name=model_name,
            model_provider_name=model_provider_name,
            max_turns=max_turns,
            max_concurrency=archetype_concurrency,
            out_path=jsonl_path,
        )
        if not branches:
            if progress:
                print(f"[{npc.id}] no branches produced; skipping .yarn")
            continue
        yarn_path.write_text(render_yarn_node_for_npc(npc, branches), encoding="utf-8")
        written[npc.id] = yarn_path
        if progress:
            print(
                f"[{npc.id}] wrote {yarn_path.name} "
                f"({len(branches)}/{len(archetypes)} branches)"
            )

    world_path = out_dir / "world.yarn"
    world_path.write_text(render_world_start_node(npcs), encoding="utf-8")
    written["__world__"] = world_path
    if progress:
        print(f"Wrote {world_path.name}")
    return written
