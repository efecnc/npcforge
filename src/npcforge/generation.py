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
from pydantic import BaseModel, Field
from afterimage.common import default_model_name as _AFTERIMAGE_DEFAULT_MODEL
from afterimage.providers import LLMFactory

from .schemas import (
    BarksConfig,
    BarkTrigger,
    NpcBarkConfig,
    NpcSheet,
    NpcStub,
    PlayerIntent,
    _is_stub_entry,
    load_barks_config,
    load_intents,
    load_npcs,
    load_npcs_with_stubs,
)
from .prompts import (
    build_repeat_greeting_prompt,
    build_time_of_day_greeting_prompt,
)
from .state import (
    ProjectVariable,
    VariableType,
    format_variables_for_prompt,
)
from .project_config import load_project_config, npc_generation_prompt_suffix
from .narrative_scope import (
    LayersConfig,
    filter_npcs_by_scope_tags,
    format_layers_catalog_block,
    layers_yaml_path,
    load_layers_config,
)
from .world_profile import WorldProfile, format_profile_for_prompt
from .yarn import render_greetings_node, render_repeat_greeting_node

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
    "'the player' abstractly.\n"
    "11. Set scope_tags to 1-4 lower_snake_case ids that locate this NPC in the "
    "world (district, building, mission slice, act). When a WORLD LAYERS "
    "block appears in the prompt, prefer ids from that list; otherwise derive "
    "consistent tags from the brief and lore. Optional narrative_scope_note "
    "may tighten how local their knowledge sounds."
)


_NPC_GEN_USER_TEMPLATE = (
    "{world_profile}\n"
    "\n"
    "{layers_block}\n"
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


class _NpcSheetLite(BaseModel):
    """Flat subset of :class:`NpcSheet` suitable for LLM structured output.

    The full :class:`NpcSheet` carries several v0.7+ extensions
    (``trajectory``, ``TriggerSpec``, ``RelationshipTrajectory.event_deltas``)
    that embed ``dict[str, X]`` types — which become ``additionalProperties``
    in JSON Schema and are refused by Gemini's structured-output API. This
    lite schema keeps only the fields ``gen_npcs`` needs to propose a fresh
    NPC; advanced fields are left to be hand-authored or added by a later
    richer generator.
    """

    id: str
    name: str
    role: str
    voice: str
    background: str = ""
    motivations: list[str] = []
    secret: str = ""
    speech_quirks: list[str] = []
    sample_lines: list[str] = []
    forbidden_words: list[str] = []
    vocabulary_ceiling: str | None = None
    accent_markers: list[str] = []
    allowed_intents: list[str] = []
    scope_tags: list[str] = Field(default_factory=list)
    narrative_scope_note: str = ""


def _lite_to_full(lite: _NpcSheetLite) -> NpcSheet:
    """Promote the lite generation output into a real :class:`NpcSheet`."""
    data = lite.model_dump(exclude_none=True)
    # vocabulary_ceiling is typed narrowly on NpcSheet; reject out-of-enum values
    # by dropping them rather than erroring the whole NPC.
    valid_ceilings = {"grade_3", "grade_5", "grade_8", "high_school", "college", "academic"}
    if data.get("vocabulary_ceiling") not in valid_ceilings:
        data.pop("vocabulary_ceiling", None)
    return NpcSheet(**data)


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
    layers_block: str = "",
    narrative_prompt_suffix: str,
) -> NpcSheet | None:
    """Single structured LLM call that returns one :class:`NpcSheet`.

    Uses :class:`_NpcSheetLite` as the generation schema to side-step
    Gemini's ``additionalProperties`` restriction on the full NpcSheet's
    nested dict fields.
    """
    system_instruction = f"{_NPC_GEN_SYSTEM}\n\n{narrative_prompt_suffix}"
    llm = LLMFactory.create(
        provider=provider,
        model_name=model or _AFTERIMAGE_DEFAULT_MODEL,
        api_key=api_key,
        system_instruction=system_instruction,
    )
    lb = layers_block.strip() or (
        "(No layers.yaml — still set scope_tags from the brief's implied place / act.)"
    )
    prompt = _NPC_GEN_USER_TEMPLATE.format(
        world_profile=format_profile_for_prompt(profile),
        layers_block=lb,
        lore=world_bible,
        existing_cast=_render_existing_cast(existing),
        intent_ids=", ".join(intent_ids) or "(none declared yet)",
        brief=brief,
    )
    try:
        response = await llm.agenerate_structured(
            prompt=prompt,
            schema=_NpcSheetLite,
            temperature=0.95,
        )
    except Exception as exc:
        logger.warning("gen_npcs single-call failed: %s", exc)
        return None
    parsed = getattr(response, "parsed", None)
    lite: _NpcSheetLite | None = None
    if isinstance(parsed, _NpcSheetLite):
        lite = parsed
    else:
        try:
            lite = _NpcSheetLite.model_validate_json(response.text)
        except Exception as exc:
            logger.warning("gen_npcs JSON parse failed: %s", exc)
            return None
    try:
        return _lite_to_full(lite)
    except Exception as exc:
        logger.warning("gen_npcs lite-to-full promotion failed: %s", exc)
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
    narrative_preset: str | None = None,
    topology: str | None = None,
    depth: str | None = None,
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
    layers_cfg = load_layers_config(layers_yaml_path(demo_dir))
    layers_block = format_layers_catalog_block(layers_cfg)
    proj = load_project_config(
        demo_dir,
        narrative_preset_override=narrative_preset,
        topology_override=topology,
        depth_override=depth,
    )
    prompt_suffix = npc_generation_prompt_suffix(proj)
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
                layers_block=layers_block,
                narrative_prompt_suffix=prompt_suffix,
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


# ---------------------------------------------------------------------------
# Intent generation
# ---------------------------------------------------------------------------


_INTENT_SYSTEM = (
    "You are a senior narrative designer designing the PLAYER's conversational "
    "palette for a game. Each 'intent' describes WHAT the player can try to do "
    "in a single turn (barter, threaten, flirt, ask about X) — not who the "
    "player is.\n\n"
    "Constraints:\n"
    "1. Intent ids are lower_snake_case, short, verb-led "
    "('ask_about_locket', 'bribe_for_info', 'farewell').\n"
    "2. Descriptions are 1-3 sentences describing the player's posture for that "
    "turn. No scene-setting, no world lore dumps.\n"
    "3. opening_intent is one short sentence naming what the player does first.\n"
    "4. Do not duplicate an existing intent's id or scope. Fill gaps.\n"
    "5. Intents should work across different NPCs in this world — they belong "
    "to the *player*, not any one NPC."
)


_INTENT_USER_TEMPLATE = (
    "{world_profile}\n\n"
    "EXISTING INTENT IDS (do not duplicate): {existing_ids}\n\n"
    "BRIEF: {brief}\n\n"
    "Produce ONE PlayerIntent matching the schema."
)


async def _generate_one_intent(
    *,
    profile: WorldProfile,
    existing_ids: list[str],
    brief: str,
    api_key: str,
    model: str | None,
    provider: str,
) -> PlayerIntent | None:
    llm = LLMFactory.create(
        provider=provider,
        model_name=model or _AFTERIMAGE_DEFAULT_MODEL,
        api_key=api_key,
        system_instruction=_INTENT_SYSTEM,
    )
    prompt = _INTENT_USER_TEMPLATE.format(
        world_profile=format_profile_for_prompt(profile),
        existing_ids=", ".join(existing_ids) or "(none yet)",
        brief=brief,
    )
    try:
        response = await llm.agenerate_structured(
            prompt=prompt,
            schema=PlayerIntent,
            temperature=0.9,
        )
    except Exception as exc:
        logger.warning("gen_intents single-call failed: %s", exc)
        return None
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, PlayerIntent):
        return parsed
    try:
        return PlayerIntent.model_validate_json(response.text)
    except Exception as exc:
        logger.warning("gen_intents JSON parse failed: %s", exc)
        return None


def _serialize_intents(intents: list[PlayerIntent]) -> list[dict]:
    rows: list[dict] = []
    for it in intents:
        row = it.model_dump(exclude_none=True)
        for key in list(row):
            if row[key] in ("", [], {}):
                del row[key]
        rows.append(row)
    return rows


def append_intents_to_yaml(
    intents_yaml: Path,
    new_intents: list[PlayerIntent],
) -> Path:
    """Append newly generated intents to ``player_intents.yaml`` (additive)."""
    if intents_yaml.exists():
        data = yaml.safe_load(intents_yaml.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError(f"{intents_yaml} must be a YAML mapping")
    else:
        data = {}
    existing = list(data.get("intents") or [])
    data["intents"] = existing + _serialize_intents(new_intents)

    intents_yaml.parent.mkdir(parents=True, exist_ok=True)
    intents_yaml.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8",
    )
    return intents_yaml


async def gen_intents(
    *,
    demo_dir: Path,
    profile: WorldProfile,
    api_key: str,
    n: int = 8,
    brief: str | None = None,
    provider: str = "gemini",
    model: str | None = None,
    concurrency: int = 3,
    append: bool = True,
) -> list[PlayerIntent]:
    """Generate additional player intents consistent with the world.

    Existing intents are read, fed into every prompt as "do not duplicate,"
    and preserved on disk. Duplicate ids surfaced by the LLM are silently
    dropped from the new batch.
    """
    intents_yaml = demo_dir / "player_intents.yaml"
    existing: list[PlayerIntent] = (
        load_intents(intents_yaml) if intents_yaml.exists() else []
    )
    taken = {i.id for i in existing}

    default_brief = (
        "Fill plausible gaps in the player's conversational palette for this "
        "world. Cover at least one 'soft' intent (flirt / compliment / confess) "
        "and one 'hard' intent (threaten / challenge / refuse) when the "
        "existing set is thin on either side."
    )
    shared_brief = brief or default_brief

    semaphore = asyncio.Semaphore(max(concurrency, 1))

    async def _bounded() -> PlayerIntent | None:
        async with semaphore:
            return await _generate_one_intent(
                profile=profile,
                existing_ids=list(taken),
                brief=shared_brief,
                api_key=api_key,
                model=model,
                provider=provider,
            )

    raw = await asyncio.gather(*(_bounded() for _ in range(max(n, 1))))

    out: list[PlayerIntent] = []
    for intent in raw:
        if intent is None:
            continue
        if intent.id in taken:
            continue  # LLM duplicated — drop
        taken.add(intent.id)
        out.append(intent)

    if append and out:
        append_intents_to_yaml(intents_yaml, out)
    return out


# ---------------------------------------------------------------------------
# Bark trigger generation
# ---------------------------------------------------------------------------


_BARK_TRIGGER_SYSTEM = (
    "You are a senior narrative designer proposing BARK TRIGGERS for an NPC. "
    "A bark trigger describes a moment in the game when the NPC would emit a "
    "1-2 line reactive utterance — combat, ambient, witnessing an event, "
    "greeting, refusing a sale.\n\n"
    "Constraints:\n"
    "1. id is lower_snake_case, short, verb-led: 'combat_start', "
    "'greet_patron', 'spots_lawman', 'refuses_drink', 'reacts_to_hum'.\n"
    "2. description is a SITUATIONAL CUE, not a directive. Good: 'A corp "
    "suit walks into the Mox.' Bad: 'React to seeing a corp.'\n"
    "3. n (variant count) is 6-10 for common triggers, lower for rare ones.\n"
    "4. Do not duplicate an existing trigger id for this NPC.\n"
    "5. Each trigger should fit THIS specific NPC's role and voice — "
    "combat barks for fighters, refusal barks for merchants, etc."
)


_BARK_TRIGGER_USER_TEMPLATE = (
    "{world_profile}\n\n"
    "--- NPC SHEET ---\n{npc_sheet}\n--- END NPC SHEET ---\n\n"
    "EXISTING TRIGGER IDS FOR THIS NPC (do not duplicate): {existing_ids}\n\n"
    "BRIEF: {brief}\n\n"
    "Produce ONE BarkTrigger matching the schema."
)


async def _generate_one_bark_trigger(
    *,
    npc: NpcSheet,
    profile: WorldProfile,
    existing_ids: list[str],
    brief: str,
    api_key: str,
    model: str | None,
    provider: str,
    layers: LayersConfig | None = None,
) -> BarkTrigger | None:
    from .prompts import render_character_sheet

    llm = LLMFactory.create(
        provider=provider,
        model_name=model or _AFTERIMAGE_DEFAULT_MODEL,
        api_key=api_key,
        system_instruction=_BARK_TRIGGER_SYSTEM,
    )
    prompt = _BARK_TRIGGER_USER_TEMPLATE.format(
        world_profile=format_profile_for_prompt(profile),
        npc_sheet=render_character_sheet(npc, layers=layers),
        existing_ids=", ".join(existing_ids) or "(none yet)",
        brief=brief,
    )
    try:
        response = await llm.agenerate_structured(
            prompt=prompt,
            schema=BarkTrigger,
            temperature=0.95,
        )
    except Exception as exc:
        logger.warning(
            "gen_barks trigger call failed for %s: %s", npc.id, exc
        )
        return None
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, BarkTrigger):
        return parsed
    try:
        return BarkTrigger.model_validate_json(response.text)
    except Exception as exc:
        logger.warning(
            "gen_barks trigger JSON parse failed for %s: %s", npc.id, exc
        )
        return None


def append_bark_triggers_to_yaml(
    barks_yaml: Path,
    npc_id: str,
    new_triggers: list[BarkTrigger],
) -> Path:
    """Append triggers for ``npc_id`` to ``barks.yaml``, additive + nested."""
    if barks_yaml.exists():
        data = yaml.safe_load(barks_yaml.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError(f"{barks_yaml} must be a YAML mapping")
    else:
        data = {}
    raw = list(data.get("barks") or [])
    serialised_new = [t.model_dump(exclude_none=True) for t in new_triggers]

    # Find existing npc entry or append a new one.
    updated = False
    for entry in raw:
        if isinstance(entry, dict) and entry.get("npc") == npc_id:
            entry.setdefault("triggers", []).extend(serialised_new)
            updated = True
            break
    if not updated:
        raw.append({"npc": npc_id, "triggers": serialised_new})

    data["barks"] = raw
    barks_yaml.parent.mkdir(parents=True, exist_ok=True)
    barks_yaml.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8",
    )
    return barks_yaml


async def gen_barks(
    *,
    demo_dir: Path,
    profile: WorldProfile,
    api_key: str,
    for_npcs: list[str] | None = None,
    only_scope_tags: list[str] | None = None,
    include_unscoped: bool = False,
    n_per_npc: int = 3,
    brief: str | None = None,
    provider: str = "gemini",
    model: str | None = None,
    concurrency: int = 3,
    append: bool = True,
) -> dict[str, list[BarkTrigger]]:
    """Generate bark triggers (not lines) for one or more NPCs, additively.

    Returns a map ``npc_id -> list[BarkTrigger]``. Actual bark *lines* are
    still produced by :func:`npcforge.pipeline.generate_barks_for_npc_trigger`
    during ``build_pipeline --mode barks``. This tool only proposes the
    trigger contexts that feed that pipeline.
    """
    characters_yaml = demo_dir / "characters.yaml"
    all_npcs = load_npcs(characters_yaml) if characters_yaml.exists() else []
    if not all_npcs:
        return {}

    if for_npcs:
        allow = {x.strip() for x in for_npcs}
        target_npcs = [n for n in all_npcs if n.id in allow]
    else:
        target_npcs = all_npcs

    st = [t.strip() for t in (only_scope_tags or []) if t and str(t).strip()]
    if st:
        target_npcs = filter_npcs_by_scope_tags(
            target_npcs, st, include_unscoped=include_unscoped
        )
        if not target_npcs:
            return {}

    layers_cfg = load_layers_config(layers_yaml_path(demo_dir))

    barks_yaml = demo_dir / "barks.yaml"
    existing_cfg = load_barks_config(barks_yaml)
    existing_triggers_by_npc: dict[str, list[str]] = {}
    for entry in existing_cfg.barks:
        existing_triggers_by_npc[entry.npc] = [t.id for t in entry.triggers]

    default_brief = (
        "Propose trigger moments that would fit this specific NPC's role. "
        "Cover at least one greeting/social, one combat/conflict, and one "
        "ambient when the NPC's role supports those. Use situational cues "
        "(not directives) for descriptions."
    )
    shared_brief = brief or default_brief

    semaphore = asyncio.Semaphore(max(concurrency, 1))
    out: dict[str, list[BarkTrigger]] = {}

    for npc in target_npcs:
        taken_ids = set(existing_triggers_by_npc.get(npc.id, []))

        async def _bounded(taken: set[str], npc_ref: NpcSheet) -> BarkTrigger | None:
            async with semaphore:
                return await _generate_one_bark_trigger(
                    npc=npc_ref,
                    profile=profile,
                    existing_ids=list(taken),
                    brief=shared_brief,
                    api_key=api_key,
                    model=model,
                    provider=provider,
                    layers=layers_cfg,
                )

        raw = await asyncio.gather(
            *(_bounded(taken_ids, npc) for _ in range(max(n_per_npc, 1)))
        )
        produced: list[BarkTrigger] = []
        for trigger in raw:
            if trigger is None or trigger.id in taken_ids:
                continue
            taken_ids.add(trigger.id)
            produced.append(trigger)

        if produced:
            out[npc.id] = produced
            if append:
                append_bark_triggers_to_yaml(barks_yaml, npc.id, produced)

    return out


# ---------------------------------------------------------------------------
# Stub resolution
# ---------------------------------------------------------------------------


async def _resolve_one_stub(
    *,
    stub: NpcStub,
    profile: WorldProfile,
    world_bible: str,
    existing: list[NpcSheet],
    intent_ids: list[str],
    api_key: str,
    model: str | None,
    provider: str,
    layers_block: str = "",
    narrative_prompt_suffix: str,
) -> NpcSheet | None:
    """Expand a single :class:`NpcStub` into a full :class:`NpcSheet`."""
    hint_parts: list[str] = [f"id: {stub.id}"]
    if stub.name:
        hint_parts.append(f"name: {stub.name}")
    if stub.role or stub.role_hint:
        hint_parts.append(f"role: {(stub.role or stub.role_hint).strip()}")
    if stub.voice_hint:
        hint_parts.append(f"voice_hint: {stub.voice_hint.strip()}")
    hint_brief = (
        "Expand the following stub into a full NpcSheet. Keep the id exactly "
        "as given. Honour every hint the writer provided; fill in the rest "
        "consistently with the world and the existing cast.\n\n"
        + "\n".join(hint_parts)
    )

    sheet = await _generate_one_npc(
        world_bible=world_bible,
        profile=profile,
        existing=existing,
        intent_ids=intent_ids,
        brief=hint_brief,
        api_key=api_key,
        model=model,
        provider=provider,
        layers_block=layers_block,
        narrative_prompt_suffix=narrative_prompt_suffix,
    )
    if sheet is None:
        return None
    # Force the id to match the stub — generator may have picked a different one.
    sheet.id = stub.id
    return sheet


def _rewrite_characters_yaml_replacing_stubs(
    characters_yaml: Path,
    resolved: dict[str, NpcSheet],
) -> Path:
    """Rewrite ``characters.yaml`` inlining resolved stubs.

    Preserves top-level keys (e.g. ``world:``, ``tone:``) and the ordering of
    npcs. Stubs that did not resolve are left in place.
    """
    data = yaml.safe_load(characters_yaml.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{characters_yaml} must be a YAML mapping")
    raw_npcs = list(data.get("npcs") or [])

    new_list: list[dict] = []
    for item in raw_npcs:
        if not isinstance(item, dict):
            new_list.append(item)
            continue
        stub_id = item.get("id")
        if _is_stub_entry(item) and stub_id in resolved:
            sheet_dict = resolved[stub_id].model_dump(exclude_none=True)
            for key in list(sheet_dict):
                if sheet_dict[key] in ("", [], {}):
                    del sheet_dict[key]
            new_list.append(sheet_dict)
        else:
            new_list.append(item)

    data["npcs"] = new_list
    characters_yaml.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8",
    )
    return characters_yaml


# ---------------------------------------------------------------------------
# State-aware generation: time-of-day greeting variants (v0.6.0)
# ---------------------------------------------------------------------------


class _GreetingLine(BaseModel):
    """Structured-output target for one time-of-day greeting."""

    text: str = Field(..., description="One-sentence in-character greeting.")
    emotion: str = Field(
        default="neutral",
        description="Short emotion tag: neutral / warm / tired / wary / amused.",
    )


_GREETING_USER_TEMPLATE = (
    "{world_profile}\n\n"
    "{variables}\n\n"
    "TIME BUCKET FOR THIS CALL: {value}\n\n"
    "Produce ONE greeting matching the schema."
)


async def _generate_one_greeting(
    *,
    npc: NpcSheet,
    variable: ProjectVariable,
    value: str,
    profile_block: str,
    variables_block: str,
    api_key: str,
    model: str | None,
    provider: str,
    temperature: float = 0.95,
) -> _GreetingLine | None:
    llm = LLMFactory.create(
        provider=provider,
        model_name=model or _AFTERIMAGE_DEFAULT_MODEL,
        api_key=api_key,
        system_instruction=build_time_of_day_greeting_prompt(npc, value),
    )
    prompt = _GREETING_USER_TEMPLATE.format(
        world_profile=profile_block,
        variables=variables_block,
        value=value,
    )
    try:
        response = await llm.agenerate_structured(
            prompt=prompt,
            schema=_GreetingLine,
            temperature=temperature,
        )
    except Exception as exc:
        logger.warning(
            "gen_greetings call failed for %s/%s: %s", npc.id, value, exc
        )
        return None
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, _GreetingLine):
        return parsed
    try:
        return _GreetingLine.model_validate_json(response.text)
    except Exception as exc:
        logger.warning(
            "gen_greetings parse failed for %s/%s: %s", npc.id, value, exc
        )
        return None


async def gen_time_of_day_greetings(
    *,
    demo_dir: Path,
    profile,  # WorldProfile — untyped to avoid a circular import
    variable: ProjectVariable,
    variables: list[ProjectVariable],
    npc_ids: list[str] | None,
    api_key: str,
    provider: str = "gemini",
    model: str | None = None,
    concurrency: int = 4,
    write: bool = True,
) -> dict[str, list[tuple[str, str]]]:
    """Generate one greeting per (NPC, variable-value).

    Returns a map ``{npc_id: [(value, text), ...]}`` in the order declared
    by ``variable.values``. When ``write`` is true, a per-NPC greeting node
    is emitted via :func:`npcforge.yarn.render_greetings_node` into
    ``<demo_dir>/out/``.

    ``variable`` must be an enum-typed variable (validated at the call site
    via its :class:`~npcforge.state.VariableType`).
    """
    if variable.type != VariableType.ENUM:
        raise ValueError(
            "gen_time_of_day_greetings requires an enum-typed variable "
            f"(got {variable.type})"
        )

    characters_yaml = demo_dir / "characters.yaml"
    all_npcs = load_npcs(characters_yaml) if characters_yaml.exists() else []
    if npc_ids:
        allow = {i.strip() for i in npc_ids if i.strip()}
        target_npcs = [n for n in all_npcs if n.id in allow]
    else:
        target_npcs = all_npcs
    if not target_npcs:
        return {}

    profile_block = format_profile_for_prompt(profile)
    variables_block = format_variables_for_prompt(variables)

    semaphore = asyncio.Semaphore(max(concurrency, 1))

    async def _one(npc: NpcSheet, value: str) -> _GreetingLine | None:
        async with semaphore:
            return await _generate_one_greeting(
                npc=npc,
                variable=variable,
                value=value,
                profile_block=profile_block,
                variables_block=variables_block,
                api_key=api_key,
                model=model,
                provider=provider,
            )

    out: dict[str, list[tuple[str, str]]] = {}
    out_dir = demo_dir / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    for npc in target_npcs:
        tasks = [_one(npc, value) for value in variable.values]
        results = await asyncio.gather(*tasks)
        variants: list[tuple[str, str]] = []
        for value, result in zip(variable.values, results):
            if result is None or not result.text.strip():
                continue
            variants.append((value, result.text.strip()))
        if not variants:
            continue
        out[npc.id] = variants
        if write:
            node_path = out_dir / f"{npc.id}_greet_{variable.id}.yarn"
            node_path.write_text(
                render_greetings_node(npc, variable.id, variants),
                encoding="utf-8",
            )

    return out


async def _generate_one_repeat_greeting(
    *,
    npc: NpcSheet,
    visit_index: int,
    n_total: int,
    is_else: bool,
    profile_block: str,
    api_key: str,
    model: str | None,
    provider: str,
) -> _GreetingLine | None:
    """Single LLM call for one visit-gated greeting variant."""
    llm = LLMFactory.create(
        provider=provider,
        model_name=model or _AFTERIMAGE_DEFAULT_MODEL,
        api_key=api_key,
        system_instruction=build_repeat_greeting_prompt(
            npc, visit_index, n_total, is_else
        ),
    )
    try:
        response = await llm.agenerate_structured(
            prompt=(
                f"{profile_block}\n\nReturn JSON matching the schema."
            ),
            schema=_GreetingLine,
            temperature=0.95,
        )
    except Exception as exc:
        logger.warning(
            "gen_repeat_greeting call failed for %s visit %d: %s",
            npc.id,
            visit_index,
            exc,
        )
        return None
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, _GreetingLine):
        return parsed
    try:
        return _GreetingLine.model_validate_json(response.text)
    except Exception as exc:
        logger.warning(
            "gen_repeat_greeting parse failed for %s visit %d: %s",
            npc.id,
            visit_index,
            exc,
        )
        return None


async def gen_repeat_greeting_node(
    *,
    demo_dir: Path,
    profile,  # WorldProfile — untyped to avoid circular import
    api_key: str,
    n: int = 3,
    npc_ids: list[str] | None = None,
    provider: str = "gemini",
    model: str | None = None,
    concurrency: int = 4,
    write: bool = True,
) -> dict[str, list[str]]:
    """Generate ``n`` visit-gated greeting variants for one or more NPCs.

    Convention: index 0 is the first visit (stranger), index 1 is the
    second visit, ..., index ``n-1`` is the ``else`` fallback played on
    every subsequent visit. Output is a map ``{npc_id: [variant, ...]}``
    in order. When ``write`` is true, a per-NPC Yarn node is emitted via
    :func:`npcforge.yarn.render_repeat_greeting_node` into
    ``<demo_dir>/out/<npc_id>_repeat_greet.yarn``.
    """
    if n < 2:
        raise ValueError("n must be >= 2 (stranger + 1 repeat)")

    characters_yaml = demo_dir / "characters.yaml"
    all_npcs = load_npcs(characters_yaml) if characters_yaml.exists() else []
    if npc_ids:
        allow = {i.strip() for i in npc_ids if i.strip()}
        target_npcs = [x for x in all_npcs if x.id in allow]
    else:
        target_npcs = all_npcs
    if not target_npcs:
        return {}

    profile_block = format_profile_for_prompt(profile)
    semaphore = asyncio.Semaphore(max(concurrency, 1))

    async def _one(npc: NpcSheet, idx: int, is_else: bool) -> _GreetingLine | None:
        async with semaphore:
            return await _generate_one_repeat_greeting(
                npc=npc,
                visit_index=idx,
                n_total=n,
                is_else=is_else,
                profile_block=profile_block,
                api_key=api_key,
                model=model,
                provider=provider,
            )

    out: dict[str, list[str]] = {}
    out_dir = demo_dir / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    for npc in target_npcs:
        tasks = []
        for idx in range(n):
            is_else = idx == n - 1
            tasks.append(_one(npc, idx, is_else))
        results = await asyncio.gather(*tasks)
        texts: list[str] = []
        for r in results:
            if r is None or not r.text.strip():
                continue
            texts.append(r.text.strip())
        if len(texts) < 2:
            # Skip NPC if we couldn't even produce stranger + 1 fallback.
            continue
        out[npc.id] = texts
        if write:
            node_path = out_dir / f"{npc.id}_repeat_greet.yarn"
            node_path.write_text(
                render_repeat_greeting_node(npc, texts), encoding="utf-8"
            )

    return out


async def resolve_stubs(
    *,
    demo_dir: Path,
    profile: WorldProfile,
    world_bible: str,
    api_key: str,
    only_ids: list[str] | None = None,
    intent_ids: list[str] | None = None,
    provider: str = "gemini",
    model: str | None = None,
    concurrency: int = 3,
    write: bool = True,
    narrative_preset: str | None = None,
    topology: str | None = None,
    depth: str | None = None,
) -> tuple[list[NpcSheet], list[str]]:
    """Replace every ``_generate: true`` entry in characters.yaml with a full sheet.

    Returns ``(resolved_sheets, unresolved_ids)`` — the second list holds
    stub ids the LLM failed to expand so callers can retry.

    Safe by default: only touches entries with ``_generate: true``. Existing
    non-stub NPCs are preserved.
    """
    characters_yaml = demo_dir / "characters.yaml"
    existing, stubs = load_npcs_with_stubs(characters_yaml)
    if only_ids:
        allow = set(only_ids)
        stubs = [s for s in stubs if s.id in allow]
    if not stubs:
        return [], []

    intents = intent_ids or []
    layers_cfg = load_layers_config(layers_yaml_path(demo_dir))
    layers_block = format_layers_catalog_block(layers_cfg)
    proj = load_project_config(
        demo_dir,
        narrative_preset_override=narrative_preset,
        topology_override=topology,
        depth_override=depth,
    )
    prompt_suffix = npc_generation_prompt_suffix(proj)
    semaphore = asyncio.Semaphore(max(concurrency, 1))

    async def _bounded(stub: NpcStub) -> NpcSheet | None:
        async with semaphore:
            return await _resolve_one_stub(
                stub=stub,
                profile=profile,
                world_bible=world_bible,
                existing=existing,
                intent_ids=intents,
                api_key=api_key,
                model=model,
                provider=provider,
                layers_block=layers_block,
                narrative_prompt_suffix=prompt_suffix,
            )

    results = await asyncio.gather(*(_bounded(s) for s in stubs))

    resolved_map: dict[str, NpcSheet] = {}
    unresolved: list[str] = []
    for stub, sheet in zip(stubs, results):
        if sheet is None:
            unresolved.append(stub.id)
        else:
            resolved_map[stub.id] = sheet

    if write and resolved_map:
        _rewrite_characters_yaml_replacing_stubs(characters_yaml, resolved_map)

    return list(resolved_map.values()), unresolved
