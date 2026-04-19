"""Emergent NPC birthing (v0.15.0).

When an NPC mentions someone who hasn't been authored yet — Gereth's
"the foreman who took the last drink" — the system keeps a
*canonical record* of every such mention. Sessions later, when the
player finally encounters that character, :func:`materialize` generates
a full :class:`~.schemas.NpcSheet` that is *consistent with every
recorded mention*. The foreman isn't invented at meeting-time — they
arrive with the backstory all of the other NPCs have already given them.

Design in one paragraph:

- Writers declare an unseen slot up front with a stable
  ``canonical_id``. No NLP entity-extraction magic — explicit and
  controllable, which matches how game writers actually work.
- Every in-game mention is recorded against that slot. Mentions carry
  the source NPC id (who said it), a one-sentence context, and the
  turn count. The registry persists to JSON beside the memory store.
- :func:`summarize_canon` renders the accumulated record as a prompt
  block for the materialiser. The block becomes *the* source of truth
  for the new sheet — no LLM invention of facts that contradict a
  prior mention.
- :func:`materialize` calls the LLM with a system prompt that embeds
  the canon, returns an ``NpcSheet``, and appends it to the cast. The
  writer reviews the result (nothing is ever auto-written to
  ``characters.yaml`` without ``--commit``).

Why NOT auto-detect mentions from LLM output? Two reasons: (1) named-
entity recognition at scale is its own hard problem; (2) the designers
we've talked to want explicit control over which unseen characters
exist in the world. A simple explicit slot-then-record model preserves
writer agency and keeps the schema debuggable.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from .schemas import (
    FactionsConfig,
    KnowledgeItem,
    NpcSheet,
    Relationship,
    StateEvolution,
    VocabularyCeiling,
    VoiceLens,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class MentionRecord(BaseModel):
    """One recorded reference to an unseen character."""

    source_npc_id: str = Field(
        ...,
        description="Which NPC said / implied the mention.",
    )
    context: str = Field(
        ...,
        description=(
            "One-sentence paraphrase of what the source said about this "
            "unseen character. Phrased from the source's POV; becomes "
            "verbatim canon when materialising."
        ),
    )
    turn: int = Field(
        default=0,
        ge=0,
        description="Monotonic turn counter from the memory store.",
    )
    scene_context: str = Field(
        default="",
        description=(
            "Optional scene tag — helpful for diagnostics ('scene_common_"
            "room_inspector', 'walk_up_gereth_barter'). Not used by the "
            "materialiser."
        ),
    )


class UnseenCharacter(BaseModel):
    """Accumulated canon for one mentioned-but-unseen person.

    The writer creates the slot up front with a stable ``canonical_id``
    and a ``display_name_hint`` (the best first-guess name). Every
    subsequent mention appends to :attr:`mention_records`. When
    materialised, the slot records the resulting NPC id so the registry
    knows the character is now "realised" — later mentions keep
    accumulating but the materialiser refuses to re-run (write once
    semantics).
    """

    canonical_id: str = Field(
        ...,
        description=(
            "Lower_snake_case stable id. Materialisation produces an NPC "
            "with this id by default; pass a new_id= to override."
        ),
    )
    display_name_hint: str = Field(
        default="",
        description=(
            "Best-guess display name. Materialisation will use this unless "
            "explicit mentions reshape it (e.g. 'the foreman' eventually "
            "gets named 'Borin' in a mention)."
        ),
    )
    role_hint: str = Field(
        default="",
        description=(
            "Optional one-phrase role seed — 'dwarven mining foreman', "
            "'cleric of the Moon Court'. Threaded into the materialiser "
            "prompt but subordinate to the mention records."
        ),
    )
    mention_records: list[MentionRecord] = Field(default_factory=list)
    materialized_as: str = Field(
        default="",
        description=(
            "NPC id that was produced when the player finally met this "
            "character. Empty = still unseen. Materialisation refuses to "
            "overwrite a non-empty value."
        ),
    )


class UnseenRegistry(BaseModel):
    """Collection of unseen character slots with JSON persistence.

    Persists to ``<demo-dir>/unseen.json``. The registry is append-only
    from the runtime's perspective (mentions accumulate); writers can
    edit the file by hand to redact or merge slots during authoring.
    """

    schema_version: str = Field(default="1")
    characters: dict[str, UnseenCharacter] = Field(default_factory=dict)

    # ------------------------------------------------------------------
    # Ergonomic helpers
    # ------------------------------------------------------------------

    def declare(
        self,
        canonical_id: str,
        *,
        display_name_hint: str = "",
        role_hint: str = "",
    ) -> UnseenCharacter:
        """Create the slot if missing; return the existing one otherwise.

        Idempotent — calling with the same id twice doesn't reset
        accumulated mentions.
        """
        if canonical_id in self.characters:
            return self.characters[canonical_id]
        self.characters[canonical_id] = UnseenCharacter(
            canonical_id=canonical_id,
            display_name_hint=display_name_hint,
            role_hint=role_hint,
        )
        return self.characters[canonical_id]

    def record_mention(
        self,
        canonical_id: str,
        *,
        source_npc_id: str,
        context: str,
        turn: int = 0,
        scene_context: str = "",
    ) -> MentionRecord:
        """Append a mention to an unseen slot. Raises if the slot hasn't
        been declared — this is intentional: mentions against unknown
        ids are usually typos, not silent extensions of the canon."""
        if canonical_id not in self.characters:
            raise KeyError(
                f"UnseenRegistry has no character '{canonical_id}'. "
                f"Declare it first with registry.declare(...)."
            )
        record = MentionRecord(
            source_npc_id=source_npc_id,
            context=context,
            turn=turn,
            scene_context=scene_context,
        )
        self.characters[canonical_id].mention_records.append(record)
        return record

    def still_unseen(self, canonical_id: str) -> bool:
        """True if the slot exists and hasn't been materialised yet."""
        if canonical_id not in self.characters:
            return False
        return not self.characters[canonical_id].materialized_as.strip()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def to_json(self, indent: int = 2) -> str:
        return self.model_dump_json(indent=indent)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "UnseenRegistry":
        if not path.exists():
            return cls()
        return cls.model_validate_json(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Summariser — prompt block shared with the materialiser
# ---------------------------------------------------------------------------


def summarize_canon(unseen: UnseenCharacter) -> str:
    """Render the accumulated mention canon as a prompt block.

    Format:

        Canon accumulated from prior scenes (everything below must
        remain TRUE in the generated character sheet):
        - [turn 3, from gereth_blackstone] Borin was the foreman of the
          seam; he took the last drink before they went down.
        - [turn 5, from mira_vesser] Borin still owed the Lantern two
          coppers when the cave-in took him.

    Empty mention list → empty block. Callers decide whether to
    materialise with no canon (usually pointless, but allowed).
    """
    if not unseen.mention_records:
        return ""
    lines = [
        "Canon accumulated from prior scenes (everything below must "
        "remain TRUE in the generated character sheet; any invention "
        "that contradicts a canon line is a rule violation):"
    ]
    for m in unseen.mention_records:
        scene = f", {m.scene_context}" if m.scene_context else ""
        lines.append(
            f"- [turn {m.turn}, from {m.source_npc_id}{scene}] "
            f"{m.context.strip()}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Materialisation prompt
# ---------------------------------------------------------------------------


def build_materialize_system_prompt(
    unseen: UnseenCharacter,
    *,
    world_bible: str,
    existing_cast: list[NpcSheet],
    factions: Optional[FactionsConfig] = None,
) -> str:
    """System prompt for the materialiser.

    Embeds the world bible, the canon block, and a roster of existing
    NPCs so the generated character references them consistently (the
    new NPC's relationships, if they include any, must point at
    real ids). Faction list is included when supplied so the new NPC
    can pick a faction id that actually exists.
    """
    roster_lines: list[str] = []
    for n in existing_cast:
        roster_lines.append(f"- {n.id}: {n.name} — {n.role}")
    roster = "\n".join(roster_lines) or "(cast empty)"

    faction_roster = ""
    if factions is not None and factions.factions:
        faction_roster = "\nFactions currently defined (pick faction_id from this list):\n"
        for f in factions.factions:
            faction_roster += f"- {f.id}: {f.name}\n"
        faction_roster = faction_roster.rstrip()

    canon_block = summarize_canon(unseen)

    rules = (
        "You are materialising a character who has been mentioned by "
        "others in the game world but never authored directly. Produce a "
        "full NpcSheet (JSON matching the schema) that:\n"
        "1. Is fully consistent with every canon line above. Any sheet "
        "that contradicts a mention is rejected.\n"
        "2. Fits the world bible's tone + setting. Low fantasy, quiet "
        "dread; characters say less than they know.\n"
        "3. Has a distinct voice — specific speech quirks, accent "
        "markers, forbidden words, sample lines. No generic archetype "
        "language.\n"
        "4. Declares relationships only toward NPCs in the roster above "
        "(use their exact ids). Never invent a relationship target id.\n"
        "5. Picks a faction_id from the factions list if relevant; leave "
        "it empty otherwise. Do not invent faction ids.\n"
        "6. The character's core motivations and secret must be "
        "compatible with the canon — a mention that the character was "
        "'the foreman of the seam' means their role can't be 'cleric'.\n"
    )

    return "\n\n".join([
        "## World bible\n" + world_bible.rstrip(),
        canon_block if canon_block else "(no canon accumulated yet)",
        "## Existing cast\n" + roster,
        faction_roster.lstrip() if faction_roster else "",
        rules.rstrip(),
    ]).strip() + "\n"


# ---------------------------------------------------------------------------
# Materialisation entry point
# ---------------------------------------------------------------------------


class _MaterializedNpcDraft(BaseModel):
    """Structured-output target for the materialiser.

    Subset of :class:`~.schemas.NpcSheet` — intentionally omits the
    campaign-arc layer (TriggerSpec has dict fields Gemini's function-
    call schema doesn't accept). Writers author arc stages + voice
    lenses after materialisation, when they already know who the
    character is going to be across many sessions.
    """

    id: str = Field(..., description="Lower_snake_case NPC id; usually the canonical id.")
    name: str = Field(..., description="Display name.")
    role: str = Field(..., description="One-phrase role.")
    voice: str = Field(..., description="Specific, not generic. 1-2 sentences.")
    background: str = Field(default="", description="Short backstory paragraph.")
    motivations: list[str] = Field(default_factory=list)
    secret: str = Field(default="", description="Never disclose directly.")
    speech_quirks: list[str] = Field(default_factory=list)
    sample_lines: list[str] = Field(default_factory=list)
    forbidden_words: list[str] = Field(default_factory=list)
    vocabulary_ceiling: Optional[VocabularyCeiling] = None
    accent_markers: list[str] = Field(default_factory=list)
    allowed_intents: list[str] = Field(default_factory=list)
    reacts_to: list[str] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)
    knowledge: list[KnowledgeItem] = Field(default_factory=list)
    state_evolution: list[StateEvolution] = Field(default_factory=list)
    faction_id: str = Field(default="")
    secondary_faction_id: str = Field(default="")
    observes_player: bool = Field(default=False)


def _draft_to_sheet(draft: _MaterializedNpcDraft) -> NpcSheet:
    return NpcSheet(**draft.model_dump())


async def materialize(
    *,
    unseen: UnseenCharacter,
    world_bible: str,
    existing_cast: list[NpcSheet],
    factions: Optional[FactionsConfig],
    api_key: str,
    model_name: Optional[str],
    model_provider_name: str,
    temperature: float = 0.85,
    override_id: str = "",
) -> NpcSheet | None:
    """Generate a full NpcSheet for an unseen character. Returns None on
    failure so callers can fall back to a manual authoring flow.

    Pinned behaviours:
    - ``override_id`` lets the caller set the new NPC's id explicitly;
      otherwise the canonical_id is used verbatim.
    - The materialiser refuses to re-run on an already-materialised slot
      (returns None + logs). Callers wanting to "re-roll" must clear
      ``materialized_as`` first.
    """
    if unseen.materialized_as.strip():
        logger.warning(
            "unseen '%s' already materialised as '%s'; refusing to "
            "overwrite. Clear materialized_as to re-roll.",
            unseen.canonical_id, unseen.materialized_as,
        )
        return None

    system_prompt = build_materialize_system_prompt(
        unseen,
        world_bible=world_bible,
        existing_cast=existing_cast,
        factions=factions,
    )

    from afterimage.common import default_model_name as _AFTERIMAGE_DEFAULT_MODEL
    from afterimage.providers import LLMFactory

    effective_model = model_name or _AFTERIMAGE_DEFAULT_MODEL
    llm = LLMFactory.create(
        provider=model_provider_name,
        model_name=effective_model,
        api_key=api_key,
        system_instruction=system_prompt,
    )

    user_prompt = (
        f"Materialise the character with canonical id "
        f"'{unseen.canonical_id}'. "
        f"Display name hint: '{unseen.display_name_hint}'. "
        f"Role hint: '{unseen.role_hint or '(none — infer from canon)'}'."
        f"\n\nReturn JSON matching the NpcSheet schema."
    )

    try:
        response = await llm.agenerate_structured(
            prompt=user_prompt,
            schema=_MaterializedNpcDraft,
            temperature=temperature,
        )
    except Exception as exc:
        logger.warning(
            "materialize failed for '%s': %s",
            unseen.canonical_id, exc,
        )
        return None

    parsed = getattr(response, "parsed", None)
    draft: _MaterializedNpcDraft | None
    if isinstance(parsed, _MaterializedNpcDraft):
        draft = parsed
    else:
        try:
            draft = _MaterializedNpcDraft.model_validate_json(response.text)
        except Exception as exc:
            logger.warning(
                "materialize JSON parse failed for '%s': %s",
                unseen.canonical_id, exc,
            )
            return None

    # Pin the id — the LLM occasionally tries to be creative with slug
    # normalisation. Canonical id wins unless override explicitly supplied.
    draft.id = override_id or unseen.canonical_id
    return _draft_to_sheet(draft)
