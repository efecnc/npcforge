"""Relationship trajectory — per-NPC curves of named waypoints (v0.17.0).

Each NPC can carry a :class:`~.schemas.RelationshipTrajectory` that
defines their shape:

- Which waypoints they pass through (``stranger → tolerated → trusted
  → confidant → intimate``, or whatever the writer names for that
  NPC's arc);
- The score thresholds at which each waypoint activates;
- How different memory event_types shift the score (per-NPC overrides
  of the module-level defaults);
- An optional per-turn decay rate so goodwill fades without contact.

The evaluator reads the memory store for events directly involving
this NPC (+ faction-shared ones), accumulates the score, and reports
the waypoint currently active. The runtime + generator pipelines
then compose waypoint unlocks with the rest of the context (arc
stages, voice lenses, ethics).

Unlike arc stages, trajectories are NOT latched — the curve can move
backward if the player betrays the NPC after building trust. Writers
who want "once confidant, always confidant" behaviour either set
``min_score`` thresholds high enough to be unreachable once passed
(via decay), or skip the trajectory and use an arc stage instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional

from .memory import MemoryStore
from .schemas import NpcSheet, RelationshipTrajectory, TrajectoryWaypoint


# Module-level default score deltas per event_type. Per-NPC overrides
# extend / replace these via RelationshipTrajectory.event_deltas.
# Designed so one strong gesture moves a neutral NPC ~0.15 of the way
# between waypoints if the waypoints sit one unit apart.
DEFAULT_EVENT_DELTAS: dict[str, float] = {
    # Builds the relationship
    "gift_given": +0.10,
    "offer_help": +0.12,
    "confess_vulnerability": +0.18,
    "secret_shared": +0.25,
    "faction_helped": +0.08,
    "barter": +0.02,

    # Breaks the relationship
    "player_lied": -0.20,
    "threat": -0.15,
    "threaten_for_info": -0.10,
    "intimidate": -0.15,
    "faction_harmed": -0.12,

    # Neutral / situational
    "ask_about_npc_other": +0.01,
    "ask_about_local_events": +0.01,
    "flirt": +0.00,           # the NPC decides; leave neutral by default
    "dramatic_entrance": +0.00,
}


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


@dataclass
class TrajectoryReading:
    """Snapshot of an NPC's current place on their curve."""

    npc_id: str
    score: float
    current: Optional[TrajectoryWaypoint]
    # Next waypoint (if any) — lets UI show "how far until confidant".
    next_waypoint: Optional[TrajectoryWaypoint]
    # Distance to next waypoint (positive = still to go; 0 if at end).
    distance_to_next: float
    # Top events that contributed most (in either direction) — for
    # CLI diagnostics + prompt injection.
    top_events: list[tuple[str, str, float]]


def resolve_event_deltas(
    trajectory: RelationshipTrajectory,
) -> dict[str, float]:
    """Compose the per-NPC override table with the defaults. Per-NPC
    values WIN (replace, not blend) — writers can zero out a default
    effect for a specific NPC by setting it explicitly to 0.0."""
    resolved = dict(DEFAULT_EVENT_DELTAS)
    for event_type, delta in trajectory.event_deltas.items():
        resolved[event_type] = delta
    return resolved


def evaluate_trajectory(
    npc: NpcSheet,
    store: MemoryStore,
    *,
    max_top_events: int = 3,
) -> Optional[TrajectoryReading]:
    """Compute the NPC's current waypoint given the memory store.

    Returns None when the NPC has no trajectory declared — callers
    can treat that as "this NPC doesn't track a relationship arc;
    judge them by other dimensions".

    Scoring:
    - Fold direct + faction-shared events (same logic as
      :func:`npcforge.memory.summarize_for_npc`, but include decayed
      events so deep history still counts).
    - Apply per-event deltas.
    - Apply per-turn decay: (turns_since_event * decay_per_turn)
      subtracted from the absolute value of the delta, clamped so
      decayed events can zero out but not flip sign.
    """
    if npc.trajectory is None:
        return None

    traj = npc.trajectory
    deltas = resolve_event_deltas(traj)
    current_turn = store.current_turn

    # Gather visible events — include decayed so old pivotal events
    # still feed the curve.
    events = store.for_npc(
        npc.id,
        faction_id=npc.faction_id or "",
        include_decayed=True,
    )
    if npc.secondary_faction_id:
        seen = {(e.turn, e.event_type, e.summary) for e in events}
        for e in store.for_npc(
            npc.id,
            faction_id=npc.secondary_faction_id,
            include_decayed=True,
        ):
            key = (e.turn, e.event_type, e.summary)
            if key not in seen:
                events.append(e)
                seen.add(key)

    contributions: list[tuple[str, str, float]] = []
    score = 0.0
    for e in events:
        base = deltas.get(e.event_type)
        if base is None or base == 0.0:
            continue
        # Apply per-turn decay based on how many turns ago this event
        # happened. Decay can reduce the magnitude but cannot flip sign.
        if traj.decay_per_turn > 0.0:
            turns_elapsed = max(0, current_turn - e.turn)
            decay = turns_elapsed * traj.decay_per_turn
            magnitude = max(abs(base) - decay, 0.0)
            contribution = magnitude if base > 0 else -magnitude
        else:
            contribution = base
        if contribution == 0.0:
            continue
        score += contribution
        contributions.append((e.event_type, e.summary, contribution))

    # Find current waypoint — highest whose min_score <= score.
    sorted_waypoints = sorted(traj.waypoints, key=lambda w: w.min_score)
    current: Optional[TrajectoryWaypoint] = None
    next_wp: Optional[TrajectoryWaypoint] = None
    for w in sorted_waypoints:
        if score >= w.min_score:
            current = w
        else:
            next_wp = w
            break
    # If score > all thresholds, we're past the highest waypoint.
    if current is None and sorted_waypoints:
        # Below the lowest — the lowest waypoint is "you haven't even
        # started", callers typically treat that as 'stranger-or-less'.
        current = None
        next_wp = sorted_waypoints[0]

    distance = (next_wp.min_score - score) if next_wp else 0.0
    contributions.sort(key=lambda c: abs(c[2]), reverse=True)

    return TrajectoryReading(
        npc_id=npc.id,
        score=score,
        current=current,
        next_waypoint=next_wp,
        distance_to_next=distance,
        top_events=contributions[:max_top_events],
    )


# ---------------------------------------------------------------------------
# Prompt summariser
# ---------------------------------------------------------------------------


def summarize_trajectory(
    npc: NpcSheet,
    reading: Optional[TrajectoryReading],
) -> str:
    """Render the reading as a prompt block.

    Empty string when the NPC has no trajectory, no current waypoint
    (player is below the lowest), or no events have landed. Callers
    can safely concatenate.
    """
    if reading is None or reading.current is None:
        return ""

    current = reading.current
    lines = [
        f"Relationship trajectory with this player (your private read "
        f"on how close they've come to you; DO NOT narrate the mechanic "
        f"or name the waypoint to them):",
        f"- Current waypoint: {current.label} ({current.id}).",
    ]
    if current.description.strip():
        lines.append(f"    Meaning: {current.description.strip()}")
    if current.voice_shift.strip():
        lines.append(f"    Voice shift (composes with other active shifts): "
                     f"{current.voice_shift.strip()}")
    if current.unlocks_knowledge:
        joined = ", ".join(current.unlocks_knowledge)
        lines.append(
            "    Unlocked knowledge ids (treat the original gate as "
            f"satisfied for these facts): {joined}"
        )
    if reading.next_waypoint is not None:
        lines.append(
            f"- Next waypoint after this: "
            f"{reading.next_waypoint.label} ({reading.next_waypoint.id}), "
            f"would require an additional {reading.distance_to_next:+.2f} score."
        )
    if reading.top_events:
        lines.append("- What moved the trajectory most:")
        for event_type, summary, contribution in reading.top_events:
            sign = "+" if contribution > 0 else "−"
            lines.append(f"    {sign} {event_type} — {summary.strip()}")
    lines.append(
        "Let the current waypoint shape tone — warmth, depth of "
        "disclosure, willingness to meet the player's eyes. Never "
        "say the waypoint name aloud; never narrate the progression."
    )
    return "\n".join(lines)
