"""Input schemas and YAML/markdown loaders for npcforge.

v0.2.0 adds player *intents* (finer-grained than archetypes), voice-ceiling
fields on NpcSheet, and bark generation config.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


VocabularyCeiling = Literal[
    "grade_3",
    "grade_5",
    "grade_8",
    "high_school",
    "college",
    "academic",
]


class Faction(BaseModel):
    """A social group NPCs belong to (v0.9.0 — social graph).

    Factions are loaded from ``factions.yaml`` at the project root. They
    let the respondent prompt know how an NPC's tone should shift when
    allies, rivals, or neutrals are in the room, and they give the
    memory layer a way to attribute player actions to a group rather
    than just an individual ("player helped the Guild" vs "player helped
    Kess specifically").

    Keep ``allies`` and ``rivals`` as **lists of faction ids** — the
    loader validates they exist. Symbols and values are free-text and
    get injected into the respondent prompt as character-grounding.
    """

    id: str = Field(..., description="Lower_snake_case faction id used in references.")
    name: str = Field(..., description="Display name, e.g. 'The Miners' Guild'.")
    description: str = Field(
        default="",
        description=(
            "One or two sentences capturing the faction's role in the world. "
            "Injected into respondent prompts when a member references it."
        ),
    )
    values: list[str] = Field(
        default_factory=list,
        description=(
            "What the faction cares about: 'coin', 'silence', 'pre-Forgetting "
            "relics', 'the old songs'. Each entry is a short phrase."
        ),
    )
    symbols: list[str] = Field(
        default_factory=list,
        description=(
            "Visible markers that identify members: 'black-gloved left hand', "
            "'brass guild pin', 'humming the third verse'."
        ),
    )
    allies: list[str] = Field(
        default_factory=list,
        description="Faction ids this faction considers aligned. Must resolve.",
    )
    rivals: list[str] = Field(
        default_factory=list,
        description="Faction ids this faction considers hostile. Must resolve.",
    )


class FactionsConfig(BaseModel):
    """Top-level ``factions.yaml`` schema."""

    factions: list[Faction] = Field(default_factory=list)


MemorySalience = Literal["trivial", "notable", "pivotal"]


class MemoryEvent(BaseModel):
    """One recorded player-NPC interaction (v0.9.0 — memory layer).

    Memory events persist across sessions so NPCs can reference what the
    player did before. Events are scoped to a single NPC (``npc_id``) but
    may also be tagged with a ``faction_id`` — enabling "the player
    insulted a Guildsman" to register with every Guild member, not just
    the one they insulted.

    ``salience`` drives decay: trivial events get pruned after a small
    number of subsequent encounters; notable events last longer; pivotal
    events are permanent (betrayals, gifts, secrets shared, deaths
    witnessed). The memory summariser respects this.

    ``turn`` is a monotonic counter the runtime bumps whenever gameplay
    reaches a narrative beat (not a frame counter). It's opaque to npcforge
    — we only use it to sort-by-recency and compute "how many beats ago."
    """

    turn: int = Field(
        ...,
        description=(
            "Monotonic event counter set by the runtime. Higher = more recent. "
            "Opaque to npcforge; we only sort and subtract."
        ),
    )
    npc_id: str = Field(
        ...,
        description="The NPC this event is about (memory is per-NPC).",
    )
    event_type: str = Field(
        ...,
        description=(
            "Short tag categorising the event: 'player_lied', 'gift_given', "
            "'threat', 'secret_shared', 'faction_helped', 'faction_harmed'. "
            "Free-form — the summariser includes the tag verbatim."
        ),
    )
    summary: str = Field(
        ...,
        description=(
            "One short sentence describing what happened, phrased from the "
            "NPC's point of view. 'The player offered coin for my silence.' "
            "Becomes verbatim prompt fuel."
        ),
    )
    salience: MemorySalience = Field(
        default="notable",
        description=(
            "trivial = prune after ~3 subsequent turns. notable = ~10 turns. "
            "pivotal = permanent. Drives decay in the memory summariser."
        ),
    )
    faction_id: str = Field(
        default="",
        description=(
            "Optional faction tag. If present, this event is visible to every "
            "member of the faction when they summarise their memory of the "
            "player — enables 'the Guild remembers' dynamics."
        ),
    )


class Relationship(BaseModel):
    """One NPC's stance toward another NPC in the cast (v0.8.0).

    Injected into respondent prompts so generated dialogue can reference
    other cast members with a stable opinion and reason, instead of
    inventing relationships on the fly.
    """

    npc_id: str = Field(
        ..., description="Target NPC's id (must match a character in the same cast)."
    )
    opinion: str = Field(
        ...,
        description=(
            "Free-text stance: 'trusts completely', 'wary ally', 'old rival', "
            "'protective of', 'nominally polite, privately contemptuous', etc."
        ),
    )
    reason: str = Field(
        default="",
        description=(
            "Short sentence-length explanation the NPC could plausibly think "
            "but would not volunteer. Grounds the opinion in something "
            "concrete from the world."
        ),
    )


class TriggerSpec(BaseModel):
    """Structured condition that gates an arc stage (v0.10.0).

    Unlike the free-text ``trigger`` field on :class:`StateEvolution`, a
    TriggerSpec is evaluated by :mod:`npcforge.arcs` against the runtime
    memory store + faction-standing state. The fields are ANDed: every
    specified constraint must hold for the stage to activate. An empty
    TriggerSpec (no fields set) always activates — useful for a stage
    that represents the NPC's baseline voice.

    This structured form lets the generator *and* the runtime agree on
    which stages are active without either side having to interpret
    prose. The free-text escape hatch stays on StateEvolution for cases
    that need it (e.g. "active after the player has witnessed Gereth
    weep in private" — too narrative to encode structurally).
    """

    min_pivotal_events: int = Field(
        default=0,
        ge=0,
        description=(
            "Minimum number of pivotal memory events involving this NPC "
            "(or tagged with their faction) that must exist. 0 disables "
            "this check."
        ),
    )
    min_total_events: int = Field(
        default=0,
        ge=0,
        description=(
            "Minimum number of memory events of any salience. Useful for "
            "soft 'the player has hung around long enough' stages."
        ),
    )
    required_event_types: list[str] = Field(
        default_factory=list,
        description=(
            "Event-type tags that must each appear in this NPC's memory "
            "at least once: ['gift_given', 'secret_shared']. Folded with "
            "faction-shared events the same way summarize_for_npc is."
        ),
    )
    min_standing: dict[str, float] = Field(
        default_factory=dict,
        description=(
            "Per-faction player-standing floors: {'miners': 20, "
            "'lantern_regulars': -10}. Evaluated against the runtime "
            "faction-standing store."
        ),
    )
    max_standing: dict[str, float] = Field(
        default_factory=dict,
        description=(
            "Per-faction player-standing ceilings: useful for stages "
            "gated on 'player has not turned on the Lantern'."
        ),
    )
    custom_condition: str = Field(
        default="",
        description=(
            "Free-text narrative condition for cases too shaped to encode "
            "structurally. Surfaced to the LLM alongside the rest of the "
            "trigger so the generator can apply it; the runtime ignores "
            "this field when deciding if the stage is active."
        ),
    )


class ArcStage(BaseModel):
    """One named beat in a character arc (v0.10.0).

    Stages are ordered within the arc's ``stages`` list — each stage's
    trigger is evaluated in order, and activation is cumulative: reaching
    stage 3 implicitly keeps stages 1 and 2 active too. Voice shifts
    stack (each stage's shift stays in effect once reached).

    Stages are *latched*: once the trigger fires, the stage stays active
    for the rest of the campaign even if the conditions later become
    false. This is what makes arcs feel like life history rather than a
    state machine. The runtime records latch events in the memory store
    with event_type='arc_latched'.
    """

    id: str = Field(..., description="Lower_snake_case stage id unique per NPC.")
    label: str = Field(
        ...,
        description=(
            "Short writer-facing name: 'stranger', 'tentative', 'confidante', "
            "'cracking', 'naming_the_dead'. Shown in the Editor's arc viewer."
        ),
    )
    voice_shift: str = Field(
        ...,
        description=(
            "Concrete instruction to the generator when this stage is "
            "active: 'full sentences now, no contractions dropped', "
            "'hums the fourth verse audibly even around strangers'."
        ),
    )
    trigger: TriggerSpec = Field(
        default_factory=TriggerSpec,
        description=(
            "Structured activation condition. Empty = active from the "
            "start (typical for the first stage of an arc)."
        ),
    )
    unlocks_knowledge: list[str] = Field(
        default_factory=list,
        description=(
            "Knowledge item ids (see NpcSheet.knowledge) this stage "
            "unlocks. The generator treats these as having an always-true "
            "gate while this stage is active, regardless of the knowledge "
            "item's own gate field."
        ),
    )
    description: str = Field(
        default="",
        description="Writer note — why does the NPC shift like this?",
    )


class NpcArc(BaseModel):
    """Ordered character arc for one NPC (v0.10.0).

    A writer specifies the ordered path the NPC takes across the campaign.
    Stages later in the list typically have stricter triggers so they
    fire only after the player has invested time / made choices with
    this specific NPC.

    The arc is optional — NPCs without one keep the v0.9 behaviour
    (respondent prompt built purely from character sheet + memory).
    """

    stages: list[ArcStage] = Field(
        ...,
        min_length=1,
        description="At least one stage (usually the baseline).",
    )
    description: str = Field(
        default="",
        description="High-level sentence: what this NPC's arc is about.",
    )


class StateEvolution(BaseModel):
    """One voice shift this NPC undergoes when a world condition becomes true (v0.8.1).

    Unlike greeting variants (which branch at runtime), evolution entries
    describe how the NPC's *written voice* changes at quest beats. The
    respondent prompt lists active evolution entries so the LLM adjusts
    its output. Gates are free-text for now — same pattern as
    :class:`KnowledgeItem.gate`.
    """

    trigger: str = Field(
        ...,
        description=(
            "When the shift applies. Free-text reference to project "
            "variables: 'quest_locket_stage >= 3', 'disposition_mira < 20', "
            "'after the cave-in is public knowledge'."
        ),
    )
    voice_shift: str = Field(
        ...,
        description=(
            "Concrete description of how the voice changes when the trigger "
            "is active: 'speaks in full sentences now', 'stops defending "
            "Mira in conversation', 'humming stops almost entirely'."
        ),
    )
    description: str = Field(
        default="",
        description="Writer-facing note explaining why this shift happens.",
    )


class KnowledgeItem(BaseModel):
    """One structured fact an NPC possesses, with a gate controlling reveal (v0.8.0).

    Writers declare *what* the NPC knows, *when* they'd reveal it, and
    *how* they deflect if the gate is not met. The respondent prompt
    surfaces ungated facts as "things the NPC knows but will not state
    directly" and gated facts as conditional reveals.

    ``gate`` is free-text for now — a later release will add structured
    `{variable: value}` matching tied to the state layer. For v0.8.0
    writers describe the condition in prose and the LLM honours it.
    """

    id: str = Field(..., description="Short identifier for this fact (lower_snake_case).")
    fact: str = Field(..., description="The thing the NPC knows.")
    gate: str = Field(
        default="",
        description=(
            "When the NPC will reveal this fact. Empty = never reveals "
            "directly. Examples: 'after the player offers coin', 'only if "
            "player mentions the Moon Court', 'never'."
        ),
    )
    reveal_lines: list[str] = Field(
        default_factory=list,
        description=(
            "Two or three sample lines the NPC might say when the gate is "
            "met. Tone exemplars; the generator does not quote them verbatim."
        ),
    )
    deflect_lines: list[str] = Field(
        default_factory=list,
        description=(
            "Two or three sample deflection lines when the gate is not met. "
            "Tone exemplars; the generator does not quote them verbatim."
        ),
    )


class NpcSheet(BaseModel):
    """A single NPC entry from ``characters.yaml``.

    Required: ``id``, ``name``, ``role``, ``voice``. Everything else is optional.

    Voice-ceiling fields (``forbidden_words``, ``vocabulary_ceiling``,
    ``accent_markers``) are injected into the respondent system prompt and
    also used by :mod:`npcforge.lint` to flag violations in generated text.

    ``allowed_intents`` is an opt-in whitelist of intent ids. When empty, the
    NPC is considered to respond to every intent defined in
    ``player_intents.yaml``.
    """

    id: str
    name: str
    role: str
    voice: str
    background: str = ""
    motivations: list[str] = Field(default_factory=list)
    secret: str = ""
    speech_quirks: list[str] = Field(default_factory=list)
    sample_lines: list[str] = Field(default_factory=list)

    # Voice ceiling (v0.2.0)
    forbidden_words: list[str] = Field(default_factory=list)
    vocabulary_ceiling: VocabularyCeiling | None = None
    accent_markers: list[str] = Field(default_factory=list)

    # Per-NPC intent whitelist (v0.2.0). Empty = all intents allowed.
    allowed_intents: list[str] = Field(default_factory=list)

    # State-layer hook (v0.6.0). Project-variable ids this NPC reacts to —
    # injected into greeting/dialogue generators so their output references
    # the right variables without leaking every declared variable into every
    # NPC's prompt. Empty = no state reactions beyond implicit defaults
    # (e.g. the time-of-day greeting generator uses time_of_day regardless).
    reacts_to: list[str] = Field(default_factory=list)

    # Character depth (v0.8.0). Relationships declare this NPC's stance
    # toward other cast members; knowledge declares structured facts the
    # NPC possesses with optional gates controlling when they're revealed.
    # Both are injected into respondent prompts so generated dialogue can
    # reference them consistently.
    relationships: list[Relationship] = Field(default_factory=list)
    knowledge: list[KnowledgeItem] = Field(default_factory=list)

    # Character state evolution (v0.8.1). Each entry is a voice shift the
    # NPC undergoes when a trigger condition becomes true. Injected into
    # the respondent prompt so generated dialogue reflects the shift.
    state_evolution: list[StateEvolution] = Field(default_factory=list)

    # Campaign-scale character arc (v0.10.0). Optional ordered path of
    # stages the NPC moves through based on structured triggers against
    # the memory store + faction standings. Composes with (does not
    # replace) the legacy state_evolution free-text list.
    arc: NpcArc | None = None

    # Faction membership (v0.9.0 — social graph). Most NPCs belong to
    # exactly one faction; allow a second slot for dual loyalties (a
    # spy, a family member with a conflict of allegiances). Empty =
    # faction-free (hermits, travellers, the player's own shadow).
    faction_id: str = Field(
        default="",
        description=(
            "Primary faction id. Must resolve against factions.yaml when "
            "factions are defined. Empty string = no affiliation."
        ),
    )
    secondary_faction_id: str = Field(
        default="",
        description=(
            "Optional secondary faction — for spies, torn loyalties, "
            "family ties that cross faction lines."
        ),
    )


class NpcStub(BaseModel):
    """A placeholder entry in ``characters.yaml`` that ``resolve_stubs`` fills in.

    Authors write a stub when they want ``gen_npcs``'s style expansion but with
    a stronger seed than a free-text brief — e.g. "here's the id and a
    one-line voice hint; you pick everything else." Loaders keep stubs
    separate from :class:`NpcSheet`; the pipeline ignores stubs entirely.

    Set ``_generate: true`` to opt in. Any of ``name``, ``role``,
    ``voice_hint``, ``role_hint`` are treated as generator seeds.
    """

    id: str
    generate: bool = Field(default=True, alias="_generate")
    name: str = ""
    role: str = ""
    role_hint: str = ""
    voice_hint: str = ""

    model_config = {"populate_by_name": True, "extra": "ignore"}


class PlayerIntent(BaseModel):
    """A single entry from ``player_intents.yaml``.

    Intents describe *what the player is trying to do this turn* (barter,
    intimidate, flirt, ask_for_directions). They are finer-grained than
    "archetypes" (who the player is) — a barter intent will work for any
    class, but a hostile NPC may decline it.
    """

    id: str
    name: str
    description: str
    opening_intent: str = ""


class BarkTrigger(BaseModel):
    """A single bark trigger for one NPC.

    ``id`` becomes the Yarn node title suffix. ``n`` is how many unique
    variants to generate. ``description`` becomes the in-context prompt
    ("the NPC has just witnessed X"), so it should read as a situational
    cue, not a command.
    """

    id: str
    description: str
    n: int = 10


class NpcBarkConfig(BaseModel):
    """Bark config for a single NPC: id + list of triggers."""

    npc: str
    triggers: list[BarkTrigger]


class BarksConfig(BaseModel):
    """Top-level ``barks.yaml`` schema."""

    barks: list[NpcBarkConfig] = Field(default_factory=list)


class BarkLine(BaseModel):
    """One generated bark — structured-output target for the LLM."""

    text: str = Field(
        ...,
        description="The bark utterance. One short sentence. In character.",
    )
    emotion: Literal[
        "neutral",
        "angry",
        "scared",
        "happy",
        "sad",
        "surprised",
        "disgusted",
        "confused",
        "sarcastic",
        "threatening",
        "pleading",
    ] = "neutral"
    intensity: Literal["low", "medium", "high"] = "medium"


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def _load_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be a YAML mapping")
    return data


def _is_stub_entry(item: dict) -> bool:
    return bool(item.get("_generate")) or bool(item.get("generate"))


def load_npcs(path: Path) -> list[NpcSheet]:
    """Load fully-authored NPCs from ``characters.yaml``.

    Stub entries (``_generate: true``) are skipped silently — they are not
    ready for the pipeline yet. Use :func:`load_npcs_with_stubs` to see both.
    """
    data = _load_yaml(path)
    if "npcs" not in data:
        raise ValueError(f"{path} must define a top-level 'npcs:' key")
    items = data["npcs"]
    if not isinstance(items, list) or not items:
        raise ValueError(f"{path} -> 'npcs' must be a non-empty list")
    return [NpcSheet(**item) for item in items if not _is_stub_entry(item)]


def load_npcs_with_stubs(path: Path) -> tuple[list[NpcSheet], list[NpcStub]]:
    """Load both full NPC sheets and stub placeholders from ``characters.yaml``.

    Useful for :func:`npcforge.generation.resolve_stubs` and for read-only
    tools that need to surface stubs to writers / agents.
    """
    data = _load_yaml(path)
    if "npcs" not in data:
        raise ValueError(f"{path} must define a top-level 'npcs:' key")
    items = data["npcs"]
    if not isinstance(items, list):
        raise ValueError(f"{path} -> 'npcs' must be a list")
    full: list[NpcSheet] = []
    stubs: list[NpcStub] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError(f"{path} npc entry must be a mapping, got: {item!r}")
        if _is_stub_entry(item):
            stubs.append(NpcStub(**item))
        else:
            full.append(NpcSheet(**item))
    return full, stubs


def load_intents(path: Path) -> list[PlayerIntent]:
    """Load player intents from ``player_intents.yaml`` (top-level ``intents:`` key)."""
    data = _load_yaml(path)
    if "intents" not in data:
        raise ValueError(f"{path} must define a top-level 'intents:' key")
    items = data["intents"]
    if not isinstance(items, list) or not items:
        raise ValueError(f"{path} -> 'intents' must be a non-empty list")
    return [PlayerIntent(**item) for item in items]


def load_barks_config(path: Path) -> BarksConfig:
    """Load ``barks.yaml`` if present. Returns an empty config if missing."""
    if not path.exists():
        return BarksConfig()
    data = _load_yaml(path)
    return BarksConfig(**data)


def load_factions(path: Path) -> FactionsConfig:
    """Load ``factions.yaml`` if present. Returns an empty config if missing.

    Validates that ``allies`` and ``rivals`` reference ids that exist in
    the same file — dangling references silently become empty strings in
    practice but we want a loud failure at load time.
    """
    if not path.exists():
        return FactionsConfig()
    data = _load_yaml(path)
    cfg = FactionsConfig(**data)
    known = {f.id for f in cfg.factions}
    for f in cfg.factions:
        for side, items in (("allies", f.allies), ("rivals", f.rivals)):
            unknown = [x for x in items if x not in known]
            if unknown:
                raise ValueError(
                    f"Faction '{f.id}' lists unknown {side}: {unknown}. "
                    f"Known ids: {sorted(known)}"
                )
    return cfg


def validate_npc_arcs(npcs: list[NpcSheet]) -> None:
    """Fail loudly on arc schema problems we can catch statically.

    Checks: (1) stage ids are unique per NPC, (2) unlocks_knowledge
    references resolve against that NPC's knowledge list, (3) stages
    with no trigger constraints are only allowed as the first stage
    (an always-active "baseline" stage in the middle of an arc would
    make later stages redundant).
    """
    for npc in npcs:
        if npc.arc is None:
            continue
        seen: set[str] = set()
        known_knowledge = {k.id for k in npc.knowledge}
        for i, stage in enumerate(npc.arc.stages):
            if stage.id in seen:
                raise ValueError(
                    f"NPC '{npc.id}': duplicate arc stage id '{stage.id}'"
                )
            seen.add(stage.id)

            missing = [
                ref for ref in stage.unlocks_knowledge
                if ref not in known_knowledge
            ]
            if missing:
                raise ValueError(
                    f"NPC '{npc.id}': arc stage '{stage.id}' unlocks "
                    f"unknown knowledge ids {missing}. Known: "
                    f"{sorted(known_knowledge)}"
                )

            is_always_active = (
                stage.trigger.min_pivotal_events == 0
                and stage.trigger.min_total_events == 0
                and not stage.trigger.required_event_types
                and not stage.trigger.min_standing
                and not stage.trigger.max_standing
                and not stage.trigger.custom_condition.strip()
            )
            if is_always_active and i > 0:
                raise ValueError(
                    f"NPC '{npc.id}': arc stage '{stage.id}' at position "
                    f"{i} has an empty trigger but isn't the first stage. "
                    "Only the baseline (index 0) may be unconditionally "
                    "active — later stages need a trigger."
                )


def validate_npc_factions(
    npcs: list[NpcSheet], factions: FactionsConfig
) -> None:
    """Fail loudly if any NPC references a faction that isn't declared.

    Called after loading both files. A typo in ``characters.yaml``'s
    ``faction_id`` would otherwise compile prompts with an unknown id —
    still functional but the social-graph injection would be inert.
    """
    if not factions.factions:
        # No factions declared — NPCs simply must not claim membership.
        offenders = [
            n.id for n in npcs
            if n.faction_id or n.secondary_faction_id
        ]
        if offenders:
            raise ValueError(
                f"NPCs claim faction membership but no factions.yaml was "
                f"loaded: {offenders}"
            )
        return
    known = {f.id for f in factions.factions}
    for npc in npcs:
        for slot, value in (
            ("faction_id", npc.faction_id),
            ("secondary_faction_id", npc.secondary_faction_id),
        ):
            if value and value not in known:
                raise ValueError(
                    f"NPC '{npc.id}' {slot}='{value}' is not a declared "
                    f"faction. Known: {sorted(known)}"
                )


def load_world_bible(lore_dir: Path) -> str:
    """Concatenate every ``*.md`` file under ``lore_dir`` (lexicographic order)."""
    if not lore_dir.is_dir():
        raise FileNotFoundError(f"Lore directory not found: {lore_dir}")
    chunks: list[str] = [
        p.read_text(encoding="utf-8").strip() for p in sorted(lore_dir.glob("*.md"))
    ]
    if not chunks:
        raise ValueError(f"No markdown lore files found in {lore_dir}")
    return "\n\n".join(chunks)


def resolve_intents_for_npc(
    npc: NpcSheet,
    all_intents: list[PlayerIntent],
) -> list[PlayerIntent]:
    """Intersect an NPC's ``allowed_intents`` with the project-wide intent list.

    Empty whitelist → all intents. Preserves the order given in
    ``player_intents.yaml``. Intent ids listed in ``allowed_intents`` that
    are not defined project-wide are silently ignored (the loader should
    already have caught typos).
    """
    if not npc.allowed_intents:
        return list(all_intents)
    allow = set(npc.allowed_intents)
    return [intent for intent in all_intents if intent.id in allow]
