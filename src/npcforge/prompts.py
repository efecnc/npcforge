"""Prompt builders: NPC sheet, respondent prompts (walk-up + bark), intent rendering.

v0.2.0 injects voice-ceiling constraints (vocabulary ceiling, forbidden
words, accent markers) directly into the NPC respondent prompt so the
LLM has a hard frame before sampling.
"""

from __future__ import annotations

from .schemas import BarkTrigger, NpcSheet, PlayerIntent, VocabularyCeiling


_CEILING_DESCRIPTIONS: dict[VocabularyCeiling, str] = {
    "grade_3": (
        "Use only words an eight-year-old would know. Short words. No jargon. "
        "Sentences under eight words when possible."
    ),
    "grade_5": (
        "Use plain words a ten-year-old would understand. Avoid specialist "
        "vocabulary. Keep sentences short and concrete."
    ),
    "grade_8": (
        "Use everyday vocabulary. Avoid academic, legal, or scholarly words. "
        "No Latinate synonyms when a plain word exists."
    ),
    "high_school": (
        "Use vocabulary appropriate to a high-school-educated adult. No "
        "technical jargon outside the character's stated expertise."
    ),
    "college": (
        "Educated adult vocabulary is fine. Technical jargon only where the "
        "character's role justifies it."
    ),
    "academic": (
        "Any vocabulary is acceptable. Formal register welcome where the "
        "character's role justifies it."
    ),
}


def _voice_ceiling_block(npc: NpcSheet) -> str:
    """Return the voice-ceiling rules as a formatted block, or empty string."""
    parts: list[str] = []

    if npc.vocabulary_ceiling is not None:
        rule = _CEILING_DESCRIPTIONS.get(npc.vocabulary_ceiling, "")
        parts.append(f"VOCABULARY CEILING ({npc.vocabulary_ceiling}): {rule}")

    if npc.forbidden_words:
        joined = ", ".join(f'"{w}"' for w in npc.forbidden_words)
        parts.append(
            f"FORBIDDEN WORDS (never use, not even inflected forms): {joined}"
        )

    if npc.accent_markers:
        markers = "\n".join(f"  - {m}" for m in npc.accent_markers)
        parts.append(f"ACCENT / SPEECH MARKERS (use naturally):\n{markers}")

    if not parts:
        return ""
    return "VOICE CONSTRAINTS (hard rules):\n" + "\n\n".join(parts)


def _render_relationships(npc: NpcSheet) -> str:
    if not npc.relationships:
        return ""
    lines = ["Relationships with other characters:"]
    for r in npc.relationships:
        tail = f" — {r.reason.strip()}" if r.reason else ""
        lines.append(f"- {r.npc_id}: {r.opinion.strip()}{tail}")
    return "\n".join(lines)


def _render_knowledge(npc: NpcSheet) -> str:
    if not npc.knowledge:
        return ""
    out: list[str] = ["Knowledge (structured reveals):"]
    for k in npc.knowledge:
        out.append(f"- {k.id}: {k.fact.strip()}")
        if k.gate:
            out.append(f"    Gate: {k.gate.strip()}")
        if k.reveal_lines:
            samples = "; ".join(f'"{s.strip()}"' for s in k.reveal_lines if s.strip())
            if samples:
                out.append(f"    Sample reveal lines (tone only): {samples}")
        if k.deflect_lines:
            samples = "; ".join(f'"{s.strip()}"' for s in k.deflect_lines if s.strip())
            if samples:
                out.append(f"    Sample deflection lines (tone only): {samples}")
    return "\n".join(out)


def render_character_sheet(npc: NpcSheet) -> str:
    """Flatten an :class:`NpcSheet` into a bible-style text block.

    The result is concatenated with the world bible and passed to the
    afterimage document provider as the NPC's grounding context. v0.8+
    surfaces relationships and structured knowledge when present.
    """
    quirks = "\n".join(f"- {q}" for q in npc.speech_quirks) or "(none)"
    motivations = "\n".join(f"- {m}" for m in npc.motivations) or "(none)"
    samples = "\n".join(f'- "{s}"' for s in npc.sample_lines) or "(none)"

    sections = [
        f"## Character Sheet: {npc.name}",
        f"Role: {npc.role}",
        f"Voice: {npc.voice.strip()}",
        f"Background:\n{npc.background.strip() or '(none)'}",
        f"Motivations:\n{motivations}",
        f"Secret (never disclose directly):\n{npc.secret or '(none)'}",
        f"Speech quirks:\n{quirks}",
        f"Sample lines (for tone only):\n{samples}",
    ]
    relationships = _render_relationships(npc)
    if relationships:
        sections.append(relationships)
    knowledge = _render_knowledge(npc)
    if knowledge:
        sections.append(knowledge)
    return "\n\n".join(sections) + "\n"


_BASE_RULES = (
    "Rules:\n"
    "1. Stay fully in character. Never mention the real world, models, or that you are an AI.\n"
    "2. Keep each reply to 1-3 short sentences. Players want playable dialogue, not lectures.\n"
    "3. Speak only in first-person dialogue — no narration, no stage directions, no fourth-wall breaks.\n"
    "4. You know only what a person in your role would plausibly know. If asked about matters outside\n"
    "   that scope, refuse or redirect in-character.\n"
    "5. Your motivations and secret may color your answers, but you do not disclose the secret directly.\n"
    "   Players must infer it.\n"
    "6. Match the player's energy — friendly, hostile, evasive — but keep your core voice fixed.\n"
    "7. If the sheet declares relationships with other characters, your lines may reference those\n"
    "   NPCs with the stated opinion when the topic arises. Do not invent relationships that are\n"
    "   not on the sheet.\n"
    "8. If the sheet declares structured knowledge with a gate, reveal the fact only when the\n"
    "   gate is clearly met by the player's approach. Otherwise deflect in character using the\n"
    "   tone of the sample deflection lines. Facts without a gate are background you never\n"
    "   volunteer directly.\n"
)


def build_npc_respondent_prompt(npc: NpcSheet) -> str:
    """System prompt for the Respondent (NPC) side of a walk-up dialog."""
    head = (
        f"You are {npc.name}, an NPC in a game world.\n"
        f"Role: {npc.role}\n"
        f"Voice: {npc.voice.strip()}\n"
    )
    ceiling = _voice_ceiling_block(npc)
    blocks = [head, _BASE_RULES.rstrip()]
    if ceiling:
        blocks.append(ceiling)
    return "\n\n".join(blocks) + "\n"


def build_bark_respondent_prompt(npc: NpcSheet, trigger: BarkTrigger) -> str:
    """System prompt for bark generation (one-shot structured output).

    Barks are 1-2 line reactive utterances — combat shouts, ambient
    muttering, reactions to a witnessed event. Kept tight: no dialogue
    follow-up, no narration, character-voice-pure.
    """
    head = (
        f"You are {npc.name}, an NPC in a game world.\n"
        f"Role: {npc.role}\n"
        f"Voice: {npc.voice.strip()}\n\n"
        f"TRIGGER: {trigger.description.strip()}\n"
    )
    rules = (
        "Emit ONE short utterance (a 'bark') that this NPC would say in the\n"
        "trigger situation. Constraints:\n"
        "- One sentence. Maximum 18 words.\n"
        "- First-person only. No narration, no stage directions.\n"
        "- Must sound like this specific character, not a generic NPC.\n"
        "- No fourth-wall breaks. No reference to the player unless the\n"
        "  trigger explicitly involves them.\n"
    )
    ceiling = _voice_ceiling_block(npc)
    blocks = [head, rules.rstrip()]
    if ceiling:
        blocks.append(ceiling)
    return "\n\n".join(blocks) + "\n"


def build_repeat_greeting_prompt(
    npc: NpcSheet, visit_index: int, n_total: int, is_else: bool
) -> str:
    """System prompt for ONE visit-count-gated greeting variant.

    ``visit_index`` is 0-based. ``is_else`` is true for the trailing
    fallback variant ("on every subsequent visit").
    """
    if is_else:
        situation = (
            "The player has now approached you for at least the "
            f"{n_total}-th time (and every time after that). They are a "
            "regular. Acknowledge the relationship without ceremony."
        )
    elif visit_index == 0:
        situation = (
            "This is the FIRST time this player has approached you. They "
            "are a stranger. Greet them as you would any unknown arrival."
        )
    elif visit_index == 1:
        situation = (
            "This is the SECOND time this player has approached you. "
            "Some mild recognition is appropriate — a comment that you've "
            "seen them before."
        )
    else:
        situation = (
            f"This is visit number {visit_index + 1}. The player is "
            "becoming a familiar face. Your greeting should reflect "
            "growing familiarity without resetting to first-meet tone."
        )

    head = (
        f"You are {npc.name}, an NPC in a game world.\n"
        f"Role: {npc.role}\n"
        f"Voice: {npc.voice.strip()}\n\n"
        f"SITUATION: {situation}\n"
    )
    rules = (
        "Produce ONE greeting line the NPC would give in this situation.\n"
        "Constraints:\n"
        "- One sentence, at most 18 words.\n"
        "- Stay fully in character. First-person dialogue only.\n"
        "- Do not reference the visit number directly ('this is your "
        "fourth time' breaks immersion). Signal familiarity through tone.\n"
        "- No narration, no stage directions, no meta references.\n"
    )
    ceiling = _voice_ceiling_block(npc)
    blocks = [head, rules.rstrip()]
    if ceiling:
        blocks.append(ceiling)
    return "\n\n".join(blocks) + "\n"


def build_time_of_day_greeting_prompt(npc: NpcSheet, time_value: str) -> str:
    """System prompt for generating ONE time-of-day greeting variant.

    Generation pattern: one LLM call per (NPC, time_value). The caller
    injects world profile and variable declarations in the user message.
    """
    head = (
        f"You are {npc.name}, an NPC in a game world.\n"
        f"Role: {npc.role}\n"
        f"Voice: {npc.voice.strip()}\n\n"
        f"TIME OF DAY: {time_value}\n"
    )
    rules = (
        "Produce ONE short greeting you would give to someone who walks up to\n"
        "you at this specific time of day. Constraints:\n"
        "- One sentence, at most 18 words.\n"
        "- Reference the time of day explicitly or by strong implication\n"
        "  (e.g. 'Kitchen's closed, friend' for night; 'Sun's already high'\n"
        "  for afternoon). Never say the variable name.\n"
        "- Stay fully in character. First-person dialogue only.\n"
        "- No narration, no stage directions, no meta references.\n"
    )
    ceiling = _voice_ceiling_block(npc)
    blocks = [head, rules.rstrip()]
    if ceiling:
        blocks.append(ceiling)
    return "\n\n".join(blocks) + "\n"


def render_player_intent(intent: PlayerIntent) -> str:
    """Flatten a :class:`PlayerIntent` into a Correspondent persona description."""
    return (
        f"PLAYER INTENT: {intent.name} ({intent.id})\n"
        f"{intent.description.strip()}\n"
        f"Opening intent: {intent.opening_intent.strip() or '(approach the NPC with this intent)'}"
    )
