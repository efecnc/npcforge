"""Disposition-curated line banks (v0.11.0).

Walk-up dialogue, barks, and greetings already exist as pre-authored
variants. Line banks generalise that idea to *every* utterance an NPC
might speak in service of a gameplay slot ("greeting",
"acknowledge_gift", "interrupt", etc.). Each variant carries a set of
:class:`LineTag`\\ s describing the context it was written for
(disposition tier, arc stage, mood, a recent event type, a faction
present in the scene, time of day). At runtime the selector picks
whichever variant *best* matches the current context — no LLM call
in the hot path, but the bank is dense enough to feel generative.

Structure in one paragraph:

- A :class:`LineSlot` describes a kind of utterance (id, description,
  optional default_text fallback).
- A :class:`LineVariant` is one pre-generated string with a bag of
  ``(dimension, value)`` tags.
- A :class:`LineBank` holds all slots + all variants for one NPC. One
  JSON file per NPC so the runtime can lazy-load per character.
- :func:`select_line` filters variants by AND-of-all-tags (a variant
  matches only when every one of its tags is satisfied by the supplied
  context). Ties are broken by salience_boost then by least-recently-
  used so the same line doesn't fire twice in a row.

Dimensions are intentionally a closed vocabulary so the runtime and the
generator can't drift. Extending requires a code change, not a schema
tweak — keeps the selector logic easy to reason about.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


# Closed vocabulary. Add new dimensions here intentionally.
LineDimension = Literal[
    "disposition_tier",   # hostile | wary | neutral | friendly | trusted
    "arc_stage",          # any NpcArc stage id (e.g. "confidante")
    "mood",               # grateful | resentful | tired | wary | hopeful | ...
    "recent_event_type",  # gift_given | player_lied | secret_shared | ...
    "time_of_day",        # dawn | morning | afternoon | dusk | night
    "faction_present",    # faction_id of someone else in the room
]


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class LineTag(BaseModel):
    """One dimension of a line variant's match profile.

    Equality on ``(dimension, value)`` pairs lets the selector compare
    tags without string-gymnastics. Keep values lower_snake_case so
    case-mismatches don't silently cause misses.
    """

    dimension: LineDimension
    value: str = Field(
        ...,
        description=(
            "The required value along the dimension. 'trusted' for a "
            "disposition_tier tag, 'grateful' for a mood tag, etc. "
            "Case-sensitive — pin it to lower_snake_case conventionally."
        ),
    )


class LineVariant(BaseModel):
    """One pre-generated utterance for a slot, with match tags."""

    text: str = Field(..., description="The line, in character.")
    tags: list[LineTag] = Field(
        default_factory=list,
        description=(
            "Bag of (dimension, value) pairs. All must match in the "
            "runtime context for this variant to be eligible. An empty "
            "tag list means the variant is context-agnostic (always "
            "eligible — useful for fallback lines)."
        ),
    )
    salience_boost: float = Field(
        default=0.0,
        description=(
            "Positive numbers prefer this variant over equal-match peers. "
            "Authors can hand-tune pivotal lines up; generated variants "
            "default to 0."
        ),
    )
    source: str = Field(
        default="",
        description=(
            "Who produced this variant — typically a model id like "
            "'gemini-2.5-flash' or 'hand-authored'. Diagnostic only."
        ),
    )


class LineSlot(BaseModel):
    """Writer-facing description of an utterance category."""

    id: str = Field(
        ...,
        description=(
            "Lower_snake_case slot id: 'greeting', 'acknowledge_gift', "
            "'respond_to_interrupt'. Runtime addresses variants by this id."
        ),
    )
    description: str = Field(
        ...,
        description=(
            "One-line description of when this line is spoken. Injected "
            "into the generator's prompt verbatim so the LLM knows the "
            "occasion."
        ),
    )
    default_text: str = Field(
        default="",
        description=(
            "Fallback string if no variant matches the context. Kept per-"
            "slot so a generic 'Mira nods.' can replace missing banks "
            "without crashing the scene."
        ),
    )


class LineBank(BaseModel):
    """All line banks for one NPC (one JSON file per character).

    The top-level shape is a dict of slot_id → variants to keep random
    lookups O(1) regardless of how many slots an NPC accumulates.
    """

    schema_version: str = Field(default="1")
    npc_id: str
    slots: dict[str, LineSlot] = Field(default_factory=dict)
    variants: dict[str, list[LineVariant]] = Field(default_factory=dict)

    # ------------------------------------------------------------------
    # Ergonomic helpers
    # ------------------------------------------------------------------

    def add_slot(self, slot: LineSlot) -> None:
        self.slots[slot.id] = slot
        self.variants.setdefault(slot.id, [])

    def add_variant(self, slot_id: str, variant: LineVariant) -> None:
        if slot_id not in self.slots:
            raise KeyError(
                f"LineBank for '{self.npc_id}' has no slot '{slot_id}'. "
                f"Call add_slot first."
            )
        self.variants.setdefault(slot_id, []).append(variant)

    def variant_count(self, slot_id: str) -> int:
        return len(self.variants.get(slot_id, []))

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def to_json(self, indent: int = 2) -> str:
        return self.model_dump_json(indent=indent)

    def to_unity_json(self, indent: int = 2) -> str:
        """Emit a JsonUtility-friendly layout for the Unity runtime.

        Unity's built-in deserialiser can't handle ``dict<string, X>``.
        We reshape ``slots`` and ``variants`` into lists of keyed structs
        so ``NpcForgeLineBank`` can round-trip via ``JsonUtility.FromJson``.
        The native ``to_json`` output stays dict-shaped for Python-side
        tooling.
        """
        payload = {
            "schema_version": self.schema_version,
            "npc_id": self.npc_id,
            "slot_entries": [
                {"key": sid, "slot": slot.model_dump()}
                for sid, slot in self.slots.items()
            ],
            "variant_entries": [
                {
                    "key": sid,
                    "list": [v.model_dump() for v in vs],
                }
                for sid, vs in self.variants.items()
            ],
        }
        return json.dumps(payload, indent=indent, ensure_ascii=False)

    def save(self, path: Path) -> None:
        """Write both the native and Unity-friendly JSON files.

        ``path`` gets the native (dict-shaped) payload; a sibling file
        with the ``.unity.json`` suffix gets the list-shaped payload.
        The Unity runtime reads the ``.unity.json`` file; the npcforge
        CLI + Editor read the native one.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")
        unity_path = path.with_suffix(".unity.json")
        unity_path.write_text(self.to_unity_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "LineBank":
        if not path.exists():
            raise FileNotFoundError(f"No line bank at {path}")
        return cls.model_validate_json(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Context + selector
# ---------------------------------------------------------------------------


class LineContext(BaseModel):
    """What's true about the world for the next line.

    Runtime callers assemble this by reading whatever sources they have
    (memory store, faction standings, arc tracker, scene state) and
    projecting it into the closed dimension vocabulary. Unknown
    dimensions stay unset; variants tagged on them simply can't match.
    """

    disposition_tier: str = ""
    arc_stage: str = ""          # single active stage id (typically the highest one)
    mood: str = ""
    recent_event_type: str = ""
    time_of_day: str = ""
    faction_present: str = ""    # faction_id of a second NPC in the room

    def value_for(self, dimension: LineDimension) -> str:
        return getattr(self, dimension, "")


def variant_matches(variant: LineVariant, ctx: LineContext) -> bool:
    """True when every one of the variant's tags is satisfied by ctx.

    A variant with no tags always matches — useful for context-agnostic
    fallbacks. A variant with any tag whose dimension is unset in ctx
    (empty string) cannot match — forcing callers to populate the
    relevant dimensions before selection.
    """
    for tag in variant.tags:
        current = ctx.value_for(tag.dimension)
        if current == "" or current != tag.value:
            return False
    return True


def select_line(
    bank: LineBank,
    slot_id: str,
    ctx: LineContext,
    *,
    recently_picked: set[str] | None = None,
    rng: random.Random | None = None,
) -> str:
    """Pick the best variant for ``slot_id`` given ``ctx``.

    Ranking:
      1. Only variants whose tags all match the context.
      2. Prefer variants with more tags (a highly specific match beats
         a context-agnostic fallback).
      3. Prefer variants with the highest ``salience_boost``.
      4. Prefer variants NOT in ``recently_picked`` (LRU avoidance).
      5. Break remaining ties with ``rng.choice``.

    If no variant matches and no tagged variants exist, fall through to
    the slot's ``default_text``. If neither exists, return an empty
    string so the caller can decide on an error message — we don't
    raise because a missing-line in production shouldn't crash the game.
    """
    if slot_id not in bank.variants:
        slot = bank.slots.get(slot_id)
        return slot.default_text if slot else ""

    candidates = [v for v in bank.variants[slot_id] if variant_matches(v, ctx)]
    if not candidates:
        slot = bank.slots.get(slot_id)
        return slot.default_text if slot else ""

    recently_picked = recently_picked or set()

    def score(v: LineVariant) -> tuple[int, float, int]:
        """Higher tuple = better. We negate recently_picked so fresh wins."""
        not_recent = 0 if v.text in recently_picked else 1
        return (len(v.tags), v.salience_boost, not_recent)

    best_score = max(score(v) for v in candidates)
    top = [v for v in candidates if score(v) == best_score]
    chooser = rng if rng is not None else random
    return chooser.choice(top).text


# ---------------------------------------------------------------------------
# Tag-combo expansion — used by the generator to enumerate what to build
# ---------------------------------------------------------------------------


def expand_tag_combos(
    *,
    disposition_tiers: list[str] | None = None,
    arc_stages: list[str] | None = None,
    moods: list[str] | None = None,
    recent_event_types: list[str] | None = None,
    times_of_day: list[str] | None = None,
    factions_present: list[str] | None = None,
) -> list[list[LineTag]]:
    """Cartesian expansion of the supplied dimensions.

    Generator callers choose which dimensions to vary along for a given
    slot — you rarely want every combination (``5 × 4 × 3 × ...`` gets
    expensive). Pass only the axes that matter for the slot. An empty
    ``axes`` list produces one empty tag-combo (the context-agnostic
    fallback).

    Example::

        combos = expand_tag_combos(
            disposition_tiers=["wary", "neutral", "friendly"],
            times_of_day=["morning", "dusk"],
        )
        # 3 × 2 = 6 combos, each with exactly two tags.
    """
    axes: list[tuple[LineDimension, list[str]]] = []
    if disposition_tiers:
        axes.append(("disposition_tier", disposition_tiers))
    if arc_stages:
        axes.append(("arc_stage", arc_stages))
    if moods:
        axes.append(("mood", moods))
    if recent_event_types:
        axes.append(("recent_event_type", recent_event_types))
    if times_of_day:
        axes.append(("time_of_day", times_of_day))
    if factions_present:
        axes.append(("faction_present", factions_present))

    if not axes:
        return [[]]

    combos: list[list[LineTag]] = [[]]
    for dimension, values in axes:
        combos = [
            tags + [LineTag(dimension=dimension, value=v)]
            for tags in combos
            for v in values
        ]
    return combos


# ---------------------------------------------------------------------------
# Diagnostic helper
# ---------------------------------------------------------------------------


def bank_coverage_report(bank: LineBank) -> dict[str, dict[str, int]]:
    """Per-slot coverage counts broken down by dimension values.

    Useful for CLI + Editor tooling: answer "how many greeting variants
    do I have for disposition_tier=trusted?" in one glance.
    """
    report: dict[str, dict[str, int]] = {}
    for slot_id, variants in bank.variants.items():
        counts: dict[str, int] = {"_total": len(variants)}
        for v in variants:
            for tag in v.tags:
                key = f"{tag.dimension}={tag.value}"
                counts[key] = counts.get(key, 0) + 1
        report[slot_id] = counts
    return report
