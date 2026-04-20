"""Persistent emotional state per NPC (v0.20.0).

Plutchik's eight primary emotions as a running intensity vector. Each
memory event nudges the axes via :data:`DEFAULT_EMOTION_DELTAS`; time-
since-event decays those contributions so stale emotions fade. The
dominant emotion feeds the respondent prompt as a DELIVERY hint, not
as content — the LLM never says "I feel hopeful", it just colours
register accordingly.

Design in one paragraph:

- Emotions are computed **on demand** from the memory store rather
  than persisted separately. The memory store is the single source
  of truth; the emotion state is a derivation of it.
- Polar pairs from Plutchik: joy ↔ sadness, anger ↔ fear,
  trust ↔ disgust, surprise ↔ anticipation. Event deltas often hit
  two polar emotions at once (a betrayal nudges both +disgust and
  -trust; a gift nudges both +joy and +trust).
- Decay scales each event's contribution by
  ``max(base - decay_per_turn × turns_elapsed, 0)``. Old events
  eventually zero out and stop feeding the current state. This keeps
  the emotion realistic ("you're still hurt from yesterday" vs. "a
  pivotal betrayal ten sessions ago shouldn't make you foam today").
- The prompt block surfaces the **dominant emotion** plus a couple
  of secondaries, with a hard guard against narrating the state
  aloud.

Inspired by ereezyy/NPCPersonalitySystem's EmotionState, but
recast as a derived prompt block rather than a separate tick-loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from .memory import MemoryStore
from .schemas import NpcSheet


# Plutchik's eight primary emotions — the academic standard. Order
# below is the canonical Plutchik wheel order (clockwise from joy).
EMOTION_AXES: tuple[str, ...] = (
    "joy", "trust", "fear", "surprise",
    "sadness", "disgust", "anger", "anticipation",
)


# Per-event-type emotion deltas. Magnitudes tuned so a single strong
# event (pivotal betrayal, secret shared) registers as a recognisable
# shift in the dominant emotion; light events contribute but rarely
# flip the state by themselves.
DEFAULT_EMOTION_DELTAS: dict[str, dict[str, float]] = {
    # Hostile
    "player_lied": {"disgust": +0.30, "trust": -0.20, "anger": +0.15},
    "threat": {"fear": +0.40, "anger": +0.30, "trust": -0.15},
    "threaten_for_info": {"fear": +0.20, "anger": +0.20, "trust": -0.10},
    "intimidate": {"fear": +0.30, "anger": +0.20, "trust": -0.10},
    "faction_harmed": {"anger": +0.30, "sadness": +0.15, "trust": -0.15},

    # Honorable / warm
    "gift_given": {"joy": +0.30, "trust": +0.20},
    "offer_help": {"trust": +0.30, "joy": +0.20},
    "confess_vulnerability": {"trust": +0.30, "surprise": +0.15},
    "secret_shared": {"trust": +0.40, "joy": +0.15},
    "faction_helped": {"joy": +0.25, "trust": +0.20},

    # Transactional / neutral
    "barter": {"anticipation": +0.05},

    # Curious / investigative
    "ask_about_npc_other": {"anticipation": +0.10, "surprise": +0.05},
    "ask_about_local_events": {"anticipation": +0.08},
    "ask_about_locket": {"anticipation": +0.15, "surprise": +0.05},

    # Theatrical
    "flirt": {"surprise": +0.15, "joy": +0.10, "anticipation": +0.10},
    "dramatic_entrance": {"surprise": +0.25, "anticipation": +0.10},
}


@dataclass
class EmotionState:
    """Snapshot of an NPC's current emotional intensities."""

    axes: dict[str, float] = field(default_factory=dict)

    def get(self, axis: str) -> float:
        return self.axes.get(axis, 0.0)

    def dominant(self, min_intensity: float = 0.1) -> tuple[str, float] | None:
        """Highest-intensity axis. Returns None when everything is
        below ``min_intensity`` — a quiet NPC shouldn't have a
        dominant emotion labelled."""
        if not self.axes:
            return None
        axis, value = max(self.axes.items(), key=lambda kv: kv[1])
        if value < min_intensity:
            return None
        return axis, value

    def top(
        self, n: int = 3, min_intensity: float = 0.1
    ) -> list[tuple[str, float]]:
        """Top-N axes above threshold, highest first."""
        ranked = sorted(self.axes.items(), key=lambda kv: kv[1], reverse=True)
        return [(a, v) for a, v in ranked if v >= min_intensity][:n]


# ---------------------------------------------------------------------------
# Compute-on-demand from the memory store
# ---------------------------------------------------------------------------


def compute_emotion_state(
    npc: NpcSheet,
    store: MemoryStore,
    *,
    decay_per_turn: float = 0.05,
    deltas: Mapping[str, Mapping[str, float]] | None = None,
) -> EmotionState:
    """Derive the NPC's current emotional state from the memory store.

    Folds in direct events + faction-shared events (same policy as
    :func:`npcforge.memory.summarize_for_npc`, but includes decayed
    events so we can apply our own per-turn decay). Each event's
    contribution is scaled by ``max(base - decay_per_turn ×
    turns_elapsed, 0)`` — old events zero out gradually; sign is
    preserved until magnitude hits zero, at which point the axis
    drops out of the sum.

    Per-axis intensity is clamped to [0, 1].
    """
    deltas_table = deltas if deltas is not None else DEFAULT_EMOTION_DELTAS

    # Visible events: direct + faction-shared across primary + secondary
    # faction slots. Include decayed so deep history isn't lost.
    visible = store.for_npc(
        npc.id,
        faction_id=npc.faction_id or "",
        include_decayed=True,
    )
    if npc.secondary_faction_id:
        seen = {(e.turn, e.event_type, e.summary) for e in visible}
        for e in store.for_npc(
            npc.id,
            faction_id=npc.secondary_faction_id,
            include_decayed=True,
        ):
            key = (e.turn, e.event_type, e.summary)
            if key not in seen:
                visible.append(e)
                seen.add(key)

    axes: dict[str, float] = {}
    current_turn = store.current_turn
    for e in visible:
        event_deltas = deltas_table.get(e.event_type)
        if not event_deltas:
            continue
        turns_elapsed = max(0, current_turn - e.turn)
        for emotion, base in event_deltas.items():
            if base == 0.0:
                continue
            if decay_per_turn > 0.0:
                magnitude = max(abs(base) - decay_per_turn * turns_elapsed, 0.0)
                contribution = magnitude if base > 0 else -magnitude
            else:
                contribution = base
            if contribution == 0.0:
                continue
            axes[emotion] = axes.get(emotion, 0.0) + contribution

    # Clamp to [0, 1] per axis. Negative contributions zero out —
    # you're not 'negatively joyous', just 'not joyous'.
    clamped = {a: max(0.0, min(1.0, v)) for a, v in axes.items()}
    # Drop zeros so the prompt block stays tight.
    clamped = {a: v for a, v in clamped.items() if v > 0.0}
    return EmotionState(axes=clamped)


# ---------------------------------------------------------------------------
# Prompt summariser
# ---------------------------------------------------------------------------


def summarize_emotion_state(
    state: EmotionState,
    *,
    max_axes: int = 3,
    min_intensity: float = 0.1,
) -> str:
    """Render the current emotional state as a prompt block.

    Empty string when nothing crosses ``min_intensity`` — a calm NPC
    gets no extra prompt weight.
    """
    top = state.top(n=max_axes, min_intensity=min_intensity)
    if not top:
        return ""
    lines = [
        "Current emotional state (YOUR internal feeling — shape "
        "DELIVERY, never narrate or name the emotion aloud):"
    ]
    for axis, intensity in top:
        lines.append(f"- {axis}: {intensity:.2f}")
    dominant = top[0][0]
    lines.append(
        f"Dominant tone: {dominant}. Let this colour pacing, warmth, "
        "and word choice. Do not say 'I feel {axis}' — let the feeling "
        "surface naturally in register. A trust-dominant character is "
        "slower to deflect; a fear-dominant character is clipped and "
        "watchful; an anticipation-dominant character leans forward in "
        "their next question."
    )
    return "\n".join(lines)
