"""Quest / story-state tracking (v0.21.0).

Quests give the generator + the runtime a shared story state to gate
on. Arcs can require "recover_locket is at 'accepted' or beyond";
knowledge reveals can lock behind "investigate_seal is past 'clue_found'";
the respondent prompt tells NPCs which quests the player is currently
holding and what stage those quests are at.

Design in one paragraph:

- Quests are declared once in ``<demo-dir>/quests.yaml`` as an ordered
  list of stages. The :class:`QuestTracker` holds the player's current
  stage id per quest (or None for 'not started'), and persists to JSON
  beside the memory store.
- Stage comparison is by INDEX, not id equality — ``is_at_or_past``
  checks that the current stage's index >= the required stage's index
  in the declared order. This lets gates work regardless of stage
  naming drift.
- The prompt summariser renders only the quests relevant to the NPC
  about to speak (``known_to`` filter + a default-everyone mode),
  preventing quest spoilers from bleeding into conversations that
  shouldn't know.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from .schemas import QuestsConfig, QuestStage


@dataclass
class ActiveQuestState:
    """One quest's current state from the tracker's POV."""

    quest_id: str
    current_stage_id: str
    current_stage_index: int
    is_completed: bool  # true when current stage is the last one


class QuestTracker(BaseModel):
    """Persistable per-quest stage cursor.

    The tracker stores only the current stage id per quest — it does
    NOT store the stage definitions (those live in
    ``QuestsConfig``). Keeps the runtime state small + diff-friendly.
    """

    schema_version: str = Field(default="1")
    current_stages: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Map of quest_id -> current stage_id. Missing quest id = "
            "'not started' (treated as stage-index -1 for gate purposes)."
        ),
    )

    # -----------------------------------------------------------------
    # Mutators
    # -----------------------------------------------------------------

    def set_stage(
        self, quest_id: str, stage_id: str, config: QuestsConfig
    ) -> None:
        """Jump to an explicit stage. Raises if the quest or stage is
        unknown — typos should fail loud."""
        quest = config.by_id(quest_id)
        if quest is None:
            raise KeyError(f"Unknown quest '{quest_id}'")
        if quest.stage_index(stage_id) < 0:
            raise KeyError(
                f"Quest '{quest_id}' has no stage '{stage_id}'"
            )
        self.current_stages[quest_id] = stage_id

    def advance(self, quest_id: str, config: QuestsConfig) -> Optional[str]:
        """Advance to the next stage. Returns the new stage id, or None
        if already at the last stage (or the quest has never been set,
        in which case we set it to the first stage)."""
        quest = config.by_id(quest_id)
        if quest is None:
            raise KeyError(f"Unknown quest '{quest_id}'")
        current = self.current_stages.get(quest_id)
        if current is None:
            new = quest.stages[0].id
            self.current_stages[quest_id] = new
            return new
        idx = quest.stage_index(current)
        if idx >= len(quest.stages) - 1:
            return None
        new = quest.stages[idx + 1].id
        self.current_stages[quest_id] = new
        return new

    # -----------------------------------------------------------------
    # Queries
    # -----------------------------------------------------------------

    def current_stage_id(self, quest_id: str) -> Optional[str]:
        return self.current_stages.get(quest_id)

    def is_at_or_past(
        self, quest_id: str, stage_id: str, config: QuestsConfig
    ) -> bool:
        """True when this quest's current stage's index >= the target's
        index. Missing quest or stage id = False."""
        quest = config.by_id(quest_id)
        if quest is None:
            return False
        current_id = self.current_stages.get(quest_id)
        if current_id is None:
            return False
        current_idx = quest.stage_index(current_id)
        target_idx = quest.stage_index(stage_id)
        if current_idx < 0 or target_idx < 0:
            return False
        return current_idx >= target_idx

    def active_states(
        self, config: QuestsConfig
    ) -> list[ActiveQuestState]:
        """Snapshot every started quest's current state, skipping
        quests that haven't begun."""
        out: list[ActiveQuestState] = []
        for quest in config.quests:
            stage_id = self.current_stages.get(quest.id)
            if stage_id is None:
                continue
            idx = quest.stage_index(stage_id)
            if idx < 0:
                # Config drift — stage was renamed / removed.
                continue
            out.append(ActiveQuestState(
                quest_id=quest.id,
                current_stage_id=stage_id,
                current_stage_index=idx,
                is_completed=(idx == len(quest.stages) - 1),
            ))
        return out

    def stages_visible_to(
        self, npc_id: str, config: QuestsConfig
    ) -> list[tuple[str, QuestStage]]:
        """Which (quest, stage) pairs should this NPC see?

        A stage's ``known_to`` list (if non-empty) filters visibility.
        Empty ``known_to`` = every NPC sees it. Used by the respondent
        summariser so quest spoilers don't leak to the wrong mouths.
        """
        result: list[tuple[str, QuestStage]] = []
        for state in self.active_states(config):
            quest = config.by_id(state.quest_id)
            if quest is None:
                continue
            stage = quest.stages[state.current_stage_index]
            if stage.known_to and npc_id not in stage.known_to:
                continue
            result.append((quest.id, stage))
        return result

    # -----------------------------------------------------------------
    # Persistence
    # -----------------------------------------------------------------

    def to_json(self, indent: int = 2) -> str:
        return self.model_dump_json(indent=indent)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "QuestTracker":
        if not path.exists():
            return cls()
        return cls.model_validate_json(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Prompt summariser
# ---------------------------------------------------------------------------


def summarize_active_quests(
    npc_id: str,
    tracker: QuestTracker,
    config: QuestsConfig,
) -> str:
    """Render the NPC-visible quest block for the respondent prompt.

    Only the quests this NPC should know about (via the ``known_to``
    filter) show up. Empty string when nothing is visible — callers
    concatenate safely without guard clauses.
    """
    visible = tracker.stages_visible_to(npc_id, config)
    if not visible:
        return ""

    lines = [
        "Active quests (what the player is currently holding; reference "
        "them naturally when relevant, never recite the stage id or "
        "quest id aloud):"
    ]
    for quest_id, stage in visible:
        quest = config.by_id(quest_id)
        name = quest.name if quest else quest_id
        lines.append(f"- {name}: {stage.label}")
        if stage.description.strip():
            lines.append(f"    {stage.description.strip()}")
    return "\n".join(lines)
