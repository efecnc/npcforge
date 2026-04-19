"""Tests for v0.12.0 lore-consistent improvisation.

Retrieval + prompt assembly are deterministic; LLM calls are tested
via live integration elsewhere. These cases cover the pure-Python
layer: split, score, prompt-block inclusion.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from npcforge.improv import (
    ImprovReply,
    LoreChunk,
    build_improv_system_prompt,
    retrieve_lore_chunks,
    split_into_chunks,
)
from npcforge.memory import MemoryStore
from npcforge.schemas import (
    Faction,
    FactionsConfig,
    KnowledgeItem,
    NpcSheet,
)


def _tavernkeeper_with_knowledge() -> NpcSheet:
    return NpcSheet(
        id="mira", name="Mira", role="tavernkeeper", voice="gruff",
        knowledge=[
            KnowledgeItem(
                id="the_well",
                fact="The well behind the Lantern predates the town.",
                gate="only when the player mentions the Moon Court",
                reveal_lines=["Older than anything here, friend."],
                deflect_lines=["Some wells are just wells."],
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Split / chunking
# ---------------------------------------------------------------------------


class TestChunking:
    def test_splits_on_blank_lines(self):
        text = "Alpha paragraph.\n\nBeta paragraph.\n\n\nGamma paragraph."
        chunks = split_into_chunks(text)
        assert [c.text for c in chunks] == [
            "Alpha paragraph.",
            "Beta paragraph.",
            "Gamma paragraph.",
        ]
        assert [c.source for c in chunks] == ["lore#p0", "lore#p1", "lore#p2"]

    def test_skips_whitespace_only_paragraphs(self):
        text = "A\n\n   \n\nB\n\n\t\n\nC"
        chunks = split_into_chunks(text)
        assert [c.text for c in chunks] == ["A", "B", "C"]

    def test_handles_crlf_line_endings(self):
        text = "A\r\n\r\nB"
        chunks = split_into_chunks(text)
        assert [c.text for c in chunks] == ["A", "B"]

    def test_empty_input_returns_empty(self):
        assert split_into_chunks("") == []
        assert split_into_chunks("    \n\n\t\n") == []


# ---------------------------------------------------------------------------
# Retrieval scoring
# ---------------------------------------------------------------------------


class TestRetrieval:
    def test_matches_specific_term_ranks_relevant_chunk_first(self):
        bundle = (
            "The Rusted Lantern is a quiet tavern on the town square.\n\n"
            "The Forgetting was a century of silence in the Greywild.\n\n"
            "Emberfall sits at the edge of the old roads."
        )
        results = retrieve_lore_chunks("what is the Forgetting?", bundle, top_k=2)
        assert results[0].text.startswith("The Forgetting")
        # Score should be positive for a hit.
        assert results[0].score > 0

    def test_idf_prefers_rare_terms(self):
        # 'town' appears in every chunk (common), 'Emberfall' in one
        # (rare). Query both — rarity should bias toward the Emberfall
        # chunk over any other.
        bundle = (
            "This town keeps its own time.\n\n"
            "Another town down the road is larger.\n\n"
            "Our town has Emberfall in its name."
        )
        results = retrieve_lore_chunks("Emberfall town", bundle, top_k=1)
        assert "Emberfall" in results[0].text

    def test_novel_query_tokens_fall_back_to_first_chunks(self):
        bundle = "Alpha.\n\nBeta.\n\nGamma."
        results = retrieve_lore_chunks("xyzzy nothing", bundle, top_k=2)
        assert [c.text for c in results] == ["Alpha.", "Beta."]

    def test_stopwords_dropped_from_query(self):
        bundle = "Alpha widget. Beta cog."
        # The entire query is stopwords — would otherwise 'match' any
        # chunk. The fallback path must kick in instead.
        results = retrieve_lore_chunks("what is the a", bundle, top_k=2)
        assert len(results) >= 1

    def test_empty_bundle_returns_empty(self):
        assert retrieve_lore_chunks("anything", "") == []


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------


class TestPromptAssembly:
    def test_prompt_embeds_retrieved_snippets_with_source_tags(self):
        npc = _tavernkeeper_with_knowledge()
        chunks = [
            LoreChunk(text="The Forgetting was a century of silence.",
                      source="lore#p7", score=2.3),
            LoreChunk(text="Emberfall sits on the old roads.",
                      source="lore#p3", score=1.1),
        ]
        prompt = build_improv_system_prompt(npc, lore_chunks=chunks)
        assert "LORE SNIPPETS" in prompt
        assert "[lore#p7]" in prompt
        assert "century of silence" in prompt
        assert "[lore#p3]" in prompt

    def test_prompt_surfaces_knowledge_with_gate(self):
        npc = _tavernkeeper_with_knowledge()
        prompt = build_improv_system_prompt(npc, lore_chunks=[])
        assert "the_well" in prompt
        assert "Moon Court" in prompt  # the gate text
        assert "Sample deflection lines" in prompt

    def test_prompt_omits_memory_when_none(self):
        npc = _tavernkeeper_with_knowledge()
        prompt = build_improv_system_prompt(npc, lore_chunks=[])
        # Memory block starts with the specific 'Memory of past encounters'
        # header (distinct from rule text, which doesn't appear in improv
        # rules).
        assert "Memory of past encounters" not in prompt

    def test_prompt_includes_memory_when_supplied(self):
        npc = _tavernkeeper_with_knowledge()
        store = MemoryStore()
        store.current_turn = 2
        store.record(npc_id="mira", event_type="player_lied",
                     summary="denied knowing Kess", salience="pivotal")
        prompt = build_improv_system_prompt(npc, lore_chunks=[], memory_store=store)
        assert "Memory of past encounters" in prompt
        assert "denied knowing Kess" in prompt

    def test_prompt_falls_back_to_sheet_only_message_when_no_lore(self):
        npc = _tavernkeeper_with_knowledge()
        prompt = build_improv_system_prompt(npc, lore_chunks=[])
        assert "LORE SNIPPETS: (none retrieved" in prompt

    def test_prompt_embeds_faction_block_when_supplied(self):
        npc = NpcSheet(
            id="mira", name="Mira", role="tavernkeeper", voice="gruff",
            faction_id="lantern",
        )
        factions = FactionsConfig(factions=[
            Faction(id="lantern", name="Lantern Regulars"),
        ])
        prompt = build_improv_system_prompt(
            npc, lore_chunks=[], factions=factions)
        assert "Primary: Lantern Regulars" in prompt


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class TestImprovReplySchema:
    def test_minimal_reply_validates(self):
        r = ImprovReply(text="I don't talk about the deep, friend.")
        assert r.used_gate_id == ""
        assert r.declined_reason == ""

    def test_reply_with_gate_used(self):
        r = ImprovReply(
            text="Older than anything here. Don't ask twice.",
            used_gate_id="the_well",
        )
        assert r.used_gate_id == "the_well"

    def test_text_is_required(self):
        with pytest.raises(Exception):  # Pydantic ValidationError
            ImprovReply()  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# End-to-end plumbing check (no LLM call)
# ---------------------------------------------------------------------------


class TestRustedLanternIntegration:
    def test_retrieval_over_rusted_lantern_lore(self):
        root = Path(__file__).resolve().parent.parent / "examples/rusted_lantern/lore"
        assert root.is_dir()
        bundle = "\n\n".join(
            p.read_text(encoding="utf-8")
            for p in sorted(root.glob("*.md"))
        )
        results = retrieve_lore_chunks("tell me about the deep", bundle, top_k=3)
        assert len(results) >= 1
        # At least one result should mention the mine / the deep.
        combined = "\n".join(r.text.lower() for r in results)
        assert "deep" in combined or "mine" in combined
