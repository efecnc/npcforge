"""World profile — structured understanding of a game's lore.

The profile is inferred once from ``lore/*.md`` via a single LLM structured
call, cached to ``<demo_dir>/.npcforge/world_profile.json``, and referenced
by every downstream generator (NPCs / intents / barks). The writer can edit
the cached JSON to correct inferences; re-inferring only happens when
``overwrite_cache=True`` or the cache is missing.

The profile is *not* a configuration the writer fills in. The writer's lore
is authoritative; this module turns the lore into machine-readable form.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from afterimage.common import default_model_name as _AFTERIMAGE_DEFAULT_MODEL
from afterimage.providers import LLMFactory
from pydantic import BaseModel, Field

from .schemas import VocabularyCeiling, load_world_bible


Rating = Literal["E", "E10+", "T", "M", "AO"]


class CanonicalTerm(BaseModel):
    """One setting-specific name for a common concept.

    Expressed as an explicit pair because Gemini's structured-output API does
    not accept the JSON-Schema ``additionalProperties`` required by
    ``dict[str, str]``.
    """

    category: str = Field(
        ...,
        description=(
            "Plain-English category — e.g. 'currency', 'law_enforcement', "
            "'communication', 'magic_or_tech', 'transport'."
        ),
    )
    term: str = Field(
        ...,
        description="What this world calls it — e.g. 'eddies', 'NCPD'.",
    )


class WorldProfile(BaseModel):
    """Structured understanding of a game's setting, inferred from lore.

    All fields are populated by a single LLM structured call against
    ``lore/*.md``. Writers may edit the cached JSON directly to correct
    inferences without re-running the LLM.
    """

    genre: str = Field(
        ...,
        description=(
            "Free-text genre label in lower_snake_case — e.g. "
            "'cyberpunk_noir', 'low_fantasy', 'frontier_western', "
            "'space_opera'. Pick the narrowest accurate label."
        ),
    )
    era: str = Field(
        ...,
        description=(
            "Concrete era description including year when given in lore — "
            "e.g. 'late 2070s, post-Arasaka pullout' or "
            "'pre-industrial, sword and sorcery'."
        ),
    )
    tone: str = Field(
        ...,
        description=(
            "One-sentence tone description inferred from the lore's voice: "
            "register, mood, and pacing expectations for NPC dialogue."
        ),
    )
    likely_rating: Rating = Field(
        ...,
        description=(
            "ESRB-style content rating the lore implies: E, E10+, T, M, or AO. "
            "Pick conservatively when uncertain."
        ),
    )
    register_default: VocabularyCeiling = Field(
        ...,
        description=(
            "Default vocabulary ceiling when an NPC sheet does not specify "
            "one. Pick the register that fits the majority of the cast."
        ),
    )
    canonical_terms: list[CanonicalTerm] = Field(
        default_factory=list,
        description=(
            "Setting-specific words for common concepts. 3-8 entries is "
            "typical — enough to ground generators, not an encyclopedia. "
            "Include 'currency', 'law_enforcement', and 'communication' "
            "when the lore names them; add setting-specific categories "
            "like 'magic_or_tech' or 'transport' when relevant."
        ),
    )
    anachronism_blocklist: list[str] = Field(
        default_factory=list,
        description=(
            "Words that would break the setting's register (e.g. 'doth' in "
            "Night City; 'computer' in a sword-and-sorcery campaign; 'awesome' "
            "in 1899). 5-15 entries, focused on common offenders."
        ),
    )
    notes: str = Field(
        default="",
        description=(
            "Any short observation that does not fit the other fields and "
            "would help downstream generators stay consistent."
        ),
    )
    inferred_from: list[str] = Field(
        default_factory=list,
        description="Lore filenames this profile was inferred from.",
    )


_PROFILE_SYSTEM_INSTRUCTION = (
    "You are a senior narrative designer reading an unfamiliar game's world "
    "bible. Your job is to produce a structured profile of the setting so "
    "downstream character / dialogue generators stay consistent with the "
    "world the writer described.\n\n"
    "Constraints:\n"
    "1. Infer only from what the lore text says. Do not add factions, "
    "eras, or terminology the writer did not write.\n"
    "2. Prefer conservative ratings. When the lore contains violence, "
    "drugs, explicit content, or extreme themes, reflect it in the rating.\n"
    "3. Pick the narrowest accurate genre label. 'cyberpunk_noir' is better "
    "than 'sci_fi'. 'frontier_western' is better than 'historical'.\n"
    "4. The anachronism_blocklist should list words that would visibly "
    "break the register — not every possible out-of-place word, just the "
    "common offenders (modern slang in period settings, archaic forms in "
    "modern settings, etc.).\n"
    "5. canonical_terms should name things the setting calls by a specific "
    "word — if the lore never names the currency, omit 'currency'."
)


_PROFILE_USER_PROMPT = (
    "Here is the world bible. Produce a WorldProfile that matches the "
    "schema.\n\n"
    "--- LORE ---\n{lore}\n--- END LORE ---\n"
)


def cache_path_for(demo_dir: Path) -> Path:
    """Canonical location for the cached profile inside a demo directory."""
    return demo_dir / ".npcforge" / "world_profile.json"


def load_cached_profile(demo_dir: Path) -> WorldProfile | None:
    """Load the cached profile if present; return ``None`` otherwise."""
    path = cache_path_for(demo_dir)
    if not path.exists():
        return None
    return WorldProfile.model_validate_json(path.read_text(encoding="utf-8"))


def save_profile(demo_dir: Path, profile: WorldProfile) -> Path:
    """Write the profile cache, creating the ``.npcforge/`` directory."""
    path = cache_path_for(demo_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(profile.model_dump_json(indent=2), encoding="utf-8")
    return path


async def infer_world_profile(
    *,
    demo_dir: Path,
    api_key: str,
    provider: str = "gemini",
    model: str | None = None,
    overwrite_cache: bool = False,
) -> WorldProfile:
    """Infer a :class:`WorldProfile` from ``<demo_dir>/lore/*.md``.

    Caches the result to ``<demo_dir>/.npcforge/world_profile.json`` unless
    one already exists and ``overwrite_cache`` is false.

    The profile is a single LLM structured-output call — one request per
    invocation. Downstream callers should prefer :func:`load_cached_profile`
    on subsequent runs.
    """
    cached = load_cached_profile(demo_dir)
    if cached is not None and not overwrite_cache:
        return cached

    lore_dir = demo_dir / "lore"
    bible = load_world_bible(lore_dir)
    sources = sorted(p.name for p in lore_dir.glob("*.md"))

    llm = LLMFactory.create(
        provider=provider,
        model_name=model or _AFTERIMAGE_DEFAULT_MODEL,
        api_key=api_key,
        system_instruction=_PROFILE_SYSTEM_INSTRUCTION,
    )
    response = await llm.agenerate_structured(
        prompt=_PROFILE_USER_PROMPT.format(lore=bible),
        schema=WorldProfile,
        temperature=0.2,
    )
    parsed = getattr(response, "parsed", None)
    if not isinstance(parsed, WorldProfile):
        parsed = WorldProfile.model_validate_json(response.text)

    parsed.inferred_from = sources
    save_profile(demo_dir, parsed)
    return parsed


def format_profile_for_prompt(profile: WorldProfile) -> str:
    """Human-readable block used inside downstream generator prompts."""
    terms = (
        "\n".join(f"  - {t.category}: {t.term}" for t in profile.canonical_terms)
        or "  (none)"
    )
    blocked = ", ".join(profile.anachronism_blocklist) or "(none)"
    return (
        f"WORLD PROFILE\n"
        f"  genre: {profile.genre}\n"
        f"  era: {profile.era}\n"
        f"  tone: {profile.tone}\n"
        f"  likely_rating: {profile.likely_rating}\n"
        f"  register_default: {profile.register_default}\n"
        f"  canonical_terms:\n{terms}\n"
        f"  anachronism_blocklist: {blocked}\n"
        f"  notes: {profile.notes or '(none)'}\n"
    )
