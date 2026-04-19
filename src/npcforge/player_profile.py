"""Player behavioural model (v0.13.0 — player modeling).

Over many interactions the system watches *how* the player talks, not
just what they say. Event types recorded by :mod:`npcforge.memory`
nudge axes on a :class:`PlayerProfile` — aggressive / patient /
deceptive / curious / theatrical / loyal — with simple weighted
clamp-to-[0,1] accumulation.

Only NPCs flagged ``observes_player = True`` on their character sheet
see the profile block in their respondent prompt. The pattern is
deliberate: most NPCs react to the immediate moment; the few
"observer" characters are the ones who notice recurring behaviour and
call the player on it. Designers pick who gets the privilege.

Design notes:

- Axes are open-set strings so writers can add new dimensions
  ('scholarly', 'penitent') by editing the axis_deltas map.
- Deltas are symmetric in structure: one event_type nudges one or more
  axes by configurable weights. The default mapping is opinionated but
  each project can override via ``axis_deltas`` kwarg on the updater.
- Decay is OFF by default because memory events already decay (see
  memory.py); double-decaying would wipe observations too fast.
  Projects that want a moving-average feel can pass ``decay_rate``.
- Values clamp to [0, 1]; negative events decrement (e.g. the player
  lying to a trusting NPC nudges 'loyal' down).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from pydantic import BaseModel, Field


# Default mapping from event_type → {axis: delta}. Designed to be
# non-negative for the axes directly-earned-by-behaviour (aggressive,
# curious, theatrical) and to apply negative nudges to inverse axes
# (faction_harmed pulls 'loyal' down).
DEFAULT_AXIS_DELTAS: dict[str, dict[str, float]] = {
    # Hostile / aggressive signals
    "threat": {"aggressive": +0.20},
    "threaten_for_info": {"aggressive": +0.15, "curious": +0.05},
    "intimidate": {"aggressive": +0.15},
    "faction_harmed": {"aggressive": +0.10, "loyal": -0.10},
    "player_lied": {"deceptive": +0.15, "loyal": -0.05},

    # Patient / generous signals
    "gift_given": {"patient": +0.10, "loyal": +0.05},
    "barter": {"patient": +0.05},
    "offer_help": {"patient": +0.10},
    "confess_vulnerability": {"patient": +0.10, "theatrical": +0.05},
    "secret_shared": {"patient": +0.10, "loyal": +0.10},

    # Loyal / faction signals
    "faction_helped": {"loyal": +0.15},

    # Curious / investigative signals
    "ask_about_npc_other": {"curious": +0.10},
    "improv_query": {"curious": +0.05},
    "ask_about_local_events": {"curious": +0.05},
    "ask_about_locket": {"curious": +0.10},

    # Theatrical / performative signals
    "flirt": {"theatrical": +0.15},
    "dramatic_entrance": {"theatrical": +0.15},
}


# Axes the summariser knows how to describe in prose. Open-set — writers
# can add labels for new axes. The summariser falls back to "tends to
# be <axis>" for unknown axes so no crash.
_AXIS_PROSE: dict[str, str] = {
    "aggressive": "takes the aggressive line with you — pressure, not persuasion",
    "patient": "tends to approach patiently — gifts, listening, time",
    "deceptive": "lies to you when it suits them",
    "curious": "asks more than they're asked — probes",
    "theatrical": "plays up the drama when they speak",
    "loyal": "has backed the people you've asked them to back",
    "disloyal": "has stepped away from the people you trusted them with",
}


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class PlayerProfile(BaseModel):
    """Running model of the player's conversational behaviour.

    Persisted to ``<demo-dir>/player_profile.json`` alongside the memory
    store. Kept separate (not a field on MemoryStore) because the
    profile is a *derivation* of events, not an event log — the memory
    store stays the source of truth.
    """

    schema_version: str = Field(default="1")
    updated_at_turn: int = Field(
        default=0,
        description="Last memory-store turn this profile was updated against.",
    )
    axes: dict[str, float] = Field(
        default_factory=dict,
        description="Per-axis weight in [0, 1]. Missing axis = 0.",
    )

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get(self, axis: str) -> float:
        return self.axes.get(axis, 0.0)

    def top_traits(
        self, n: int = 3, min_weight: float = 0.2
    ) -> list[tuple[str, float]]:
        """Most-weighted axes above ``min_weight``, highest first."""
        ranked = sorted(self.axes.items(), key=lambda kv: kv[1], reverse=True)
        return [(k, v) for k, v in ranked if v >= min_weight][:n]

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def to_json(self, indent: int = 2) -> str:
        return self.model_dump_json(indent=indent)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "PlayerProfile":
        if not path.exists():
            return cls()
        return cls.model_validate_json(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Mutation
# ---------------------------------------------------------------------------


def apply_event(
    profile: PlayerProfile,
    event_type: str,
    *,
    axis_deltas: dict[str, dict[str, float]] | None = None,
    decay_rate: float = 0.0,
    turn: int | None = None,
) -> PlayerProfile:
    """Nudge ``profile`` in place based on one event type.

    ``axis_deltas`` defaults to :data:`DEFAULT_AXIS_DELTAS`. Pass a
    project-specific map to override (union or replace; we don't merge).
    Events with no entry in the map are silent no-ops so the memory
    store can record any event_type without breaking the profile.

    ``decay_rate`` (0..1) scales existing axes down BEFORE applying
    the delta. 0 = no decay (recommended default; memory store already
    decays). Non-zero produces a moving-average feel where old
    observations fade.

    ``turn`` (optional) stamps ``updated_at_turn``. When omitted we
    leave the field untouched — callers bump it explicitly when they
    want.
    """
    deltas = (axis_deltas or DEFAULT_AXIS_DELTAS).get(event_type)
    if deltas is None:
        return profile

    if decay_rate > 0.0:
        factor = 1.0 - decay_rate
        profile.axes = {k: max(0.0, v * factor) for k, v in profile.axes.items()}

    for axis, delta in deltas.items():
        new_val = profile.axes.get(axis, 0.0) + delta
        profile.axes[axis] = max(0.0, min(1.0, new_val))

    if turn is not None:
        profile.updated_at_turn = max(profile.updated_at_turn, turn)
    return profile


def rebuild_from_store(
    store_events: list,
    *,
    axis_deltas: dict[str, dict[str, float]] | None = None,
    decay_rate: float = 0.0,
) -> PlayerProfile:
    """Rebuild a profile from a memory store's full event list.

    Useful when writers edit the delta map mid-campaign — regenerate
    the profile against the mapped event_types instead of migrating
    the stored weights. ``store_events`` accepts either a list of
    :class:`~.schemas.MemoryEvent` or a list of dicts with 'event_type'
    and 'turn' keys (pipeline-agnostic).
    """
    profile = PlayerProfile()
    for e in store_events:
        event_type = getattr(e, "event_type", None) or e.get("event_type")
        turn = getattr(e, "turn", None) or e.get("turn", 0)
        if not event_type:
            continue
        apply_event(
            profile, event_type,
            axis_deltas=axis_deltas,
            decay_rate=decay_rate,
            turn=turn,
        )
    return profile


# ---------------------------------------------------------------------------
# Observer summariser
# ---------------------------------------------------------------------------


def summarize_for_observer(
    profile: PlayerProfile,
    *,
    max_traits: int = 3,
    min_weight: float = 0.25,
) -> str:
    """Render the profile as a prompt block for observer NPCs.

    Returns an empty string when the profile has no traits above
    ``min_weight`` — observer NPCs with no pattern to notice simply
    don't get the block, and behave like any other NPC. This is what
    prevents them from narrating an empty cloud on the first encounter.
    """
    traits = profile.top_traits(n=max_traits, min_weight=min_weight)
    if not traits:
        return ""

    lines = [
        "Player pattern (observed across prior encounters; you notice these "
        "things about them because your role asks it of you):"
    ]
    for axis, weight in traits:
        prose = _AXIS_PROSE.get(axis, f"tends to be {axis}")
        # Round the weight to 1 decimal so the LLM sees a signal, not
        # a precise number to quote back at the player.
        lines.append(f"- {axis} ({weight:.1f}): {prose}")
    lines.append(
        "Reference the pattern only if it fits naturally. Do not list "
        "traits, do not quote numbers, and do not perform-the-observation."
    )
    return "\n".join(lines)
