"""Moral profile + ethical reactions (v0.16.0).

Every player action — recorded as a :class:`~.schemas.MemoryEvent`
with a known ``event_type`` — gets judged through the lens of the NPC
who witnessed or heard about it. The same lie is a deep affront to an
honor-bound NPC, a shrug to a pragmatic one, and a tell to a self-
serving one. This module encodes those judgments:

- :class:`EthicalProfile` — the NPC's hidden ethical stance (a weight
  vector over five axes: honor_bound, pragmatic, self_serving, zealot,
  communal). Authored per-NPC in ``characters.yaml``.
- :data:`DEFAULT_EVENT_JUDGEMENTS` — per-event_type × per-axis delta
  table. ``player_lied`` is -0.30 under honor_bound, +0.10 under
  self_serving, -0.20 under zealot, 0.00 under pragmatic.
- :func:`evaluate_player_against_npc` — weights the NPC's stance by
  the delta table across visible events, returning an
  :class:`EthicalReading` with a per-axis approval score and a short
  list of the events that moved it.

The reading is consumed in two places: the runtime can branch dialog
on it (write a scripted line that only fires when the NPC's approval
is negative on honor_bound), and observer NPCs get the summary as a
prompt block so they can call the player out in-character.

Player approval here is ORTHOGONAL to faction standing. Mira might
like the player's disposition (standing up) AND disapprove of them
ethically (lied to Kess three times). Two channels, two purposes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .memory import MemoryStore
from .schemas import EthicalAxis, EthicalProfile, NpcSheet


# ---------------------------------------------------------------------------
# Default judgment table
# ---------------------------------------------------------------------------


# Per-event_type deltas per axis. Delta > 0 = "this action counts in the
# player's favour from this stance"; delta < 0 = "counts against".
# Magnitudes are tuned so a single strong transgression can move a
# focused (weight >= 0.7) NPC's approval by ~0.3, and a run of them
# can fully flip a neutral NPC.
DEFAULT_EVENT_JUDGEMENTS: dict[str, dict[EthicalAxis, float]] = {
    # Hostile / dishonorable
    "player_lied":        {"honor_bound": -0.30, "pragmatic": +0.00, "self_serving": +0.10, "zealot": -0.20, "communal": -0.10},
    "threat":             {"honor_bound": -0.20, "pragmatic": -0.05, "self_serving": +0.00, "zealot": -0.10, "communal": -0.15},
    "threaten_for_info":  {"honor_bound": -0.15, "pragmatic": +0.05, "self_serving": +0.10, "zealot": -0.05, "communal": -0.10},
    "intimidate":         {"honor_bound": -0.20, "pragmatic": +0.00, "self_serving": +0.05, "zealot": -0.10, "communal": -0.15},
    "faction_harmed":     {"honor_bound": -0.10, "pragmatic": +0.00, "self_serving": +0.05, "zealot": -0.05, "communal": -0.20},

    # Honorable / generous
    "gift_given":         {"honor_bound": +0.15, "pragmatic": +0.00, "self_serving": -0.05, "zealot": +0.00, "communal": +0.20},
    "offer_help":         {"honor_bound": +0.20, "pragmatic": +0.00, "self_serving": -0.05, "zealot": +0.05, "communal": +0.25},
    "confess_vulnerability":
                          {"honor_bound": +0.20, "pragmatic": -0.05, "self_serving": -0.10, "zealot": +0.05, "communal": +0.15},
    "secret_shared":      {"honor_bound": +0.25, "pragmatic": +0.00, "self_serving": -0.05, "zealot": +0.10, "communal": +0.15},
    "faction_helped":     {"honor_bound": +0.15, "pragmatic": +0.00, "self_serving": -0.05, "zealot": +0.05, "communal": +0.25},

    # Transactional / neutral-on-most
    "barter":             {"honor_bound": +0.00, "pragmatic": +0.10, "self_serving": +0.05, "zealot": +0.00, "communal": +0.00},

    # Curious / investigative — zealots approve (pursuit of truth);
    # self-servers vaguely approve (leverage); others neutral.
    "ask_about_npc_other":      {"honor_bound": +0.00, "pragmatic": +0.00, "self_serving": +0.05, "zealot": +0.05, "communal": +0.00},
    "ask_about_local_events":   {"honor_bound": +0.00, "pragmatic": +0.00, "self_serving": +0.00, "zealot": +0.05, "communal": +0.05},

    # Theatrical / performative — pragmatic and honor-bound both
    # slightly wary; self-serving likes the showmanship.
    "flirt":              {"honor_bound": -0.05, "pragmatic": -0.05, "self_serving": +0.10, "zealot": -0.05, "communal": +0.00},
    "dramatic_entrance":  {"honor_bound": -0.05, "pragmatic": -0.05, "self_serving": +0.05, "zealot": +0.00, "communal": +0.00},
}


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


@dataclass
class EthicalReading:
    """One NPC's weighted ethical read on the player.

    ``score`` is the summed (delta × axis_weight) across every event
    the NPC has witnessed (or heard via faction-shared events). Positive
    = net approval on THIS NPC's ethical terms; negative = net
    disapproval. Magnitudes are hard to calibrate without playtesting
    so treat the sign + quadrant as the real signal, not the number.

    ``by_axis`` is the per-axis contribution so the summariser can
    explain WHY the NPC feels how they do.

    ``top_events`` lists the handful of events that contributed most
    to the score (both directions), for prompt injection — the observer
    block cites up to 3 of these to the LLM as "things that moved this
    character's read".
    """

    score: float
    by_axis: dict[str, float]
    top_events: list[tuple[str, str, float]]  # (event_type, summary, delta)


def evaluate_player_against_npc(
    npc: NpcSheet,
    store: MemoryStore,
    *,
    judgement_table: Mapping[str, Mapping[EthicalAxis, float]] | None = None,
    max_top_events: int = 3,
) -> EthicalReading:
    """Compute this NPC's ethical reading of the player.

    Iterates over events visible to this NPC (direct + faction-shared,
    same folding as :func:`npcforge.memory.summarize_for_npc`), weights
    each event's per-axis delta by the NPC's profile, and returns the
    sum. NPCs without an ``ethical_profile`` get a zero reading — the
    caller can treat that as "no ethical stance; this character
    judges on other dimensions".
    """
    profile = npc.ethical_profile
    if profile is None:
        return EthicalReading(score=0.0, by_axis={}, top_events=[])

    judgements = judgement_table or DEFAULT_EVENT_JUDGEMENTS

    # Fold NPC's own events + faction-shared events. We re-use the
    # memory store's for_npc helper but pass include_decayed so old
    # pivotal lies don't evaporate from the NPC's ethical read.
    events = store.for_npc(
        npc.id,
        faction_id=npc.faction_id or "",
        include_decayed=True,
    )
    # Also pull secondary-faction events.
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

    total = 0.0
    by_axis: dict[str, float] = {}
    weighted_events: list[tuple[str, str, float]] = []

    for e in events:
        deltas = judgements.get(e.event_type)
        if deltas is None:
            continue
        event_total = 0.0
        for axis, delta in deltas.items():
            stance = profile.weight(axis)
            if stance == 0.0 or delta == 0.0:
                continue
            contribution = stance * delta
            by_axis[axis] = by_axis.get(axis, 0.0) + contribution
            event_total += contribution
        if event_total != 0.0:
            weighted_events.append((e.event_type, e.summary, event_total))
            total += event_total

    # Sort by absolute contribution so the most impactful events
    # (positive OR negative) rise to the top.
    weighted_events.sort(key=lambda x: abs(x[2]), reverse=True)
    return EthicalReading(
        score=total,
        by_axis=by_axis,
        top_events=weighted_events[:max_top_events],
    )


# ---------------------------------------------------------------------------
# Prompt summariser
# ---------------------------------------------------------------------------


def summarize_ethical_reading(
    npc: NpcSheet,
    reading: EthicalReading,
) -> str:
    """Render the reading as a prompt block for ethical-observer NPCs.

    Returns an empty string when the NPC has no ethical profile, or
    when no judged events have landed yet. Callers can safely append
    the return value without checking.
    """
    if npc.ethical_profile is None:
        return ""
    if not reading.top_events and abs(reading.score) < 0.001:
        return ""

    dominant = npc.ethical_profile.dominant_axes()
    stance_phrase = ", ".join(dominant) if dominant else "(no dominant axis)"
    verdict = (
        "net approving" if reading.score > 0.1 else
        "net disapproving" if reading.score < -0.1 else
        "mixed"
    )

    lines = [
        f"Ethical reading (YOUR private judgement of the player — "
        f"you do not narrate this as a list; you let it shape the "
        f"tone you address them with):",
        f"- Your dominant ethical axes: {stance_phrase}.",
        f"- Net read on the player, weighted by YOUR values: "
        f"{verdict} (score {reading.score:+.2f}).",
    ]
    if reading.top_events:
        lines.append("- What moved the reading (most recent / most weighty first):")
        for event_type, summary, delta in reading.top_events:
            sign = "+" if delta > 0 else "−"
            lines.append(f"    {sign} {event_type} — {summary.strip()}")
    lines.append(
        "React to the player in a way consistent with this reading. "
        "If the reading is disapproving on an axis that matters to you, "
        "let that shape register, not the words — no lectures, no "
        "moralising, no listing of transgressions. A cooler greeting "
        "or an edge of withdrawn warmth is enough."
    )
    return "\n".join(lines)
