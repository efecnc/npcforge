"""Prompt builders: NPC character sheet, respondent system prompt, archetype persona."""

from __future__ import annotations

from .schemas import NpcSheet, PlayerArchetype


def render_character_sheet(npc: NpcSheet) -> str:
    """Flatten an :class:`NpcSheet` into a bible-style text block.

    The result is concatenated with the world bible and passed into the
    afterimage document provider as the NPC's grounding context.
    """
    quirks = "\n".join(f"- {q}" for q in npc.speech_quirks)
    motivations = "\n".join(f"- {m}" for m in npc.motivations)
    samples = "\n".join(f'- "{s}"' for s in npc.sample_lines)
    return (
        f"## Character Sheet: {npc.name}\n\n"
        f"Role: {npc.role}\n\n"
        f"Voice: {npc.voice.strip()}\n\n"
        f"Background:\n{npc.background.strip()}\n\n"
        f"Motivations:\n{motivations}\n\n"
        f"Secret (not disclosed to the player directly):\n{npc.secret}\n\n"
        f"Speech quirks:\n{quirks}\n\n"
        f"Sample lines (for tone only):\n{samples}\n"
    )


def build_npc_respondent_prompt(npc: NpcSheet) -> str:
    """System prompt for the Respondent (NPC) side of the afterimage loop.

    Kept short; the full character sheet goes into the grounding document.
    These rules are the hard constraints that should survive long dialogues.
    """
    return (
        f"You are {npc.name}, an NPC in a game world.\n"
        f"Role: {npc.role}\n"
        f"Voice: {npc.voice.strip()}\n\n"
        "Rules:\n"
        "1. Stay fully in character. Never mention the real world, models, or that you are an AI.\n"
        "2. Keep each reply to 1-3 short sentences. Players want playable dialogue, not lectures.\n"
        "3. Speak only in first-person dialogue — no narration, no stage directions, no fourth-wall breaks.\n"
        "4. You know only what a person in your role would plausibly know. If asked about matters outside\n"
        "   that scope, refuse or redirect in-character.\n"
        "5. Your motivations and secret (see context) may color your answers, but you do not disclose the\n"
        "   secret directly. Players must infer it.\n"
        "6. Match the player's energy — friendly, hostile, evasive — but keep your core voice fixed.\n"
    )


def render_player_archetype(archetype: PlayerArchetype) -> str:
    """Flatten a :class:`PlayerArchetype` into a Correspondent persona description."""
    return (
        f"PLAYER ARCHETYPE: {archetype.name} ({archetype.id})\n"
        f"{archetype.description.strip()}\n"
        f"Opening intent: {archetype.opening_intent.strip()}"
    )
