"""NPC memory store (v0.9.0 — memory layer).

Memory events persist across sessions so NPCs can reference what the
player did before. The runtime records events through this store; the
generator / respondent prompt reads a summarised view via
:func:`summarize_for_npc`.

Design in one paragraph:

- Events are plain :class:`~.schemas.MemoryEvent` instances, each tagged
  with an NPC id, a monotonic ``turn`` counter, an event-type string,
  and a short summary sentence. A ``salience`` field drives decay so
  trivial pleasantries get pruned while pivotal moments (betrayals,
  gifts, secrets shared, deaths witnessed) last forever.
- The store is backed by a single JSON file — diff-friendly, easy to
  inspect by hand, and cheap to sync with the Unity runtime's own
  save format (both use schema-aligned record shapes).
- Summarisation renders a plain-text block tuned for prompt injection:
  one line per retained event, sorted most-recent first, capped at a
  sensible number so the context window stays lean.

A separate :func:`summarize_faction_memory` folds in every event
tagged with a faction_id, so "the player insulted a Guildsman" shows up
for every Guild member the next time they meet the player. This is
what makes factions feel like real social groups rather than colour-coded
teams.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .schemas import MemoryEvent, MemorySalience, NpcSheet


# Tuning knobs for decay. Kept as module-level constants so they're
# easy to override in a test / a future player-config knob.
DECAY_HORIZON_TRIVIAL = 3   # keep trivial events within this many turns of "now"
DECAY_HORIZON_NOTABLE = 10  # keep notable events within this many turns of "now"
# pivotal events are kept forever.

DEFAULT_MAX_LINES = 8  # cap on events rendered into a single prompt.


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


@dataclass
class MemoryStore:
    """In-memory collection of :class:`MemoryEvent` with JSON persistence.

    The store is a flat list rather than a per-NPC dict because events
    can be faction-tagged (visible to every faction member). Filtering
    on read is O(events) which is fine — a long-campaign RPG will
    realistically accumulate hundreds, not millions.
    """

    events: list[MemoryEvent] = field(default_factory=list)
    current_turn: int = 0

    # -----------------------------------------------------------------
    # Mutators
    # -----------------------------------------------------------------

    def record(
        self,
        *,
        npc_id: str,
        event_type: str,
        summary: str,
        salience: MemorySalience = "notable",
        faction_id: str = "",
        turn: int | None = None,
    ) -> MemoryEvent:
        """Append a new event. Returns the stored event for chaining / test use.

        If ``turn`` is omitted we use :attr:`current_turn` — callers
        typically bump that once per narrative beat and let every event
        in the beat share the same turn.
        """
        if turn is None:
            turn = self.current_turn
        event = MemoryEvent(
            turn=turn,
            npc_id=npc_id,
            event_type=event_type,
            summary=summary,
            salience=salience,
            faction_id=faction_id,
        )
        self.events.append(event)
        return event

    def advance_turn(self, by: int = 1) -> int:
        """Bump the monotonic turn counter. Returns the new value."""
        self.current_turn += by
        return self.current_turn

    # -----------------------------------------------------------------
    # Queries
    # -----------------------------------------------------------------

    def for_npc(
        self,
        npc_id: str,
        *,
        faction_id: str = "",
        include_decayed: bool = False,
    ) -> list[MemoryEvent]:
        """Every event this NPC should remember, most-recent first.

        Includes:
        - direct events (``event.npc_id == npc_id``), and
        - faction-tagged events matching ``faction_id`` (the NPC's primary
          or secondary faction — caller passes whichever is relevant).

        When ``include_decayed`` is False (default), trivial/notable
        events outside their decay horizon are omitted.
        """
        out: list[MemoryEvent] = []
        for e in self.events:
            if e.npc_id == npc_id:
                out.append(e)
                continue
            if faction_id and e.faction_id == faction_id and e.npc_id != npc_id:
                out.append(e)
        # Sort recency-first.
        out.sort(key=lambda ev: ev.turn, reverse=True)
        if include_decayed:
            return out
        return [e for e in out if _still_salient(e, self.current_turn)]

    def for_faction(self, faction_id: str) -> list[MemoryEvent]:
        """Every event tagged with this faction, most-recent first.

        Used for faction-standing rollups and for the Editor's faction
        inspector. Does NOT apply decay — factions have long memories.
        """
        if not faction_id:
            return []
        out = [e for e in self.events if e.faction_id == faction_id]
        out.sort(key=lambda ev: ev.turn, reverse=True)
        return out

    # -----------------------------------------------------------------
    # Persistence
    # -----------------------------------------------------------------

    def to_json(self, indent: int = 2) -> str:
        payload = {
            "schemaVersion": "1",
            "currentTurn": self.current_turn,
            "events": [e.model_dump() for e in self.events],
        }
        return json.dumps(payload, indent=indent, ensure_ascii=False)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "MemoryStore":
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        events = [MemoryEvent(**e) for e in data.get("events", [])]
        return cls(events=events, current_turn=int(data.get("currentTurn", 0)))


# ---------------------------------------------------------------------------
# Decay predicate
# ---------------------------------------------------------------------------


def _still_salient(event: MemoryEvent, current_turn: int) -> bool:
    """True if the event should still be surfaced at ``current_turn``.

    pivotal = always; notable = DECAY_HORIZON_NOTABLE turns; trivial =
    DECAY_HORIZON_TRIVIAL turns. ``current_turn`` is typically the
    store's own counter — we pass it explicitly so a preview tool
    can ask "how would this look 20 turns from now".
    """
    if event.salience == "pivotal":
        return True
    age = current_turn - event.turn
    if event.salience == "notable":
        return age <= DECAY_HORIZON_NOTABLE
    return age <= DECAY_HORIZON_TRIVIAL


# ---------------------------------------------------------------------------
# Prompt-facing summariser
# ---------------------------------------------------------------------------


def summarize_for_npc(
    npc: NpcSheet,
    store: MemoryStore,
    *,
    max_lines: int = DEFAULT_MAX_LINES,
) -> str:
    """Render this NPC's memory of the player as a prompt block.

    Returns an empty string when there's nothing to remember — callers
    can safely concatenate the result without adding stray headers.
    Feeds NpcSheet.faction_id + secondary_faction_id into the query so
    the NPC sees faction-shared events as well as their own.

    Format:

        Memory of past encounters with the player (most recent first):
        - [turn 12, pivotal] player_lied_about_knowing_kess — the player
          denied knowing Kess, then used his name in the next breath.
        - [turn 9, notable] gift_given — the player offered coin for
          your silence. You kept it; your silence is not yet decided.
        - [turn 3, notable, Guild] faction_helped — the player cleared
          a Guild debt for one of your kin.
    """
    events: list[MemoryEvent] = []
    seen: set[tuple[int, str, str]] = set()
    for fid in (npc.faction_id, npc.secondary_faction_id):
        for e in store.for_npc(npc.id, faction_id=fid):
            key = (e.turn, e.event_type, e.summary)
            if key in seen:
                continue
            seen.add(key)
            events.append(e)
    if not events:
        return ""

    events.sort(key=lambda ev: ev.turn, reverse=True)
    events = events[:max_lines]

    lines = [
        "Memory of past encounters with the player (most recent first). "
        "These are things that actually happened between you and the player "
        "in prior scenes. Reference them naturally when relevant — do not "
        "narrate them or mention turn numbers out loud:"
    ]
    for e in events:
        faction_tag = f", {e.faction_id}" if e.faction_id else ""
        lines.append(
            f"- [turn {e.turn}, {e.salience}{faction_tag}] {e.event_type} — "
            f"{e.summary.strip()}"
        )
    return "\n".join(lines)


def summarize_faction_memory(
    faction_id: str,
    store: MemoryStore,
    *,
    max_lines: int = DEFAULT_MAX_LINES,
) -> str:
    """Render the faction's collective memory of the player.

    Used by scene generators and by the Editor's faction inspector to
    answer "how does this whole faction feel about the player right
    now". Ignores decay — factions have institutional memory.
    """
    events = store.for_faction(faction_id)
    if not events:
        return ""
    events = events[:max_lines]
    lines = [
        f"How the {faction_id} faction remembers the player "
        "(most recent first):"
    ]
    for e in events:
        lines.append(
            f"- [turn {e.turn}, {e.salience}] {e.event_type} — "
            f"{e.summary.strip()}"
        )
    return "\n".join(lines)
