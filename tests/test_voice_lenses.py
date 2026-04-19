"""Tests for v0.14.0 cultural / linguistic voice lenses."""

from __future__ import annotations

from pathlib import Path

import pytest

from npcforge.improv import build_improv_system_prompt
from npcforge.prompts import build_npc_respondent_prompt, _render_voice_lenses
from npcforge.schemas import (
    NpcSheet,
    VoiceLens,
    load_npcs,
    resolve_active_lenses,
    validate_npc_voice_lenses,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _npc_with_lenses(*lenses: VoiceLens) -> NpcSheet:
    return NpcSheet(
        id="mira", name="Mira", role="tavernkeeper", voice="gruff",
        voice_lenses=list(lenses),
    )


def _tipsy_lens() -> VoiceLens:
    return VoiceLens(
        id="tipsy", label="tipsy", kind="state",
        cadence_shift="Sentences loosen; contractions return.",
        extra_accent_markers=["repeats a phrase twice"],
    )


def _inspector_lens() -> VoiceLens:
    return VoiceLens(
        id="inspector_present",
        label="speaking to a Guild inspector",
        kind="audience",
        cadence_shift="Adds titles. No 'friend'. Full sentences.",
        extra_forbidden_words=["deep", "friend"],
        extra_accent_markers=["Says 'the mine' where she'd normally say 'the deep'."],
    )


# ---------------------------------------------------------------------------
# Schema + validation
# ---------------------------------------------------------------------------


class TestVoiceLensSchema:
    def test_duplicate_lens_ids_rejected(self):
        npc = _npc_with_lenses(_tipsy_lens(), _tipsy_lens())
        with pytest.raises(ValueError, match="duplicate voice_lens id"):
            validate_npc_voice_lenses([npc])

    def test_empty_lens_list_passes(self):
        npc = NpcSheet(id="x", name="X", role="y", voice="z")
        validate_npc_voice_lenses([npc])  # no raise

    def test_rusted_lantern_lenses_validate(self):
        root = Path(__file__).resolve().parent.parent / "examples/rusted_lantern"
        npcs = load_npcs(root / "characters.yaml")
        validate_npc_voice_lenses(npcs)
        gereth = next(n for n in npcs if n.id == "gereth_blackstone")
        mira = next(n for n in npcs if n.id == "mira_vesser")
        assert {l.id for l in gereth.voice_lenses} == {
            "grindholt_formal", "tipsy", "with_adelie_present"}
        assert {l.id for l in mira.voice_lenses} == {
            "inspector_present", "last_call"}

    def test_kind_literal_enforced(self):
        with pytest.raises(Exception):
            VoiceLens(
                id="x", label="x", kind="bogus",  # type: ignore[arg-type]
                cadence_shift=".")


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


class TestResolveActiveLenses:
    def test_returns_subset_preserving_declaration_order(self):
        npc = _npc_with_lenses(
            _tipsy_lens(),
            _inspector_lens(),
            VoiceLens(id="c", label="c", kind="cultural", cadence_shift="x"),
        )
        active = resolve_active_lenses(npc, {"c", "tipsy"})
        assert [l.id for l in active] == ["tipsy", "c"]

    def test_unknown_ids_silently_ignored(self):
        npc = _npc_with_lenses(_tipsy_lens())
        active = resolve_active_lenses(npc, {"unknown_lens", "also_unknown"})
        assert active == []

    def test_npc_without_lenses_returns_empty(self):
        npc = NpcSheet(id="x", name="X", role="y", voice="z")
        assert resolve_active_lenses(npc, {"anything"}) == []


# ---------------------------------------------------------------------------
# _render_voice_lenses
# ---------------------------------------------------------------------------


class TestRenderVoiceLenses:
    def test_empty_returns_empty(self):
        assert _render_voice_lenses([]) == ""

    def test_renders_header_and_per_lens_block(self):
        block = _render_voice_lenses([_tipsy_lens(), _inspector_lens()])
        assert "Active voice lenses" in block
        assert "state: tipsy (tipsy)" in block
        assert "audience: speaking to a Guild inspector (inspector_present)" in block
        assert "Sentences loosen" in block
        assert "Adds titles" in block

    def test_unions_extra_forbidden_and_accent_across_lenses(self):
        block = _render_voice_lenses([_inspector_lens(), _tipsy_lens()])
        # extra_forbidden from inspector_present only.
        assert "Extra forbidden words" in block
        assert '"deep"' in block
        assert '"friend"' in block
        # extra_accent_markers from both.
        assert "repeats a phrase twice" in block
        assert "Says 'the mine'" in block

    def test_dedups_extra_markers_across_lenses(self):
        a = VoiceLens(id="a", label="a", kind="state", cadence_shift=".",
                      extra_forbidden_words=["x"])
        b = VoiceLens(id="b", label="b", kind="state", cadence_shift=".",
                      extra_forbidden_words=["x", "y"])
        block = _render_voice_lenses([a, b])
        # 'x' should appear once in the extra-forbidden list.
        forb_line = [l for l in block.splitlines()
                     if "Extra forbidden words" in l][0]
        assert forb_line.count('"x"') == 1
        assert '"y"' in forb_line


# ---------------------------------------------------------------------------
# Prompt wiring
# ---------------------------------------------------------------------------


class TestPromptWiring:
    def test_respondent_prompt_omits_block_without_active(self):
        npc = _npc_with_lenses(_tipsy_lens())
        prompt = build_npc_respondent_prompt(npc)
        # Rule 14 mentions 'Active voice lenses' + 'situational modifiers'
        # in prose. Use a render-only token (literal "Cadence shift:"
        # per-line prefix) to prove no block was appended.
        assert "Cadence shift:" not in prompt

    def test_respondent_prompt_includes_block_when_active(self):
        npc = _npc_with_lenses(_tipsy_lens())
        prompt = build_npc_respondent_prompt(npc, active_lenses=[_tipsy_lens()])
        assert "Active voice lenses" in prompt
        assert "tipsy (tipsy)" in prompt

    def test_improv_prompt_includes_block_when_active(self):
        npc = _npc_with_lenses(_inspector_lens())
        prompt = build_improv_system_prompt(
            npc, lore_chunks=[], active_lenses=[_inspector_lens()])
        assert "Active voice lenses" in prompt
        assert "inspector_present" in prompt

    def test_rule_14_present_in_base_rules(self):
        npc = NpcSheet(id="x", name="X", role="y", voice="z")
        prompt = build_npc_respondent_prompt(npc)
        assert "14. If an 'Active voice lenses' block" in prompt
