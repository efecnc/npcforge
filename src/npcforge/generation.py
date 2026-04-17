"""NPC generation — turn lore + a brief into character sheets.

One LLM structured call per NPC against the ``NpcSheet`` schema. The world
profile (from :mod:`npcforge.world_profile`) plus any existing cast are
injected into every prompt so new NPCs are stylistically consistent and
don't duplicate existing roles.

Writes are **strictly additive**: existing NPC entries are preserved, new
ones are appended. YAML comments above the ``npcs:`` key are preserved;
comments inside the npcs list are not (acceptable for v0.3.0 alpha).
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Iterable

import yaml
from afterimage.common import default_model_name as _AFTERIMAGE_DEFAULT_MODEL
from afterimage.providers import LLMFactory

from .schemas import NpcSheet, load_npcs
from .world_profile import WorldProfile, format_profile_for_prompt

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def _render_existing_cast(existing: list[NpcSheet]) -> str:
    if not existing:
        return "(none yet — this NPC is the first in the cast)"
    lines: list[str] = []
    for n in existing:
        sample = n.sample_lines[0] if n.sample_lines else ""
        lines.append(
            f"- id: {n.id}  name: {n.name}  role: {n.role}  "
            f"voice: {n.voice.split(chr(10))[0].strip()[:80]}"
            + (f'  sample: "{sample[:60]}"' if sample else "")
        )
    return "\n".join(lines)


_NPC_GEN_SYSTEM = (
    "You are a senior narrative designer writing NPC character sheets for a "
    "game. Each sheet must obey the provided schema exactly and be grounded "
    "in the supplied world profile and lore.\n\n"
    "Hard constraints:\n"
    "1. Stay inside the world's genre, era, tone, and rating. Do not invent "
    "factions or terminology the lore has not introduced.\n"
    "2. Do not duplicate an existing NPC's role, id, or voice. Fill faction / "
    "register / archetype gaps.\n"
    "3. Voice is the single most important field. Write 2-4 sentences that "
    "describe HOW the NPC speaks (rhythm, register, tics). Not WHAT they think.\n"
    "4. Sample lines are for tone only, not verbatim reuse. 2-4 of them.\n"
    "5. Secret must be a single concrete fact the NPC never discloses directly.\n"
    "6. Forbidden words must include the world profile's anachronism blocklist "
    "and any words that would break this specific NPC's voice.\n"
    "7. vocabulary_ceiling: match the NPC's education and role — miners and "
    "drifters are grade_5; craftspeople and merchants are grade_8 or "
    "high_school; scholars, priests, and corp suits are college or academic.\n"
    "8. allowed_intents must be a subset of the project-wide intent list. If "
    "you are unsure whether an intent fits, omit it. Aim for 4-8.\n"
    "9. id must be lower_snake_case, unique within the cast.\n"
    "10. Do not invent meta-context; do not break character; do not reference "
    "'the player' abstractly."
)


_NPC_GEN_USER_TEMPLATE = (
    "{world_profile}\n"
    "\n"
    "--- LORE ---\n{lore}\n--- END LORE ---\n"
    "\n"
    "EXISTING CAST (do not duplicate any role / id / voice):\n"
    "{existing_cast}\n"
    "\n"
    "PROJECT-WIDE INTENT IDS (allowed_intents must be a subset of these):\n"
    "{intent_ids}\n"
    "\n"
    "BRIEF FOR THIS NEW NPC:\n"
    "{brief}\n"
    "\n"
    "Produce one NpcSheet that matches the schema. Do not add fields."
)


def _brief_from_role(role: str | None, brief: str | None) -> str:
    """Merge a short role hint and a longer brief into one prompt line."""
    parts: list[str] = []
    if role:
        parts.append(f"Role: {role.strip()}.")
    if brief:
        parts.append(brief.strip())
    if not parts:
        parts.append(
            "An NPC that fits the world, fills an obvious faction or archetype "
            "gap in the existing cast, and has a distinct voice."
        )
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Id handling
# ---------------------------------------------------------------------------


def _slugify(text: str) -> str:
    cleaned = re.sub(r"[^0-9a-zA-Z]+", "_", text.strip().lower()).strip("_")
    if not cleaned:
        return "npc"
    if cleaned[0].isdigit():
        cleaned = "n" + cleaned
    return cleaned


def _ensure_unique_id(proposed: str, taken: Iterable[str]) -> str:
    """Append a numeric suffix if ``proposed`` collides with an existing id."""
    taken_set = set(taken)
    base = _slugify(proposed)
    if base not in taken_set:
        return base
    i = 2
    while f"{base}_{i}" in taken_set:
        i += 1
    return f"{base}_{i}"


# ---------------------------------------------------------------------------
# Core generator
# ---------------------------------------------------------------------------


async def _generate_one_npc(
    *,
    world_bible: str,
    profile: WorldProfile,
    existing: list[NpcSheet],
    intent_ids: list[str],
    brief: str,
    api_key: str,
    model: str | None,
    provider: str,
) -> NpcSheet | None:
    """Single structured LLM call that returns one :class:`NpcSheet`.

    Returns ``None`` on parse failure; logs a warning with the underlying
    exception so callers can trace issues.
    """
    llm = LLMFactory.create(
        provider=provider,
        model_name=model or _AFTERIMAGE_DEFAULT_MODEL,
        api_key=api_key,
        system_instruction=_NPC_GEN_SYSTEM,
    )
    prompt = _NPC_GEN_USER_TEMPLATE.format(
        world_profile=format_profile_for_prompt(profile),
        lore=world_bible,
        existing_cast=_render_existing_cast(existing),
        intent_ids=", ".join(intent_ids) or "(none declared yet)",
        brief=brief,
    )
    try:
        response = await llm.agenerate_structured(
            prompt=prompt,
            schema=NpcSheet,
            temperature=0.95,
        )
    except Exception as exc:
        logger.warning("gen_npcs single-call failed: %s", exc)
        return None
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, NpcSheet):
        return parsed
    try:
        return NpcSheet.model_validate_json(response.text)
    except Exception as exc:
        logger.warning("gen_npcs JSON parse failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# YAML I/O (additive append)
# ---------------------------------------------------------------------------


def _read_existing_yaml(path: Path) -> dict:
    if not path.exists():
        return {"npcs": []}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} must be a YAML mapping at the top level")
    loaded.setdefault("npcs", [])
    return loaded


def _serialize_new_npcs(new_npcs: list[NpcSheet]) -> list[dict]:
    """Pydantic → dict with empty lists / blank strings pruned for readability."""
    rows: list[dict] = []
    for npc in new_npcs:
        row = npc.model_dump(exclude_none=True)
        for key in list(row):
            value = row[key]
            if value in ("", [], {}):
                del row[key]
        rows.append(row)
    return rows


def append_npcs_to_yaml(
    characters_yaml: Path,
    new_npcs: list[NpcSheet],
) -> Path:
    """Append newly-generated NPCs to ``characters.yaml``.

    Reads the file (or starts from scratch if missing), extends the
    ``npcs:`` list, writes back. Comments above the ``npcs:`` key are
    preserved because we don't touch the top of the file when the file
    already exists; comments inside the list are not preserved.
    """
    existing_doc = _read_existing_yaml(characters_yaml)
    existing_npcs: list[dict] = list(existing_doc.get("npcs") or [])
    existing_doc["npcs"] = existing_npcs + _serialize_new_npcs(new_npcs)

    characters_yaml.parent.mkdir(parents=True, exist_ok=True)
    characters_yaml.write_text(
        yaml.safe_dump(
            existing_doc,
            sort_keys=False,
            allow_unicode=True,
            width=100,
        ),
        encoding="utf-8",
    )
    return characters_yaml


# ---------------------------------------------------------------------------
# Public entry point — additive NPC generation
# ---------------------------------------------------------------------------


async def gen_npcs(
    *,
    demo_dir: Path,
    profile: WorldProfile,
    world_bible: str,
    api_key: str,
    n: int = 5,
    brief: str | None = None,
    roles: list[str] | None = None,
    intent_ids: list[str] | None = None,
    provider: str = "gemini",
    model: str | None = None,
    concurrency: int = 3,
    append: bool = True,
) -> list[NpcSheet]:
    """Generate new NPCs for a demo directory and (by default) append them.

    If ``roles`` is given, one NPC is generated per role (its length wins
    over ``n``). Otherwise ``n`` unconstrained NPCs are generated with the
    same shared ``brief``. Existing NPCs are read from
    ``<demo_dir>/characters.yaml`` and fed into every prompt so the
    generator does not duplicate them.

    When ``append`` is false the NPCs are returned but not written — useful
    for callers that want to review before saving.
    """
    characters_yaml = demo_dir / "characters.yaml"
    existing = load_npcs(characters_yaml) if characters_yaml.exists() else []
    taken_ids = {npc.id for npc in existing}

    roles_list = [r.strip() for r in (roles or []) if r.strip()]
    # Each entry in `assignments` is one brief passed to one LLM call.
    if roles_list:
        assignments = [_brief_from_role(r, brief) for r in roles_list]
    else:
        assignments = [_brief_from_role(None, brief) for _ in range(max(n, 1))]

    intents = intent_ids or []
    semaphore = asyncio.Semaphore(max(concurrency, 1))

    async def _bounded(assignment: str) -> NpcSheet | None:
        async with semaphore:
            return await _generate_one_npc(
                world_bible=world_bible,
                profile=profile,
                existing=existing,
                intent_ids=intents,
                brief=assignment,
                api_key=api_key,
                model=model,
                provider=provider,
            )

    generated = await asyncio.gather(*(_bounded(a) for a in assignments))

    out: list[NpcSheet] = []
    for npc in generated:
        if npc is None:
            continue
        npc.id = _ensure_unique_id(npc.id or _slugify(npc.name), taken_ids)
        taken_ids.add(npc.id)
        out.append(npc)

    if append and out:
        append_npcs_to_yaml(characters_yaml, out)
    return out
