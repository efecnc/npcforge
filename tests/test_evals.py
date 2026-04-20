"""Tests for v0.22.0 dialogue-quality eval harness.

Covers the pure / deterministic surfaces only: scoring helpers, Pydantic
shapes, report rendering, and the built-in Rusted Lantern fixture list.
LLM-driven paths (``run_case`` / ``run_suite``) need live API keys and
are exercised separately via ``npcforge eval``.
"""

from __future__ import annotations

from npcforge.evals import (
    CaseResult,
    EvalCase,
    EvalReport,
    _META_PHRASES,
    check_lint,
    check_register,
    count_sentences,
    count_words,
    default_rusted_lantern_cases,
    render_markdown_report,
)
from npcforge.schemas import NpcSheet


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _npc(forbidden: list[str] | None = None) -> NpcSheet:
    return NpcSheet(
        id="mira", name="Mira", role="tavernkeep", voice="dry",
        forbidden_words=forbidden or [],
    )


# ---------------------------------------------------------------------------
# count_sentences / count_words
# ---------------------------------------------------------------------------


class TestSentenceCount:
    def test_empty_string(self):
        assert count_sentences("") == 0
        assert count_sentences("   ") == 0

    def test_single_sentence_no_terminator(self):
        assert count_sentences("Hello there") == 1

    def test_single_sentence_with_period(self):
        assert count_sentences("Hello there.") == 1

    def test_multiple_sentences(self):
        assert count_sentences("One. Two. Three.") == 3

    def test_mixed_terminators(self):
        assert count_sentences("Really? Yes! I know.") == 3

    def test_run_together_punct_collapses(self):
        # "!!!" should count as one terminator, not three.
        assert count_sentences("Wow!!! Go.") == 2


class TestWordCount:
    def test_empty(self):
        assert count_words("") == 0

    def test_single(self):
        assert count_words("Mm.") == 1

    def test_whitespace_collapses(self):
        assert count_words("one   two\tthree") == 3


# ---------------------------------------------------------------------------
# check_lint
# ---------------------------------------------------------------------------


class TestCheckLint:
    def test_no_forbidden_words_no_hits(self):
        hits, notes = check_lint("Evening traveller.", _npc())
        assert hits == 0
        assert notes == []

    def test_hits_per_forbidden_word(self):
        npc = _npc(forbidden=["thee", "verily"])
        hits, notes = check_lint("Verily thee shall pass.", npc)
        assert hits == 2
        assert any("thee" in n for n in notes)
        assert any("verily" in n for n in notes)

    def test_match_is_case_insensitive(self):
        npc = _npc(forbidden=["Deep"])
        hits, _ = check_lint("The deep calls.", npc)
        assert hits == 1

    def test_word_boundary_so_substrings_do_not_match(self):
        npc = _npc(forbidden=["deep"])
        hits, _ = check_lint("Her deepness surprises me.", npc)
        assert hits == 0

    def test_extra_forbidden_adds_to_per_case(self):
        hits, notes = check_lint(
            "That's the answer.",
            _npc(),
            extra_forbidden=["answer"],
        )
        assert hits == 1
        assert any("answer" in n for n in notes)

    def test_empty_forbidden_ignored(self):
        npc = _npc(forbidden=["", "real"])
        hits, _ = check_lint("A real find.", npc)
        assert hits == 1


# ---------------------------------------------------------------------------
# check_register
# ---------------------------------------------------------------------------


class TestCheckRegister:
    def test_clean_line_passes(self):
        ok, notes = check_register("Evening. Coin or story — one of them.")
        assert ok is True
        assert notes == []

    def test_ai_meta_phrase_fails(self):
        ok, notes = check_register("As an AI, I cannot answer that.")
        assert ok is False
        # Multiple phrases in _META_PHRASES match ("as an ai",
        # "i cannot") — both should be reported.
        assert len(notes) >= 1

    def test_parenthetical_stage_direction_fails(self):
        ok, notes = check_register("(quietly) I have not seen it.")
        assert ok is False
        assert any("(quietly)" in n for n in notes)

    def test_asterisk_stage_direction_fails(self):
        ok, notes = check_register("*nods* Aye.")
        assert ok is False
        assert any("*nods*" in n for n in notes)

    def test_narrator_tag_fails(self):
        ok, _ = check_register("[NARRATOR] The room falls quiet.")
        assert ok is False

    def test_case_insensitive_match(self):
        ok, _ = check_register("AS A LANGUAGE MODEL I must decline.")
        assert ok is False

    def test_meta_phrase_list_non_empty(self):
        # Regression guard — it's very easy to accidentally drop the
        # tuple to empty while editing.
        assert len(_META_PHRASES) > 5


# ---------------------------------------------------------------------------
# EvalCase / CaseResult / EvalReport
# ---------------------------------------------------------------------------


class TestPydanticShapes:
    def test_case_defaults(self):
        case = EvalCase(id="x", npc_id="y", prompt="Hi.")
        assert case.max_sentences == 3
        assert case.max_words == 60
        assert case.forbid_phrases == []

    def test_case_roundtrip_json(self):
        case = EvalCase(
            id="x", npc_id="y", prompt="Hi.",
            max_sentences=2, max_words=20, forbid_phrases=["ai"],
        )
        blob = case.model_dump_json()
        rebuilt = EvalCase.model_validate_json(blob)
        assert rebuilt == case

    def test_result_defaults_fail_closed(self):
        r = CaseResult(case_id="x", npc_id="y", prompt="p")
        # overall_pass defaults False — must be set explicitly by the runner.
        assert r.overall_pass is False
        assert r.generated_ok is True  # generation presumed ok until proven otherwise
        assert r.length_ok is True
        assert r.register_ok is True

    def test_report_pass_rate_with_zero_cases(self):
        r = EvalReport(provider="gemini", model="x")
        assert r.pass_rate == 0.0

    def test_report_pass_rate_with_cases(self):
        r = EvalReport(provider="gemini", model="x", total=4, passed=3)
        assert r.pass_rate == 0.75


# ---------------------------------------------------------------------------
# render_markdown_report
# ---------------------------------------------------------------------------


class TestRenderMarkdown:
    def _sample_report(self) -> EvalReport:
        return EvalReport(
            provider="gemini",
            model="gemini-2.5-flash",
            total=2,
            passed=1,
            voice_avg=0.55,
            lint_total=1,
            length_failures=0,
            register_failures=1,
            results=[
                CaseResult(
                    case_id="mira_greet", npc_id="mira_vesser",
                    prompt="Evening.",
                    text="Evening. Coin or story.",
                    voice_score=0.72,
                    lint_hits=0, length_ok=True, register_ok=True,
                    overall_pass=True, elapsed_ms=820.0,
                ),
                CaseResult(
                    case_id="kess_trust", npc_id="kess_the_knife",
                    prompt="Can I trust you?",
                    text="(quietly) Of course you can.",
                    voice_score=0.38,
                    lint_hits=1,
                    lint_notes=[
                        "meta phrase leaked: '(quietly)'",
                        "forbidden word used: 'of'",
                    ],
                    length_ok=True, register_ok=False,
                    overall_pass=False, elapsed_ms=910.0,
                ),
            ],
        )

    def test_markdown_has_header_and_metadata(self):
        md = render_markdown_report(self._sample_report())
        assert md.startswith("# npcforge eval report")
        assert "provider: `gemini`" in md
        assert "model: `gemini-2.5-flash`" in md
        assert "passed: 1 / 2" in md
        assert "50%" in md  # pass-rate percentage

    def test_markdown_has_per_case_rows(self):
        md = render_markdown_report(self._sample_report())
        assert "| case | npc | pass | voice | lint | len | reg | elapsed |" in md
        assert "`mira_greet`" in md
        assert "`kess_the_knife`" in md

    def test_markdown_flags_passes_and_fails(self):
        md = render_markdown_report(self._sample_report())
        # Mira row passes; Kess row fails (register=✗).
        assert "| ✓ |" in md
        assert "| ✗ |" in md

    def test_markdown_includes_reply_and_notes(self):
        md = render_markdown_report(self._sample_report())
        assert "Evening. Coin or story." in md
        assert "meta phrase leaked" in md
        assert "forbidden word used: 'of'" in md

    def test_markdown_handles_empty_report(self):
        md = render_markdown_report(EvalReport(provider="gemini", model="x"))
        assert "# npcforge eval report" in md
        assert "cases: 0" in md
        assert "passed: 0 / 0" in md


# ---------------------------------------------------------------------------
# default_rusted_lantern_cases
# ---------------------------------------------------------------------------


class TestDefaultSuite:
    def test_has_twenty_cases(self):
        cases = default_rusted_lantern_cases()
        assert len(cases) == 20

    def test_ids_are_unique(self):
        cases = default_rusted_lantern_cases()
        ids = [c.id for c in cases]
        assert len(set(ids)) == len(ids)

    def test_all_five_npcs_covered(self):
        cases = default_rusted_lantern_cases()
        expected = {
            "mira_vesser", "gereth_blackstone", "sister_adelie",
            "kess_the_knife", "ulrik_the_old_man",
        }
        got = {c.npc_id for c in cases}
        assert expected == got

    def test_every_prompt_non_empty(self):
        for c in default_rusted_lantern_cases():
            assert c.prompt.strip()
