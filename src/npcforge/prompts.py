"""Prompt builders: NPC sheet, respondent prompts (walk-up + bark), intent rendering.

v0.2.0 injects voice-ceiling constraints (vocabulary ceiling, forbidden
words, accent markers) directly into the NPC respondent prompt so the
LLM has a hard frame before sampling.
"""

from __future__ import annotations

from .schemas import (
    BarkTrigger,
    Faction,
    FactionsConfig,
    NpcSheet,
    Personality,
    PlayerIntent,
    VocabularyCeiling,
    VoiceLens,
)
from .arcs import ActiveStage


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


def _render_relationships(
    npc: NpcSheet,
    cast: list[NpcSheet] | None = None,
) -> str:
    """Render the relationships block, anchoring each target NPC in their
    declared role when the cast is supplied.

    The cast-aware form fixes a v0.8.0 failure mode where the LLM
    substituted generic priors ("dwarves are blacksmiths") for the actual
    world-bible role when asked about another NPC. Embedding the role
    next to the opinion gives the LLM no room to invent.
    """
    if not npc.relationships:
        return ""
    by_id: dict[str, NpcSheet] = {}
    if cast:
        by_id = {n.id: n for n in cast}

    lines = ["Relationships with other characters:"]
    for r in npc.relationships:
        target = by_id.get(r.npc_id)
        if target is not None:
            header = f"- {r.npc_id} ({target.name}, {target.role}): {r.opinion.strip()}"
        else:
            header = f"- {r.npc_id}: {r.opinion.strip()}"
        lines.append(header)
        if r.reason:
            lines.append(f"    Why: {r.reason.strip()}")
    return "\n".join(lines)


def _render_faction_affiliation(
    npc: NpcSheet,
    factions: FactionsConfig | None = None,
) -> str:
    """Render the NPC's faction membership block.

    We resolve the id against ``factions`` so the respondent prompt sees
    the display name + description + values + symbols + allies / rivals
    inline. Without the config, we fall back to emitting just the id —
    still useful (the LLM can at least reference it consistently) but
    much less grounded.
    """
    if not npc.faction_id and not npc.secondary_faction_id:
        return ""

    by_id: dict[str, Faction] = {}
    if factions is not None:
        by_id = {f.id: f for f in factions.factions}

    def render_one(slot_label: str, faction_id: str) -> list[str]:
        f = by_id.get(faction_id)
        if f is None:
            return [f"{slot_label}: {faction_id} (details not loaded)"]
        block = [f"{slot_label}: {f.name} ({f.id})"]
        if f.description:
            block.append(f"    About: {f.description.strip()}")
        if f.values:
            block.append("    Values: " + ", ".join(f.values))
        if f.symbols:
            block.append("    Visible markers: " + "; ".join(f.symbols))
        if f.allies:
            block.append("    Allied factions: " + ", ".join(f.allies))
        if f.rivals:
            block.append("    Rival factions: " + ", ".join(f.rivals))
        return block

    lines: list[str] = ["Faction affiliation (shapes how you speak to whom):"]
    if npc.faction_id:
        lines.extend(render_one("Primary", npc.faction_id))
    if npc.secondary_faction_id:
        lines.extend(render_one("Secondary", npc.secondary_faction_id))
    return "\n".join(lines)


_OCEAN_PROSE: dict[tuple[str, str], str] = {
    ("openness", "high"): (
        "entertains strange ideas and speculative claims; willing to "
        "follow a line of thought wherever it goes"
    ),
    ("openness", "low"): (
        "pragmatic and grounded; dismisses abstractions and 'what if' "
        "lines of thought"
    ),
    ("conscientiousness", "high"): (
        "precise in speech, plans ahead, rarely forgets a detail once "
        "spoken; finishes sentences"
    ),
    ("conscientiousness", "low"): (
        "impulsive, casual in speech, drops threads mid-sentence, does "
        "not notice when a promise goes unkept"
    ),
    ("extraversion", "high"): (
        "chatty; volunteers information without being asked; opens "
        "follow-up questions; pace is energetic"
    ),
    ("extraversion", "low"): (
        "terse; waits to be asked; closes conversations early; pace is "
        "slow and spare"
    ),
    ("agreeableness", "high"): (
        "warm toward the person in front of them; cooperative; softens "
        "hard news with phrasing"
    ),
    ("agreeableness", "low"): (
        "blunt; does not soften; confrontational when pressed; willing "
        "to disagree directly"
    ),
    ("neuroticism", "high"): (
        "emotionally reactive; anger, anxiety, and sadness surface "
        "quickly and show in register"
    ),
    ("neuroticism", "low"): (
        "even-keeled; slow to flinch; emotional shifts are small and "
        "understated"
    ),
}


def _render_personality(personality: Personality | None) -> str:
    """Render OCEAN as a compact register-hint block.

    Returns empty string when personality is None OR sits in the neutral
    band on every axis — a bland NPC gets no extra prompt weight.
    """
    if personality is None:
        return ""
    dominant = personality.dominant_axes()
    if not dominant:
        return ""
    lines = [
        "Personality profile (OCEAN register hints — shape pacing, "
        "warmth, volatility; compose with voice + lenses; never narrate):"
    ]
    for axis, direction in dominant:
        prose = _OCEAN_PROSE.get((axis, direction), f"{direction} {axis}")
        val = personality.axis(axis)
        lines.append(f"- {axis} ({direction}, {val:.2f}): {prose}")
    return "\n".join(lines)


def _render_voice_lenses(lenses: list[VoiceLens]) -> str:
    """Render active voice lenses as a cumulative modifier stack.

    Unioned extra_forbidden_words and extra_accent_markers surface as a
    single block at the bottom so the LLM sees one consolidated rule
    set instead of per-lens rule fragments.
    """
    if not lenses:
        return ""
    lines = [
        "Active voice lenses (situational modifiers; apply every "
        "cadence_shift cumulatively — they compose with your base voice "
        "and with each other, they do not replace anything):"
    ]
    for l in lenses:
        lines.append(f"- {l.kind}: {l.label} ({l.id})")
        lines.append(f"    Cadence shift: {l.cadence_shift.strip()}")
        if l.description.strip():
            lines.append(f"    Note: {l.description.strip()}")

    # Consolidated extra rules at the bottom so the LLM doesn't
    # have to re-read the lens list to honour them.
    extra_forbidden: list[str] = []
    extra_accent: list[str] = []
    for l in lenses:
        extra_forbidden.extend(w for w in l.extra_forbidden_words if w not in extra_forbidden)
        extra_accent.extend(m for m in l.extra_accent_markers if m not in extra_accent)
    if extra_forbidden:
        lines.append(
            "    Extra forbidden words (from active lenses): "
            + ", ".join(f'"{w}"' for w in extra_forbidden)
        )
    if extra_accent:
        lines.append("    Extra accent markers (from active lenses):")
        for m in extra_accent:
            lines.append(f"      - {m}")
    return "\n".join(lines)


def _render_arc_stages(
    stages: list[ActiveStage],
) -> str:
    """Render active arc stages as a cumulative voice-shift stack.

    Stages are listed in the order they were declared. Each stage
    contributes its ``voice_shift`` as a modifier that *stacks* on top
    of earlier stages — later shifts don't replace earlier ones, they
    compose. The block also surfaces each stage's
    ``custom_condition`` (when non-empty) so the LLM can apply
    narrative conditions the runtime can't evaluate structurally.
    """
    if not stages:
        return ""
    lines = [
        "Character arc — currently-active stages (cumulative; each voice "
        "shift applies in addition to earlier ones):"
    ]
    for s in stages:
        tag = " [latched]" if s.latched else ""
        lines.append(f"- Stage {s.index}: {s.stage.label} ({s.stage.id}){tag}")
        lines.append(f"    Voice shift: {s.stage.voice_shift.strip()}")
        if s.stage.unlocks_knowledge:
            joined = ", ".join(s.stage.unlocks_knowledge)
            lines.append(
                f"    Unlocked knowledge ids (treat gate as satisfied): {joined}"
            )
        if s.stage.trigger.custom_condition.strip():
            lines.append(
                "    Narrative condition: "
                + s.stage.trigger.custom_condition.strip()
            )
    return "\n".join(lines)


def _render_state_evolution(npc: NpcSheet) -> str:
    if not npc.state_evolution:
        return ""
    lines = ["State evolution (voice shifts to apply when a trigger is active):"]
    for s in npc.state_evolution:
        lines.append(f"- Trigger: {s.trigger.strip()}")
        lines.append(f"    Voice shift: {s.voice_shift.strip()}")
        if s.description:
            lines.append(f"    Note: {s.description.strip()}")
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


def render_character_sheet(
    npc: NpcSheet,
    cast: list[NpcSheet] | None = None,
    factions: FactionsConfig | None = None,
    arc_stages: list[ActiveStage] | None = None,
) -> str:
    """Flatten an :class:`NpcSheet` into a bible-style text block.

    The result is concatenated with the world bible and passed to the
    afterimage document provider as the NPC's grounding context. When
    ``cast`` is supplied (v0.8.1+), each declared relationship target is
    annotated with that NPC's role from the sheet so the LLM cannot
    substitute generic fantasy priors for the real world-bible role.

    When ``factions`` is supplied (v0.9.0+), the NPC's primary and
    secondary faction memberships get fully expanded (name, values,
    symbols, allies, rivals) so the respondent has the social-graph
    context it needs to shift tone per audience.
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
    personality_block = _render_personality(npc.personality)
    if personality_block:
        sections.append(personality_block)
    faction_block = _render_faction_affiliation(npc, factions=factions)
    if faction_block:
        sections.append(faction_block)
    relationships = _render_relationships(npc, cast=cast)
    if relationships:
        sections.append(relationships)
    knowledge = _render_knowledge(npc)
    if knowledge:
        sections.append(knowledge)
    state_evolution = _render_state_evolution(npc)
    if state_evolution:
        sections.append(state_evolution)
    arc_block = _render_arc_stages(arc_stages or [])
    if arc_block:
        sections.append(arc_block)
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
    "   not on the sheet. When another NPC is mentioned, describe them using the ROLE noted\n"
    "   beside their id (e.g. 'Dwarven miner, sole survivor of the cave-in') — never invent\n"
    "   generic occupations (blacksmith, tinker) that contradict the sheet.\n"
    "8. If the sheet declares structured knowledge with a gate, reveal the fact only when the\n"
    "   gate is clearly met by the player's approach. Otherwise deflect in character using the\n"
    "   tone of the sample deflection lines. Facts without a gate are background you never\n"
    "   volunteer directly.\n"
    "9. If the sheet declares state-evolution voice shifts, apply the shifts whose triggers are\n"
    "   currently active. Treat them as modifiers on your core voice, not replacements.\n"
    "10. If the sheet declares faction affiliation, your tone shifts based on who else is in the\n"
    "    scene. With an ally present: warmer register, code-shared references. With a rival\n"
    "    present: clipped, guarded, or confrontational — per your core voice. Never narrate\n"
    "    the shift; just do it.\n"
    "11. If a 'Memory of past encounters' block is provided, those events actually happened\n"
    "    between you and this specific player in prior scenes. Reference them naturally when\n"
    "    they're relevant to what the player is saying now. Do not list them. Do not mention\n"
    "    turn numbers or event_type tags — those are bookkeeping, not dialogue.\n"
    "12. If a 'Character arc' block lists active stages, apply EVERY listed voice shift\n"
    "    cumulatively. Later stages compose with earlier ones — they do not replace them.\n"
    "    Unlocked knowledge ids override their own gate field (treat the fact as freely\n"
    "    reveal-able if the player's question calls for it). Narrative conditions described\n"
    "    in prose may further gate a stage: apply the shift only when the scene's context\n"
    "    clearly matches. Do not narrate the shift — let it show in word choice and register.\n"
    "13. If a 'Player pattern' block is provided, it describes the player's observed\n"
    "    conversational behaviour across prior scenes. Reference the pattern sparingly and\n"
    "    only when it fits your line. Never list traits, never quote weight numbers, never\n"
    "    perform the observation ('I've been watching you'). Let the recognition leak into\n"
    "    a single line at most: 'You come in here the same way every time, friend.'\n"
    "14. If an 'Active voice lenses' block lists situational modifiers, apply every listed\n"
    "    cadence shift cumulatively. Lenses compose with the base voice AND with each\n"
    "    other — a 'tipsy' + 'with_inspector_present' stack produces loosened-but-clipped\n"
    "    register, not one OR the other. Union the extra forbidden words with the base\n"
    "    ceiling; honour the extra accent markers the same way you honour the base ones.\n"
    "    Never narrate the lens ('drunkenly:') — let it surface in cadence.\n"
    "15. If an 'Ethical reading' block describes your private judgement of the player,\n"
    "    let the VERDICT shape tone — warmer if net approving, cooler if net\n"
    "    disapproving, uneven if mixed. Never narrate the reading, never list the events\n"
    "    that fed it, never lecture or moralise. A withdrawn register, a slower greeting,\n"
    "    a closed-off posture conveyed in word choice — that's what a quiet observer\n"
    "    does when they've seen enough. Do not recite your ethical axes to the player.\n"
    "16. If a 'Relationship trajectory' block names your current waypoint with this\n"
    "    player, let it shape warmth, depth of disclosure, and willingness to meet the\n"
    "    player's eyes. Never say the waypoint name aloud; never narrate the progression\n"
    "    ('we've grown closer' is out). A stranger-waypoint greeting is terse and\n"
    "    boundaried; a confidant-waypoint greeting assumes shared history without naming\n"
    "    it. Knowledge ids listed under the waypoint's unlocks override their own gates.\n"
    "17. If a 'Personality profile' block describes your OCEAN register hints, let them\n"
    "    shape PACING and DELIVERY without replacing your voice. Low extraversion = terse,\n"
    "    slow, fewer volunteered details. High neuroticism = emotions surface quickly.\n"
    "    High conscientiousness = finished sentences, precise phrasing. These are base-\n"
    "    temperament hints, composing with every other active block. Never narrate the\n"
    "    hints, never list axes, never say 'as an extravert' — let them surface in rhythm.\n"
    "18. If a 'Current emotional state' block lists your internal feeling, let the\n"
    "    dominant tone shape DELIVERY — warmth, pacing, word choice — without ever\n"
    "    naming the emotion aloud. Never say 'I feel afraid' or 'I'm angry'; let the\n"
    "    fear show in a clipped watchful register and the anger in edges of word choice.\n"
    "    This is TRANSIENT state (decays between turns) — distinct from the permanent\n"
    "    ethical reading and the stable OCEAN profile.\n"
)


def build_npc_respondent_prompt(
    npc: NpcSheet,
    factions: FactionsConfig | None = None,
    memory_summary: str = "",
    arc_stages: list[ActiveStage] | None = None,
    player_profile_block: str = "",
    active_lenses: list[VoiceLens] | None = None,
    ethical_reading_block: str = "",
    trajectory_block: str = "",
    emotion_block: str = "",
) -> str:
    """System prompt for the Respondent (NPC) side of a walk-up dialog.

    v0.9.0: optional ``factions`` expands the NPC's affiliation into a
    full social-graph block; optional ``memory_summary`` (produced by
    :func:`npcforge.memory.summarize_for_npc`) drops a 'what happened
    before' note into the system prompt. Both hooks are additive —
    existing callers that pass neither keep pre-v0.9 behaviour.
    """
    head = (
        f"You are {npc.name}, an NPC in a game world.\n"
        f"Role: {npc.role}\n"
        f"Voice: {npc.voice.strip()}\n"
    )
    ceiling = _voice_ceiling_block(npc)
    faction_block = _render_faction_affiliation(npc, factions=factions)
    personality_block = _render_personality(npc.personality)
    blocks = [head, _BASE_RULES.rstrip()]
    if personality_block:
        blocks.append(personality_block)
    if faction_block:
        blocks.append(faction_block)
    if ceiling:
        blocks.append(ceiling)
    if memory_summary.strip():
        blocks.append(memory_summary.strip())
    arc_block = _render_arc_stages(arc_stages or [])
    if arc_block:
        blocks.append(arc_block)
    if player_profile_block.strip() and npc.observes_player:
        blocks.append(player_profile_block.strip())
    lens_block = _render_voice_lenses(active_lenses or [])
    if lens_block:
        blocks.append(lens_block)
    if ethical_reading_block.strip():
        blocks.append(ethical_reading_block.strip())
    if trajectory_block.strip():
        blocks.append(trajectory_block.strip())
    if emotion_block.strip():
        blocks.append(emotion_block.strip())
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


def build_line_slot_prompt(
    npc: NpcSheet,
    slot_description: str,
    tag_description: str,
    factions: FactionsConfig | None = None,
) -> str:
    """System prompt for line-bank variant generation (v0.11.0).

    Unlike the full respondent prompt (conversational), this prompt
    targets a single short utterance — one line, in character, tuned
    for a specific gameplay slot and tag combo. Output is plain text
    (not structured JSON) because the batch generator handles N calls
    per combo and a single string is cheaper than a JSON schema.

    ``tag_description`` is the human-readable spelling of the combo
    the generator should honour — e.g. "disposition: trusted. mood:
    grateful. time of day: dusk." The LLM gets the slot purpose and
    the tag profile and returns one line that fits both.
    """
    head = (
        f"You are {npc.name}, an NPC in a game world.\n"
        f"Role: {npc.role}\n"
        f"Voice: {npc.voice.strip()}\n\n"
        f"SLOT: {slot_description.strip()}\n"
        f"CONTEXT: {tag_description.strip() or '(none — produce a context-agnostic line)'}\n"
    )
    rules = (
        "Produce ONE short utterance for this slot, in this context.\n"
        "Constraints:\n"
        "- One sentence, at most 20 words.\n"
        "- First-person dialogue. No narration, no stage directions,\n"
        "  no parentheticals.\n"
        "- Stay fully in this specific character's voice. Honour the\n"
        "  vocabulary ceiling, forbidden words, and speech quirks.\n"
        "- Let the CONTEXT shape register, word choice, and warmth —\n"
        "  but never narrate the shift ('warmly:', 'tiredly:' are\n"
        "  forbidden).\n"
        "- Do not repeat the slot description or any of the tag values\n"
        "  verbatim. The line should sound like speech, not stage\n"
        "  direction.\n"
    )
    faction_block = _render_faction_affiliation(npc, factions=factions)
    ceiling = _voice_ceiling_block(npc)
    blocks = [head, rules.rstrip()]
    if faction_block:
        blocks.append(faction_block)
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
