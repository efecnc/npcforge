"""Voice-consistency scoring.

For each walk-up branch, computes an embedding-space similarity between the
NPC's generated assistant turns and the reference ``sample_lines`` from the
sheet. Produces one score per intent in ``[0, 1]``:

- 1.0 = every assistant turn in this branch is (roughly) as close in
  embedding space as the NPC's sample lines are to themselves.
- 0.0 = orthogonal.

Scoring is a single batched embedding call per NPC, so cost per run is low
compared to the walk-up generation itself. When the embedding provider
fails or an NPC has no sample lines, the score dict for that NPC is empty —
the caller surfaces ``voice_scoring_enabled=False`` in the manifest.
"""

from __future__ import annotations

import logging
import math
from typing import Iterable

from afterimage.evaluator import default_embedding_provider_config
from afterimage.key_management import SmartKeyPool
from afterimage.providers.embedding_providers import EmbeddingProviderFactory

from .schemas import NpcSheet
from .yarn import Branch

logger = logging.getLogger(__name__)


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two equal-length float vectors. Returns 0 when either is zero."""
    if not a or not b:
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def _normalise(score: float) -> float:
    """Clamp a cosine similarity (which can go slightly negative on noise) to [0, 1]."""
    if score < 0.0:
        return 0.0
    if score > 1.0:
        return 1.0
    return score


def _assistant_turns(branch_turns: Iterable[dict]) -> list[str]:
    out: list[str] = []
    for t in branch_turns:
        if t.get("role") == "assistant":
            content = (t.get("content") or "").strip()
            if content:
                out.append(content)
    return out


async def score_voice_consistency(
    *,
    npc: NpcSheet,
    branches: list[Branch],
    api_key: str,
    provider: str,
) -> dict[str, float]:
    """Return ``{intent_id: voice_score}`` for one NPC's walk-up branches.

    Empty ``sample_lines`` or no assistant turns → empty map. Failures are
    logged and swallowed (score simply omitted). Uses whichever embedding
    backend :func:`afterimage.evaluator.default_embedding_provider_config`
    selects for the current chat provider.
    """
    samples = [s.strip() for s in npc.sample_lines if s and s.strip()]
    if not samples or not branches:
        return {}

    # Collect every assistant turn per branch so we can batch one embedding call.
    branch_turns: list[tuple[str, list[str]]] = []
    for intent, turns in branches:
        asst = _assistant_turns(turns)
        if asst:
            branch_turns.append((intent.id, asst))

    if not branch_turns:
        return {}

    all_texts: list[str] = list(samples)
    branch_ranges: list[tuple[str, int, int]] = []  # (intent_id, start, end)
    cursor = len(all_texts)
    for intent_id, asst in branch_turns:
        start = cursor
        all_texts.extend(asst)
        cursor = len(all_texts)
        branch_ranges.append((intent_id, start, cursor))

    config = default_embedding_provider_config(provider)
    key_pool = SmartKeyPool.from_single_key(api_key)
    embedder = EmbeddingProviderFactory.create(config, key_pool=key_pool)

    try:
        vectors = await embedder.embed(all_texts)
    except Exception as exc:
        logger.warning("voice-consistency embedding failed for %s: %s", npc.id, exc)
        try:
            await embedder.aclose()
        except Exception:
            pass
        return {}

    try:
        await embedder.aclose()
    except Exception:
        pass

    if len(vectors) != len(all_texts):
        logger.warning(
            "voice-consistency: got %d vectors for %d inputs; skipping %s",
            len(vectors),
            len(all_texts),
            npc.id,
        )
        return {}

    sample_vecs = vectors[: len(samples)]

    scores: dict[str, float] = {}
    for intent_id, start, end in branch_ranges:
        turn_vecs = vectors[start:end]
        if not turn_vecs:
            continue
        # For each generated turn take its best match against any sample line,
        # then average across turns. This rewards branches that stay close to
        # at least one canonical voice exemplar on every line.
        per_turn: list[float] = []
        for tv in turn_vecs:
            best = max((_cosine(tv, sv) for sv in sample_vecs), default=0.0)
            per_turn.append(_normalise(best))
        scores[intent_id] = sum(per_turn) / len(per_turn)

    return scores
