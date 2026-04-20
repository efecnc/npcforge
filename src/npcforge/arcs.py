"""Character-arc evaluation (v0.10.0 — campaign-scale depth).

An NPC's :class:`~.schemas.NpcArc` lists ordered stages the character
moves through over the whole campaign, each with a structured
:class:`~.schemas.TriggerSpec` condition. This module turns that
declaration into an answer to two questions:

    1. Given the current memory store + faction-standing snapshot,
       which stages of this NPC's arc are currently active?

    2. If we've *ever* seen stage N fire before, is it still active?
       (Stages latch: once a character has begun naming their dead
       aloud, they don't unname them because the player's standing
       later dipped.)

Answer #1 drives the generator's voice-shift injection into the
respondent prompt. Answer #2 matters for runtime behaviour — the
Unity ``NpcForgeArcTracker`` records every latch event back into the
memory store so the next session's answer is correctly monotonic.

We deliberately don't evaluate ``custom_condition`` here. That's a
narrative instruction meant for the LLM to judge ("active after the
player has witnessed Gereth weep in private"). Encoding it would
require a scene-awareness the runtime doesn't have. The prompt layer
surfaces it verbatim so the LLM can apply it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .memory import MemoryStore
from .quests import QuestTracker
from .schemas import ArcStage, NpcSheet, QuestsConfig, TriggerSpec


# Event-type tag used when the runtime records a stage latching for
# the first time. Exposed as a constant so callers can filter it out
# of the player-facing summary if they want to.
ARC_LATCH_EVENT_TYPE = "arc_latched"


@dataclass
class ActiveStage:
    """One currently-active stage in an evaluated arc.

    ``latched`` is True when the stage was activated by a prior turn
    (recorded in the memory store as an ARC_LATCH_EVENT_TYPE event) and
    stays active regardless of whether the trigger is still satisfied.
    Baseline stages (position 0, always-true trigger) are ``latched``
    from the start of the campaign.
    """

    stage: ArcStage
    index: int
    latched: bool


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def evaluate_arc(
    npc: NpcSheet,
    store: MemoryStore | None = None,
    standings: Mapping[str, float] | None = None,
    quest_tracker: QuestTracker | None = None,
    quest_config: QuestsConfig | None = None,
) -> list[ActiveStage]:
    """Return every stage that's currently active, cumulative + in order.

    Activation is cumulative: if stage 2 is active, stages 0 and 1 are
    also active (earlier stages don't 'expire' when the NPC moves
    deeper into the arc — their voice shifts still compose into the
    current speaking register).

    Latching: a stage with a previously-recorded ``arc_latched`` event
    in ``store`` (matching ``npc_id`` and the stage's id in the event's
    summary) stays active even if its structured trigger no longer
    holds. This is what keeps arcs monotonic across sessions.
    """
    if npc.arc is None or not npc.arc.stages:
        return []

    standings = dict(standings or {})
    store_or_empty = store if store is not None else MemoryStore()

    latched_ids = _previously_latched_stage_ids(npc.id, store_or_empty)

    active: list[ActiveStage] = []
    for i, stage in enumerate(npc.arc.stages):
        is_latched = stage.id in latched_ids
        trigger_met = _trigger_satisfied(
            stage.trigger,
            npc,
            store_or_empty,
            standings,
            quest_tracker=quest_tracker,
            quest_config=quest_config,
        )
        if is_latched or trigger_met:
            active.append(
                ActiveStage(stage=stage, index=i, latched=is_latched)
            )
    return active


def newly_latched_stages(
    npc: NpcSheet,
    store: MemoryStore,
    standings: Mapping[str, float] | None = None,
    quest_tracker: QuestTracker | None = None,
    quest_config: QuestsConfig | None = None,
) -> list[ActiveStage]:
    """Return stages whose trigger is satisfied NOW but never previously
    latched. Runtime callers use this list to record fresh latch events
    into the memory store.

    Always-active baseline stages (empty trigger) are excluded: they
    don't need latching because they're on from the start of the
    campaign and writing a latch event for them would just pollute the
    store with redundant records.
    """
    if npc.arc is None:
        return []
    already = _previously_latched_stage_ids(npc.id, store)
    out: list[ActiveStage] = []
    standings = dict(standings or {})
    for i, stage in enumerate(npc.arc.stages):
        if stage.id in already:
            continue
        if _is_always_active(stage.trigger):
            continue
        if _trigger_satisfied(
            stage.trigger, npc, store, standings,
            quest_tracker=quest_tracker, quest_config=quest_config,
        ):
            out.append(ActiveStage(stage=stage, index=i, latched=False))
    return out


def _is_always_active(trigger: TriggerSpec) -> bool:
    """True when the trigger has no structural constraints and no
    custom condition — the stage is on from campaign start."""
    return (
        trigger.min_pivotal_events == 0
        and trigger.min_total_events == 0
        and not trigger.required_event_types
        and not trigger.min_standing
        and not trigger.max_standing
        and not trigger.min_quest_stages
        and not trigger.custom_condition.strip()
    )


def record_latch(
    npc: NpcSheet,
    stage: ArcStage,
    store: MemoryStore,
) -> None:
    """Persist a stage latch back to the memory store.

    We record as a ``notable`` event so the store's decay layer doesn't
    prune it (notable means "visible across a long horizon"). Writing
    latches as regular events means the store file remains the single
    source of truth — no separate 'arc progress' JSON to keep in sync.
    """
    store.record(
        npc_id=npc.id,
        event_type=ARC_LATCH_EVENT_TYPE,
        summary=f"arc stage '{stage.id}' latched",
        salience="notable",
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _previously_latched_stage_ids(npc_id: str, store: MemoryStore) -> set[str]:
    """Extract latched-stage ids from the memory store.

    A latch event's summary is ``"arc stage '<id>' latched"`` — we parse
    the id back out instead of reading a separate field so the event
    record stays a simple string (diff-friendly in JSON).
    """
    result: set[str] = set()
    for e in store.events:
        if e.npc_id != npc_id or e.event_type != ARC_LATCH_EVENT_TYPE:
            continue
        # Summary form: "arc stage '<id>' latched". Quote-stripped parse.
        text = e.summary
        marker = "arc stage '"
        i = text.find(marker)
        if i == -1:
            continue
        j = text.find("'", i + len(marker))
        if j == -1:
            continue
        result.add(text[i + len(marker):j])
    return result


def _trigger_satisfied(
    trigger: TriggerSpec,
    npc: NpcSheet,
    store: MemoryStore,
    standings: Mapping[str, float],
    *,
    quest_tracker: QuestTracker | None = None,
    quest_config: QuestsConfig | None = None,
) -> bool:
    """True when every constraint in ``trigger`` holds right now.

    custom_condition is intentionally ignored here — it's a narrative
    instruction for the LLM, not something the runtime can evaluate.
    Callers that want to honour it should surface it to the generator.
    """
    # Collect the events visible to this NPC: direct + faction-shared
    # via either primary or secondary faction slot.
    visible = _visible_events(npc, store)

    if trigger.min_total_events > 0 and len(visible) < trigger.min_total_events:
        return False

    if trigger.min_pivotal_events > 0:
        pivotal = sum(1 for e in visible if e.salience == "pivotal")
        if pivotal < trigger.min_pivotal_events:
            return False

    if trigger.required_event_types:
        seen_types = {e.event_type for e in visible}
        if not set(trigger.required_event_types).issubset(seen_types):
            return False

    for faction_id, floor in trigger.min_standing.items():
        if standings.get(faction_id, 0.0) < floor:
            return False

    for faction_id, ceiling in trigger.max_standing.items():
        if standings.get(faction_id, 0.0) > ceiling:
            return False

    # Quest gates: a missing tracker/config with a non-empty
    # min_quest_stages fails closed — callers need to wire the tracker
    # in for quest-gated arcs to fire.
    if trigger.min_quest_stages:
        if quest_tracker is None or quest_config is None:
            return False
        for quest_id, required_stage in trigger.min_quest_stages.items():
            if not quest_tracker.is_at_or_past(
                quest_id, required_stage, quest_config,
            ):
                return False

    return True


def _visible_events(npc: NpcSheet, store: MemoryStore):
    """Events this NPC 'knows about' for arc-trigger purposes.

    We bypass ``store.for_npc`` here because arc evaluation should
    consider the raw history without decay — you don't forget a
    pivotal betrayal the way you forget small pleasantries. Faction
    events are folded in the same way summarize_for_npc does.
    """
    out = []
    faction_ids = {npc.faction_id, npc.secondary_faction_id}
    faction_ids.discard("")
    for e in store.events:
        if e.event_type == ARC_LATCH_EVENT_TYPE:
            # Arc latches aren't "events the NPC lived through" in the
            # narrative sense — skip them when evaluating new triggers.
            continue
        if e.npc_id == npc.id:
            out.append(e)
        elif e.faction_id and e.faction_id in faction_ids:
            out.append(e)
    return out
