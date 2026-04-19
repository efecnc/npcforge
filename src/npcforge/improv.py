"""Lore-consistent improvisation (v0.12.0).

The first feature that puts an LLM in the player's critical path. Used
when the player asks a question that wasn't pre-scripted into the
Yarn walk-up tree or a line-bank slot — the runtime shells out to an
LLM with:

    1. The NPC's character sheet + faction + memory + arc context
       (same set of inputs the generator pipeline already composes).
    2. A retrieval slice over the world bible: 2-4 lore chunks whose
       words overlap the player's query.
    3. An explicit listing of the NPC's knowledge items with their
       gates, so the LLM can decide whether a given fact should
       reveal or deflect.

The retrieval we ship here is intentionally simple: IDF-weighted token
overlap against paragraph-split chunks. It's dependency-free, fast,
and "good enough" for lore bundles of the size npcforge projects
actually use (kilobytes, not gigabytes). Projects that want embedding-
based retrieval can replace :func:`retrieve_lore_chunks` with their
own implementation and pass the results through ``lore_chunks=``.

Latency note: this path costs one LLM call per query. Design around it
— trigger improv only when the player chooses "Ask anything" or when
the scripted option set can't plausibly cover the question. It is NOT
a replacement for walk-up dialogue; it's a fallback.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel, Field

from .memory import MemoryStore, summarize_for_npc
from .schemas import FactionsConfig, NpcSheet, VoiceLens

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------


_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-']*")
_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "but", "if", "so", "of", "to", "in",
    "on", "at", "by", "for", "from", "with", "as", "is", "was", "are",
    "were", "be", "been", "being", "have", "has", "had", "do", "does",
    "did", "it", "its", "this", "that", "these", "those", "i", "you",
    "he", "she", "they", "we", "me", "him", "her", "them", "us", "my",
    "your", "his", "their", "our", "what", "which", "who", "whom",
    "where", "when", "why", "how", "all", "any", "some", "no", "not",
    "yes", "too", "very", "just", "also",
})


def _tokens(text: str) -> list[str]:
    """Lowercase words, stopwords dropped, short tokens dropped."""
    return [
        w for w in _TOKEN_RE.findall(text.lower())
        if len(w) >= 2 and w not in _STOPWORDS
    ]


@dataclass
class LoreChunk:
    """One retrievable paragraph of world bible.

    ``source`` is a compact identifier — typically "lore/foo.md#p3" — so
    the prompt can cite the chunk's origin for writer debugging. The
    LLM does not quote the source in its output.
    """

    text: str
    source: str
    score: float = 0.0


def split_into_chunks(lore_bundle: str, source_prefix: str = "lore") -> list[LoreChunk]:
    """Split the lore bundle on blank lines into paragraph chunks.

    We preserve order so downstream logic can show chunks in the same
    sequence writers authored them. Each chunk is limited by the writer's
    paragraph breaks — we do not reflow. Empty/whitespace paragraphs
    are skipped.
    """
    chunks: list[LoreChunk] = []
    # Normalise line endings; split on one-or-more blank lines.
    normalised = lore_bundle.replace("\r\n", "\n").strip()
    if not normalised:
        return chunks
    for i, para in enumerate(re.split(r"\n\s*\n+", normalised)):
        stripped = para.strip()
        if not stripped:
            continue
        chunks.append(LoreChunk(
            text=stripped,
            source=f"{source_prefix}#p{i}",
        ))
    return chunks


def retrieve_lore_chunks(
    query: str,
    lore_bundle: str,
    *,
    top_k: int = 3,
    source_prefix: str = "lore",
) -> list[LoreChunk]:
    """Return the ``top_k`` most relevant chunks for ``query``.

    Scoring is IDF-weighted token overlap: a query word that appears in
    one chunk out of 50 is worth much more than one that appears in 40
    chunks. This biases toward specific named entities ("Forgetting",
    "Grindholt") over common verbs.

    If the query produces no tokens (all stopwords), returns the first
    ``top_k`` chunks so we at least ground the generator in *some*
    lore — better than no context at all.
    """
    chunks = split_into_chunks(lore_bundle, source_prefix=source_prefix)
    if not chunks:
        return []

    query_tokens = _tokens(query)
    if not query_tokens:
        return chunks[:top_k]

    # Per-chunk token sets for O(chunks) intersection.
    chunk_tokens: list[set[str]] = [set(_tokens(c.text)) for c in chunks]

    # IDF: log( (N+1) / (df+1) ) with add-one smoothing.
    df: dict[str, int] = {}
    for tokens in chunk_tokens:
        for t in tokens:
            df[t] = df.get(t, 0) + 1
    n = len(chunks)

    scored: list[LoreChunk] = []
    for i, c in enumerate(chunks):
        tokens_here = chunk_tokens[i]
        score = 0.0
        for qt in query_tokens:
            if qt in tokens_here:
                score += math.log((n + 1) / (df.get(qt, 0) + 1))
        if score > 0.0:
            scored.append(LoreChunk(text=c.text, source=c.source, score=score))

    scored.sort(key=lambda c: c.score, reverse=True)
    # When retrieval misses completely (all query tokens novel to the
    # bundle), fall back to the first chunks so the generator still has
    # *some* lore grounding.
    if not scored:
        return chunks[:top_k]
    return scored[:top_k]


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


def build_improv_system_prompt(
    npc: NpcSheet,
    *,
    lore_chunks: list[LoreChunk],
    factions: Optional[FactionsConfig] = None,
    memory_store: Optional[MemoryStore] = None,
    player_profile_block: str = "",
    active_lenses: Optional[list[VoiceLens]] = None,
    ethical_reading_block: str = "",
    trajectory_block: str = "",
) -> str:
    """System prompt for one improvised reply.

    Deliberately smaller than the walk-up respondent prompt — we don't
    need the ceremonial 12-rule block here because improv is a single
    short reply, not a conversation, and extra instructions dilute
    attention. We do repeat the most important invariants: stay in
    character, never volunteer gated knowledge, cite nothing outside
    the lore snippets shown.
    """
    from .prompts import render_character_sheet  # local import, avoid circular

    lore_block: str
    if lore_chunks:
        rendered = "\n\n".join(
            f"[{c.source}]\n{c.text.strip()}" for c in lore_chunks
        )
        lore_block = (
            "LORE SNIPPETS (authoritative — do not invent facts outside these):\n"
            f"{rendered}"
        )
    else:
        lore_block = (
            "LORE SNIPPETS: (none retrieved; ground your reply only in "
            "your character sheet)"
        )

    mem_block = ""
    if memory_store is not None:
        mem_block = summarize_for_npc(npc, memory_store)

    sheet = render_character_sheet(npc, factions=factions)

    rules = (
        "You are answering a question that wasn't pre-scripted for this "
        "character. Produce ONE short in-character reply. Constraints:\n"
        "1. Stay fully in character. First-person dialogue only. No "
        "   narration, no stage directions.\n"
        "2. Ground every factual claim in the lore snippets above OR in "
        "   your character sheet. If the question lands outside both, "
        "   deflect in-character — do not invent.\n"
        "3. Your 'Knowledge' block lists facts you possess. Honour gates: "
        "   reveal only when the player's question clearly satisfies the "
        "   gate, otherwise deflect using the tone of the sample "
        "   deflection lines.\n"
        "4. One to three short sentences. At most 60 words.\n"
        "5. Honour your vocabulary ceiling, forbidden words, and speech "
        "   quirks. Apply any active arc-stage voice shifts.\n"
        "6. Do not quote the lore snippets verbatim or cite their [source] "
        "   tags. Translate any facts you use into your own voice.\n"
    )

    blocks = [sheet, lore_block, rules.rstrip()]
    if mem_block:
        blocks.append(mem_block)
    if player_profile_block.strip() and npc.observes_player:
        blocks.append(player_profile_block.strip())
    if active_lenses:
        from .prompts import _render_voice_lenses  # avoid circular at import-time
        lens_block = _render_voice_lenses(active_lenses)
        if lens_block:
            blocks.append(lens_block)
    if ethical_reading_block.strip():
        blocks.append(ethical_reading_block.strip())
    if trajectory_block.strip():
        blocks.append(trajectory_block.strip())
    return "\n\n".join(blocks) + "\n"


# ---------------------------------------------------------------------------
# Structured output target
# ---------------------------------------------------------------------------


class ImprovReply(BaseModel):
    """Structured-output schema for one improvised reply.

    Splitting the reply into ``text`` + ``used_gate_id`` (optional)
    gives the runtime a cheap way to record memory events tied to
    knowledge reveals — the LLM tells us whether it opened a gated
    fact, and we can store ``secret_shared`` with the gate id so the
    next arc evaluation sees it.
    """

    text: str = Field(
        ...,
        description=(
            "The NPC's reply. 1-3 short sentences. First-person, in "
            "character, no narration."
        ),
    )
    used_gate_id: str = Field(
        default="",
        description=(
            "Empty unless the reply revealed one of the NPC's gated "
            "knowledge items — set to that item's id so the runtime can "
            "record a 'secret_shared' memory event."
        ),
    )
    declined_reason: str = Field(
        default="",
        description=(
            "Empty unless the reply was a deflection or refusal — set "
            "to a one-phrase reason ('gate not met', 'outside scope', "
            "'hostile disposition') for writer diagnostics."
        ),
    )


# ---------------------------------------------------------------------------
# Query entry point
# ---------------------------------------------------------------------------


async def improv_query(
    *,
    npc: NpcSheet,
    query: str,
    world_bible: str,
    factions: Optional[FactionsConfig],
    memory_store: Optional[MemoryStore],
    api_key: str,
    model_name: Optional[str],
    model_provider_name: str,
    top_k_lore: int = 3,
    temperature: float = 0.8,
    player_profile_block: str = "",
    active_lenses: Optional[list[VoiceLens]] = None,
    ethical_reading_block: str = "",
    trajectory_block: str = "",
) -> ImprovReply | None:
    """Run one improv call. Returns None on failure (callers fall back).

    The function is async so it slots into the existing pipeline's
    concurrency model, but most games will invoke it serially — there's
    a player waiting for the reply on the other end.
    """
    # Retrieval first — cheap, no network.
    chunks = retrieve_lore_chunks(query, world_bible, top_k=top_k_lore)

    system_prompt = build_improv_system_prompt(
        npc,
        lore_chunks=chunks,
        factions=factions,
        memory_store=memory_store,
        player_profile_block=player_profile_block,
        active_lenses=active_lenses,
        ethical_reading_block=ethical_reading_block,
        trajectory_block=trajectory_block,
    )

    # Imported here to avoid dragging the afterimage providers into
    # modules that only want retrieval.
    from afterimage.common import default_model_name as _AFTERIMAGE_DEFAULT_MODEL
    from afterimage.providers import LLMFactory

    effective_model = model_name or _AFTERIMAGE_DEFAULT_MODEL
    llm = LLMFactory.create(
        provider=model_provider_name,
        model_name=effective_model,
        api_key=api_key,
        system_instruction=system_prompt,
    )

    try:
        response = await llm.agenerate_structured(
            prompt=(
                "Player says: " + query.strip() + "\n\n"
                "Reply as the character. JSON matching ImprovReply."
            ),
            schema=ImprovReply,
            temperature=temperature,
        )
    except Exception as exc:
        logger.warning("improv query failed for %s: %s", npc.id, exc)
        return None

    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, ImprovReply):
        return parsed
    try:
        return ImprovReply.model_validate_json(response.text)
    except Exception as exc:
        logger.warning("improv JSON parse failed for %s: %s", npc.id, exc)
        return None
