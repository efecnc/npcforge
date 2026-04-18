# Changelog

All notable changes to npcforge land here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[SemVer](https://semver.org/).

## [0.8.1] — 2026-04-18

Closes the two items deliberately deferred in v0.8.0: character state
evolution, and the relationship-anchor fix for the "blacksmith drift"
the LLM occasionally showed when describing another cast member.

### Added

- **`StateEvolution`** schema — `{trigger, voice_shift, description}`.
  Each entry is a voice shift the NPC undergoes when a condition
  becomes true (*"disposition_mira < 20"*, *"quest_locket_stage >= 3"*).
  Gate syntax is free-text; matches `KnowledgeItem.gate`. The
  respondent prompt rule-set gets a rule 9 instructing the LLM to apply
  active shifts as modifiers on the core voice, not replacements.
- **`NpcSheet.state_evolution: list[StateEvolution]`** — default empty.
- **Peer-role anchor in relationships** — `render_character_sheet` now
  accepts an optional `cast: list[NpcSheet]`. When supplied, each
  relationship target is annotated with that NPC's real role from the
  sheet:
  ```
  - gereth_blackstone (Gereth Blackstone, Dwarven miner, sole survivor of the cave-in): protective, guilty
      Why: She sold the mine lease to the expedition...
  ```
  Rule 7 of the respondent prompt was extended to name-check this
  column and explicitly forbid inventing generic occupations. Pipeline
  threading (`_build_provider` → `generate_branch` → `generate_for_npc`
  → `run_all`) passes the full `selected` cast all the way down.

### Demo updates

- Mira gets two state-evolution entries:
  - `disposition_mira < 20` → *"drops the transactional bartender
    veneer... calls people by surnames not 'friend'. The 'deep' accent
    marker holds."*
  - `quest_locket_stage >= 4` → *"acknowledges the deep by name...
    stops pretending the humming is just weather."*
- Gereth gets two:
  - `quest_locket_stage >= 3` → *"four-note hum halves in frequency.
    Sentences grow longer... 'twelve, one' only in real grief."*
  - `disposition_mira < 20` → *"stops defending Mira."*

### Tests — 152 passing (up from 143)

- `StateEvolution` default fields; NpcSheet's default-empty
  `state_evolution`; demo sheets ship with evolution entries.
- Peer-role anchor: rendering without `cast` matches v0.8.0 shape;
  rendering with `cast` annotates each relationship target with their
  role; unknown-target relationships fall back gracefully.
- State-evolution block rendering includes Trigger / Voice shift /
  optional Note; omitted entirely when empty.

### Verified end-to-end on Gemini 2.5-flash

Re-ran the v0.8.0 failure case — asking Mira about Gereth:

> **Mira:** *"He's a miner. Sole survivor from deep's cave-in. Keeps to himself."*

Correct role from the world bible. No fantasy-blacksmith leakage. The
v0.8.0 known-limitation is resolved.

### New known limitation (v0.8.2)

When the Correspondent (player) model drops an NPC's name and says
"that dwarf I saw earlier", the LLM occasionally fabricates a
substitute name ("Grak Stonehand") rather than committing to the real
one. Separate naming-fidelity pass in v0.8.2. The role grounding that
v0.8.1 fixes is intact.

### Not in v0.8.1 (deliberately)

- Multi-character scenes (`group_chatter_pair` mode).
- Structured gate matching — `{variable, op, value}` resolver that
  reads the state layer at generation time.
Both are v0.8.2.

---

## [0.8.0] — 2026-04-18

Character depth — the first half of the veteran-designer review's
Witcher/RDR2-tier dynamics. Two structured fields on every `NpcSheet`:
`relationships` (what each NPC thinks of the others) and `knowledge`
(structured facts with optional reveal gates). Both flow into every
downstream generator's respondent prompt.

### Added

- **`Relationship`** schema — `{npc_id, opinion, reason}`. Declares one
  NPC's stance toward another cast member with a grounded reason the
  LLM can reference. Rendered in the character-sheet block as
  `- <target>: <opinion> — <reason>`.
- **`KnowledgeItem`** schema — `{id, fact, gate, reveal_lines,
  deflect_lines}`. Each gated fact carries tone exemplars for both
  sides of the gate. The respondent prompt rule-set got two new rules:
  reveal only when the gate is clearly met, otherwise deflect using
  the sample deflection tone.
- Demo updates: Mira now declares relationships with all four other
  Rusted Lantern NPCs plus two gated knowledge items (`sold_mine_lease`
  gated on coin + expedition mention; `broken_seal` never-direct-reveal).
  Gereth declares cross-cast relationships plus `not_found_locket`
  gated on trauma-exchange (confess_vulnerability + player naming a
  loss first).

### Changed

- `render_character_sheet` grows two new blocks when the NPC has
  relationships or knowledge; otherwise the output is unchanged.
- `build_npc_respondent_prompt` gains rules 7 and 8 covering
  relationship usage and knowledge-gate behaviour.
- NpcSheet gains `relationships: list[Relationship]` and
  `knowledge: list[KnowledgeItem]` fields (both default empty, so
  every existing cast keeps working).

### Tests — 143 passing (up from 133)

- `Relationship` / `KnowledgeItem` default shapes.
- YAML round-trip of the demo: Mira has 4 relationships + 2 gated
  knowledge items; Gereth has relationships back toward Mira.
- `render_character_sheet` includes + omits relationships/knowledge
  sections based on presence.
- Respondent prompt mentions relationships and gates.
- Free-form tmp YAML round-trip covering the new fields.

### Verified end-to-end on Gemini 2.5-flash

Build on Mira + Gereth at `--turns 3`, then played four branches:

- **Gereth's `confess_vulnerability` with player's parallel loss** →
  gate met → Gereth reveals in his own fragmented voice:
  *"The dark takes its toll, doesn't it? Twelve, one. Hmm-hmm-hmm-hmm.
  This locket... it was there. With the others. A cost, yes."*
- **Mira's `ask_about_locket` without coin or faction token** → gate
  not met → she deflects in deflect-line tone: *"Whispers always fly.
  Never much truth to half of them."* / *"Old wives' tales. Something
  about luck. Or doom."*
- **Mira's `bribe_for_info` with silver + expedition named** → gate
  partially met → she reveals a step further: *"A silver buys some
  talk. They went into old deep for mithril. That's what they
  claimed."*
- **Mira's `ask_about_npc_other` asking about Gereth** → her declared
  relationship ("protective, guilty") colours the answer; LLM noted
  Gereth sticks to old ways and would be "good with metal." (Some
  fantasy-dwarf-stereotype leakage — a known prompt-strength
  limitation; v0.8.1 will tighten the world-bible anchor.)

### Known limitation

Relationship content occasionally pulls from the LLM's generic prior
(fantasy-dwarf = blacksmith) when the world-bible entry for the target
NPC is thin on what they *do*. Tightening the respondent prompt to
anchor in the world-bible role is a v0.8.1 item.

### Not in v0.8.0 (deliberately)

- `state_evolution:` block (NPC voice shifts at quest beats)
- Multi-character scenes (`group_chatter_pair`)
- Structured gate matching (`{variable: value}` tied to state layer)

All three are v0.8.1 / v0.8.2 work.

---

## [0.7.1+unity-upm] — 2026-04-18

Unity UPM package — installable from the Package Manager. Supplement to
v0.7.1; no Python changes.

### Added

- **`examples/unity_integration/npcforge-unity/`** — full UPM package
  structured per Unity's manifest + asmdef specs:
  - `package.json` — `dev.altai.npcforge` @ `0.1.0`, `unity = "2022.3"`,
    Apache-2.0 licence, keywords, repo/doc/changelog URLs.
  - `Runtime/Altai.NpcForge.asmdef` — references `YarnSpinner.Unity`;
    `versionDefines` gate a `NPCFORGE_HAS_YARN` symbol so code compiles
    cleanly when Yarn Spinner is missing.
  - `Runtime/*.cs` — four glue scripts in the `Altai.NpcForge`
    namespace (`NpcForgeDialogueController`, `TimeOfDayController`,
    `NpcApproachButton`, `NpcForgeStartup`).
  - `Editor/Altai.NpcForge.Editor.asmdef` — `includePlatforms:
    ["Editor"]`, references only the Runtime assembly.
  - `Editor/NpcForgePreferences.cs` — per-project `EditorPrefs` scoped
    by `PlayerSettings.productGUID`.
  - `Editor/NpcForgeCliRunner.cs` — background-thread subprocess
    runner with main-thread callback dispatch; streams stdout/stderr
    line-by-line so multi-minute generations don't freeze the Editor.
  - `Editor/NpcForgeWindow.cs` — IMGUI panel with Settings, Generate,
    Sync, and Log sections. Calls `AssetDatabase.Refresh()` after
    successful syncs so new `.yarn` files appear instantly.
  - `Editor/NpcForgeMenu.cs` — top-level `Tools → npcforge` menu with
    `Open Panel…` (`Ctrl/Cmd+Shift+Alt+N`), `Quick Sync to This
    Project`, `Build All`, `Documentation`.
  - `Documentation~/index.md` — package-scoped docs (tilde suffix keeps
    Unity from importing it as an asset).
  - `README.md` + `CHANGELOG.md` at package root.

### Install

In Unity, **Window → Package Manager → +** → **Add package from git URL…**:
```
https://github.com/efecnc/npcforge.git?path=examples/unity_integration/npcforge-unity
```

Users still need Python + the `npcforge` CLI installed separately (the
CLI is what the package subprocesses out to). Yarn Spinner for Unity
2.4+ is the only Unity-side hard dependency.

### Built against the Unity docs

Package structure, `package.json` fields, `.asmdef` format, and
EditorWindow patterns were built against the current Unity 2022.3 LTS
docs (`upm-manifestPkg.html`, `cus-layout.html`,
`assembly-definition-file-format.html`, `EditorWindow` ScriptReference).
IMGUI chosen over UI Toolkit for MVP to avoid an extra package
dependency; a UI Toolkit rewrite can slot in later without changing the
surface area.

### Not tested inside Unity Editor

Built correctly per the spec but not exercised in a live Editor this
session (no Unity install on the dev machine). Expected issues to
catch on first real install: `asmdef` reference syntax, IMGUI rect
calculations on smaller windows, subprocess path resolution on
Windows. All are localised; fixable without architectural changes.

---

## [0.7.1] — 2026-04-18

The "characters and conversations just appear in your engine" release.
One command pushes the generator's output into Unity, Godot, or Unreal's
expected filesystem layout — no copy-paste step between npcforge and
the engine ever again.

### Added

- **`src/npcforge/engines/`** — new package with one file per engine:
  - `base.py` — `EngineAdapter` base class + `SyncAction` / `SyncResult`
    dataclasses + `SyncMarker` (read / write / hash the
    `.npcforge-sync.json` bookkeeping file).
  - `unity.py` — Unity adapter. Dialogue → `Assets/NpcForge/Dialogue/`;
    runtime glue (the 4 C# scripts from `examples/unity_integration`) →
    `Assets/NpcForge/Scripts/` with `--install-scripts`.
  - `godot.py` — Godot adapter. Dialogue → `<project>/npcforge/dialogue/`.
  - `unreal.py` — Unreal adapter. `.yarn` → `Content/NpcForge/Dialogue/`;
    `lines.csv` relocates to `Content/NpcForge/Data/` so the engine
    indexes it as a data asset rather than a dialogue script.
  - Registry in `__init__.py` with `get_adapter(name)` +
    `supported_engines()` for tool / CLI dispatch.
- **`engine_sync` tool** (10th in `TOOL_REGISTRY`) — Pydantic
  input / output with `demo_dir`, `project_dir`, `engine`, optional
  `source_dir` override (to sync a frozen `sample_output/` instead of
  live `out/`), `install_scripts`, `dry_run`. Returns typed actions +
  errors + marker path.
- **`npcforge engine-sync` CLI subcommand** with the same flags plus
  `--verbose` for per-file action logging.
- **Sync marker (`.npcforge-sync.json`)** — written inside the engine's
  dialogue folder. Tracks {file → sha256} so subsequent syncs skip
  unchanged content and only recopy what actually changed.

### Design choices worth calling out

- **We do not write engine-specific sidecars** (`.yarn.meta`, `.import`,
  `.uasset`). Yarn Spinner / Godot / Unreal all generate those on first
  reimport. Hand-writing them drifts with Yarn Spinner versions; letting
  the engine do it is the robust path.
- **Project root is the engine's filesystem root**, not `res://` or any
  editor alias — we're a filesystem tool, not an in-editor plugin.
  Users point `--project-dir` at the folder that contains `Assets/` for
  Unity, `Content/` for Unreal, `project.godot` for Godot.
- **Content filter is whitelist-only**. Only `.yarn` and `.csv` from the
  source `out/` get synced — JSONL traces, `manifest.json`, `lint.md`
  stay out of the engine tree.

### Tests — 133 passing (up from 113)

- Registry: `supported_engines()` exposes {godot, unity, unreal};
  `get_adapter` rejects unknown names.
- Path resolution per engine (dialogue folder, scripts folder).
- `SyncMarker.read` / `.to_json` roundtrip; graceful null on missing
  or corrupt file.
- Unity sync copies `.yarn` + `.csv`, skips debug output (`.jsonl`,
  `manifest.json`, `lint.md`), writes the marker.
- Second sync skips unchanged files; changed file is re-copied with
  reason `"content changed"`.
- Dry-run writes nothing (no dialogue dir, no marker).
- Missing source directory surfaces as an error, no crash.
- Unreal relocates `lines.csv` from `Dialogue/` to `Data/`.
- `engine_sync` tool: round-trip on Unity via `demo_dir` convention,
  dry-run preserves action planning, `source_dir` override works.

### Verified end-to-end against committed sample_output

Fresh sync of `examples/rusted_lantern/sample_output/` (12 `.yarn` files
from a prior full build):

- Unity + `--install-scripts`: 12 dialogue files + 4 C# glue files = 16
  deliverables, marker at `Assets/NpcForge/Dialogue/.npcforge-sync.json`.
- Godot: 12 dialogue files under `npcforge/dialogue/`, marker alongside.
- Unreal: 12 dialogue files under `Content/NpcForge/Dialogue/`, marker
  alongside.

Every tree is what each engine's importer expects to find. The user's
workflow compresses from *"run build → find out/ → copy files into
engine → set up Yarn Project manually"* to *"npcforge engine-sync
--engine X --project-dir Y"*.

---

## [0.7.0] — 2026-04-18

First release focused on making every generated line **audio-pipeline
ready** — the side-data Wwise / FMOD / Unity Audio / loc teams need
alongside the Yarn files. No new generators; every existing output now
carries line IDs, emotion, and duration estimates.

### Added

- **`src/npcforge/audio.py`** — new pure module with:
  - `LineRecord` Pydantic model (line_id, npc_id, speaker, context,
    source_file, emotion, intensity, duration_sec, text).
  - `line_id(npc_id, text, context)` — deterministic hash-based ID.
    Same text in same context → same ID across regens; different
    context disambiguates same text in different places.
  - `count_syllables(text)` — vowel-group + trailing-e heuristic.
  - `estimate_duration_seconds(text)` — syllable-based speech-rate
    estimate; minimum 0.3 s per line.
  - `infer_emotion(text)` — token-rule heuristic returning
    `(emotion, intensity)`. Matches the emotion vocabulary already on
    barks.
  - `write_lines_csv` / `read_lines_csv` — canonical CSV I/O with a
    fixed column order downstream tooling can depend on.

- **`LinesExport`** field on `Manifest` — `{csv: str, total: int}`.
  Null on runs that produced no lines.

- **`lines.csv` emitted by `build_pipeline`** — every walk-up turn and
  every bark variant gets one row. Column order is frozen:
  `line_id, npc_id, speaker, context, source_file, emotion, intensity, duration_sec, text`.

### Changed

- Manifest `version` now reads `0.7.0` on every new build.
- `run_all` collects `LineRecord`s as walk-up and bark content flows
  through, then writes `lines.csv` once at the end. Barks reuse the
  structured emotion / intensity the generator already produces; walk-up
  turns get heuristic-inferred emotion from `infer_emotion`.

### Tests — 113 passing (up from 94)

- `canonicalise_text` collapses whitespace consistently.
- `line_id` is deterministic across whitespace variations, context, and
  text changes; format is `<npc_id>_<10-hex>`.
- `count_syllables` + `estimate_duration_seconds` — basic words,
  trailing-e rule, minimum clamp, growth with length.
- `infer_emotion` — threatening / pleading / warm / neutral rules +
  intensity high-from-`!!!` and low-from-`...`.
- `write_lines_csv` / `read_lines_csv` roundtrip preserves every field
  and the column order contract.

### Verified end-to-end on Gemini 2.5-flash

`build --demo-dir /tmp/npcforge_v07 --only-npcs mira_vesser --mode all
--turns 2` produced a 46-line `lines.csv`:

- walk-up turns from 9 intent branches, each tagged with speaker,
  duration (1.25 s … 10.50 s), and heuristic emotion.
- bark variants across `greet_patron` + `reacts_to_hum` reusing the
  structured emotion / intensity generated at bark time.
- deterministic `line_id` format `mira_vesser_<10-hex>`.

### Not in v0.7

State-aware walk-up branches (emit `<<if>>` / `<<set>>` on the main
walk-up pipeline) and Godot integration example are the v0.7.1 and
v0.7.2 releases respectively — deliberately scoped out to keep this
release focused on the audio/VO side of engine-consumable output.

---

## [0.6.1+unity] — 2026-04-18

Unity 2022 integration example — committed, no code changes.

### Added

- **`examples/unity_integration/`** — drop-in Unity starter:
  - `Assets/NpcForge/Dialogue/` — real `.yarn` files produced by v0.6.1:
    `world.yarn` with `<<declare>>` defaults, `mira_vesser.yarn` (9
    walk-up intent branches), `mira_vesser_greet_time_of_day.yarn` (5
    time-of-day variants), `mira_vesser_repeat_greet.yarn` (4
    visit-gated variants + else-fallback).
  - `Assets/NpcForge/Scripts/` — four C# scripts that wire Yarn
    Spinner 2 to npcforge's node-naming conventions:
    `NpcForgeDialogueController` (state setters + node entry points),
    `TimeOfDayController` (UI button glue), `NpcApproachButton`
    (per-button mode selector), `NpcForgeStartup` (seed variables at
    scene load).
  - `SETUP.md` — step-by-step: new 2022.3 LTS project → Yarn Spinner
    package install → Yarn Project with the shipped `.yarn` files →
    scene wiring → press Play.
- Root README links the integration under "Ready-to-run starter worlds".

### Why

The v0.6.x state layer produces dialogue that *claims* to be
engine-ready. This commit proves it: every generated `.yarn` file
imports into Yarn Spinner without edits, and Unity reads / writes the
same variable storage that the generator's prompts reference.

---

## [0.6.1] — 2026-04-18

Completes the two v0.6.0 known-limitations: `play` now renders both
state-aware node types, and `gen repeat-greeting` ships alongside
`gen greetings`.

### Added

- **`gen_repeat_greeting`** tool (9th in `TOOL_REGISTRY`) — generates
  visit-count-gated greetings per NPC. Visits 0 .. n-2 play distinct
  variants; the final variant is an `<<else>>` fallback for every
  subsequent visit. Uses Yarn's `visited_count()` builtin so no project
  variable is required.
- **`npcforge gen repeat-greeting --n 3 --only-npcs mira_vesser`** CLI
  subcommand.
- **`npcforge play --greet <variable>`** — render an enum-keyed
  greeting node (one line per enum value, labelled
  `[time_of_day=morning] Mira: ...`).
- **`npcforge play --repeat-greet`** — render a visit-counter greeting
  node (labels `[visit #0] ... [visit else]`, including the
  else-fallback line).
- Play parser now dispatches on three conditional shapes cleanly —
  bark rotation (`% N == I`), enum greeting (`$var == "value"`), and
  visit counter (`== I`) — into three typed variant lists on
  `YarnNode` (`bark_variants`, `enum_variants`, `visit_variants`).

### Changed

- Yarn exporter gains `render_repeat_greeting_node(npc, variants)` and
  `repeat_greeting_node_title(npc_id)`; shape mirrors `render_bark_node`
  but keyed on `visited_count() == N` rather than `% N == I`.
- Prompts gain `build_repeat_greeting_prompt(npc, visit_index, n_total,
  is_else)` — situational framing per visit (stranger / recognised /
  familiar / regular).

### Tests — 94 passing (up from 83)

- `render_repeat_greeting_node` shape: N=2, N=3, empty-variants fallback.
- Parser extracts enum variants (cleanly routed away from bark / visit
  lists) and visit variants (including the `<<else>>` branch as
  index = -1).
- `render_enum_variants` and `render_visit_variants` label each line
  with the right bracket form.
- `play_greetings` and `play_repeat_greeting` round-trip from disk.

### Verified end-to-end on Gemini 2.5-flash

`npcforge gen repeat-greeting --only-npcs mira_vesser --n 4`:

```
[visit 0] Table's empty. Drink, or just passing through?
[visit 1] Seen you before. What'll it be?
[visit 2] You're getting comfortable in deep's walls. What's need?
[else]    Don't bother with a menu; you know what you like.
```

Her accent marker holds across the arc — "deep's walls" for "the
mine's walls" — and the tone walks cleanly from stranger → regular.
`npcforge play --npc mira_vesser --repeat-greet` prints all four
variants including the else-fallback.

---

## [0.6.0] — 2026-04-18

The state layer. First release that crosses from "style-sample generator"
to "engines can consume the output with state." Foundation for the next
four planned releases (relationships, knowledge gates, disposition,
appearance state) — all of which build on this.

### Added

- **`npcforge.state`** — new module defining `ProjectVariable` (enum /
  int / float / bool / string), `VariablesConfig`, `load_variables`,
  `format_variables_for_prompt` (LLM-facing block), `yarn_literal`, and
  `yarn_declare_block` (emits `<<declare $id = default>>` lines).
- **`variables.yaml`** per project — writers declare state variables
  once, every downstream generator reads them. The demo
  `examples/rusted_lantern/variables.yaml` ships `time_of_day`,
  `player_visits_mira`, and `disposition_mira`.
- **`gen_greetings`** tool (8th tool in `TOOL_REGISTRY`) — given an
  enum project variable (typically `time_of_day`), generates one
  in-character greeting per value per NPC and writes a Yarn node per
  NPC using `<<if $var == "value">>` / `<<elseif>>` / `<<else>>` /
  `<<endif>>`. Requires a declared enum variable; raises clearly if
  one is missing.
- **`npcforge gen greetings` CLI subcommand** with `--variable`,
  `--only-npcs`, `--concurrency`, `--dry-run`.
- **`NpcSheet.reacts_to: list[str]`** — opt-in list of variable ids
  this NPC cares about. Reserved for future state-aware dialogue
  generators; present now so future releases can add reactivity
  without another schema change.
- **`build_pipeline` now emits `<<declare>>`** blocks at the top of
  `world.yarn` when `variables.yaml` is present — generated Yarn
  compiles standalone.

### Changed

- `run_all` gains a `variables: list[ProjectVariable] | None = None`
  parameter (defaults unchanged; omitting it keeps v0.5 behaviour).
- Yarn `render_world_start_node` now accepts a `declare_lines:
  list[str] | None` keyword. Old callers still work.
- `build` automatically loads `variables.yaml` and passes it through.

### Tests — 83 passing (up from 61)

- `ProjectVariable` validators: enum default inference, default outside
  values rejected, empty values list rejected, numeric / bool sensible
  defaults.
- `load_variables` on the committed demo, plus graceful empty return
  when the file is missing.
- `yarn_literal` for every type, including escaped quotes.
- `yarn_declare_block` one-line-per-variable emission.
- `render_world_start_node` with declares: declares appear before the
  first option line (Yarn requires it); backward-compatible without.
- `render_greetings_node` emits the correct `if` / (N-1) × `elseif` /
  `else` / `endif` chain for N variants, metadata tags, every value
  as a literal.
- `NpcSheet.reacts_to` round-trips through YAML.

### Verified end-to-end on Gemini 2.5-flash

`gen greetings --only-npcs mira_vesser,gereth_blackstone` on a /tmp
copy of the Rusted Lantern produced 10 variants, all in voice:

Mira's five stayed distinctly time-flavoured while holding her accent
markers (drops "the" — *"Pour yourself a drink"*; never says "mine"):

- dawn:     *"First light. No easy coin this early."*
- morning:  *"Sun's barely up. What do you need?"*
- afternoon:*"Afternoon. Pour yourself a drink if you're thirsty."*
- dusk:     *"Dusk settling in. You here for trouble or a pint?"*
- night:    *"Kitchen's closed. Just drinks for now."*

Gereth's five carried the four-note hum and "twelve, one" trauma motif
in every single one — same character continuity the generator trio and
voice-scoring layers already demonstrated.

The two generated Yarn files each compile to a 5-branch `<<if>>` chain
keyed on `$time_of_day`. A Yarn Spinner 2 runtime plays them directly.

### Known limitation

`npcforge play` does not yet render greeting nodes (only walk-up +
barks). Ships in v0.6.1 alongside `repeat_greeting` mode.

---

## [0.5.0] — 2026-04-17

Writer-workflow polish — the three items the veteran-designer review
flagged as the highest-leverage gaps to close before the next schema
expansion.

### Added

- **`npcforge play`** — terminal playback of generated Yarn files. Reads
  the subset of Yarn Spinner 2 syntax npcforge emits; walks one branch
  (`--intent "threaten for info"`), every branch (no flag), or a bark
  library (`--bark reacts_to_hum`). Colourised per speaker (NPC vs
  Player), respects `NO_COLOR` and non-TTY output, optional `--tempo`
  pacing and `--wait` between lines.
- **Voice-consistency scoring** (opt-in via `build --score-voice`).
  One batched embedding call per NPC computes cosine similarity
  between every generated assistant turn and the NPC's
  ``sample_lines``; per-branch mean lands in
  `manifest.json -> npcs.<id>.walk_up.voice_scores[intent_id]`. The
  CLI prints the per-NPC average when scoring is enabled. Failures
  log and emit an empty score map; `voice_scoring_enabled` reflects
  whether scoring was requested.
- **Typed `Manifest` model** (`npcforge.manifest`) replacing the
  v0.4.x `dict[str, Any]` manifest. Downstream consumers (CI diffs,
  engine importers, writer dashboards) now get a stable Pydantic
  schema. Backward-compatible on the wire: the previous `"json": ...`
  field survives via a Pydantic alias (`json_path` on the model).

### Changed

- **CLI rename (non-breaking in practice):** `npcforge gen barks
  --for-npcs` → `--only-npcs`, matching `build --only-npcs`. The
  underlying `GenBarksInput.for_npcs` field is likewise `only_npcs` now.
- `BuildPipelineOutput.manifest` is now `Manifest`, not
  `dict[str, Any]`. Agents that parsed the dict need to switch to the
  typed attributes (or call `manifest.model_dump(by_alias=True)` for
  the old shape).

### Tests — 61 passing (up from 45)

- `Manifest` round-trip with the `json` alias (wire format preserved).
- Yarn parser against the committed Rusted Lantern `sample_output/`:
  walk-up option extraction, bark-variant extraction, comment stripping.
- Renderer output to `StringIO` (pure, colourless in non-TTY).
- `play_walk_up` / `play_barks` end-to-end against sample_output
  (no LLM).
- Voice-score math: `_cosine` identity / orthogonal / opposite / zero
  handling, `_normalise` clamping.

### Verified end-to-end against Gemini

Full `build --mode walk_up --only-npcs mira_vesser,gereth_blackstone
--score-voice` on a /tmp copy of the Rusted Lantern demo produced
sensible scores:

- Mira's canonical-voice intents (`threaten_for_info` 0.71,
  `bribe_for_info` 0.73) scored higher than her softer registers
  (`ask_about_local_events` 0.62).
- Gereth's entire branch set scored 0.67–0.78 — his distinctive
  four-note hum + "twelve, one" motif gives embeddings a stable
  anchor, so every branch stays close to his sample lines.

Elapsed 99s for 13 branches + embedding scoring on gemini-2.5-flash.

---

## [0.4.0] — 2026-04-17

The generator trio completion. Lore in, everything out.

### Added

- **`gen_intents`** tool — generate new `PlayerIntent` entries from the
  world profile + existing intent catalog. One LLM structured call per
  intent; duplicate ids silently dropped. Appended to
  `player_intents.yaml` (additive; never overwrites).
- **`gen_barks`** tool — propose new bark triggers for one or more NPCs.
  Emits `(id, description, n)` triples for each NPC, appended into
  `barks.yaml` under the right NPC entry. Actual bark *lines* are still
  produced by `build_pipeline --mode barks` — this tool only feeds the
  triggers.
- **`resolve_stubs`** tool — expand every `_generate: true` placeholder
  in `characters.yaml` into a full `NpcSheet`, honouring `role_hint`,
  `voice_hint`, and `name` seeds. Rewrites the YAML in place preserving
  top-level keys and the order of non-stub entries.
- **`NpcStub`** schema — the placeholder shape. Writers drop a minimal
  entry (id + hints + `_generate: true`); the loader separates stubs
  from full sheets. `load_npcs_with_stubs` returns both lists; strict
  `load_npcs` skips stubs so the pipeline is never confused.
- New CLI subcommands: `gen intents`, `gen barks`, `resolve stubs`.
  Each accepts `--dry-run` to preview without writing.
- New append helpers (`append_intents_to_yaml`,
  `append_bark_triggers_to_yaml`) with the same additive guarantees as
  `append_npcs_to_yaml`.

### Tools registry

Eight tools now (up from five): `infer_world_profile`,
`show_world_profile`, `list_npcs`, `gen_npcs`, `gen_intents`,
`gen_barks`, `resolve_stubs`, `build_pipeline`.

### Tests

- 45 passing (up from 37). New coverage for stub loading, intent /
  bark-trigger append round-trips, stub-only rewrite semantics, and
  the assertion that `load_npcs` silently skips stubs.

### Verified end-to-end

On a /tmp copy of the Rusted Lantern demo:

- `gen intents --n 3 --brief "more physically-grounded intents"` →
  added three `challenge_*` intents consistent with the setting.
- `gen barks --for-npcs mira_vesser --n 2` → added
  `warns_troublemaker` and `questions_deep`, both fitting Mira's
  gruff voice.
- Injected `{id: the_rival_tavernkeeper, _generate: true,
  role_hint: "..."}` stub → `resolve stubs` produced **Corvin Stone,
  proprietor of The Whispering Stag**, whose generated secret ties him
  to the Hawksreach Buyers faction from the world bible and whose
  `allowed_intents` include the freshly-added `challenge_statement`.
  Inter-content continuity from world profile + existing cast +
  just-generated intents cascaded correctly.

---

## [0.3.0] — 2026-04-17

Agent-ready architecture. The big shape change.

### Added

- **Tools layer** (`npcforge.tools`) — every capability is now a typed async
  function with Pydantic input/output models. CLI and MCP server both
  dispatch into one registry.
- **`WorldProfile`** auto-inferred from `lore/*.md` via one structured LLM
  call, cached to `<demo_dir>/.npcforge/world_profile.json`. Every
  downstream generator consumes it.
- **`gen_npcs`** tool — generate NPC sheets from lore + brief / roles,
  **additive** (never overwrites existing entries in `characters.yaml`).
  One LLM call per NPC; ids deduplicated automatically.
- **MCP server** (`npcforge-mcp` / `npcforge mcp`) — stdio transport,
  registers every tool. Auto-injects provider API keys from the
  environment so agents can invoke tools without shipping secrets
  through prompts. Requires `pip install 'npcforge[mcp]'`.
- **Five starter tools** in the registry: `infer_world_profile`,
  `show_world_profile`, `list_npcs`, `gen_npcs`, `build_pipeline`.
- New CLI subcommands: `world infer`, `world show`, `list-npcs`,
  `gen npcs`, `mcp`.
- New docs: [`docs/TOOLS.md`](docs/TOOLS.md),
  [`docs/MCP.md`](docs/MCP.md), and this file.

### Changed

- **CLI is subcommand-based.** `npcforge --demo-dir X --mode Y` is gone.
  Use `npcforge build --demo-dir X --mode Y` instead.
- `WorldProfile.canonical_terms` is a `list[CanonicalTerm]`, not
  `dict[str, str]` — Gemini's structured-output API rejects
  `additionalProperties` which the dict form requires.
- README, authoring guide, and starter instructions rewritten for the
  generators-first workflow.

### Tests

- 37 passing (up from 25). New coverage for the tools registry, JSON
  Schema shapes, `list_npcs`, `show_world_profile` round-trip,
  `gen_npcs` IO (id uniqueness, additive append, top-level-key
  preservation).

---

## [0.2.0] — 2026-04-17

The production-readiness pass guided by the veteran-designer review.

### Added

- **Bark generation** (`--mode barks`) — reactive 1-line NPC utterances
  for triggers (`combat_start`, `greet_patron`, `reacts_to_hum`, ...).
  One LLM structured call per variant, deduplicated on exact text.
  Emits `.yarn` with a `visited_count()` variant selector plus a
  machine-readable `.json`.
- **Voice ceiling** on `NpcSheet`: `vocabulary_ceiling`,
  `forbidden_words`, `accent_markers`. Injected into prompts and
  lint-checked after generation (inflections included — `fascinate`
  also flags `fascinated`, `fascinating`, `fascinates`).
- **`LintReport`** + `lint.md` — writer-facing summary of every
  forbidden-word hit, grouped by NPC.
- `--only-npcs` for iteration speed.
- `manifest.json` with content hashes, elapsed time, lint totals.
- Optional `ysc compile` validation when Yarn Spinner tooling is on
  `PATH`.

### Changed

- **Breaking:** `player_archetypes.yaml` renamed to
  `player_intents.yaml`. Intents are finer-grained than archetypes —
  12 in the demo. Each NPC whitelists valid intents via
  `allowed_intents`.
- `NpcSheet` carries `allowed_intents`, `vocabulary_ceiling`,
  `forbidden_words`, `accent_markers`.

### Infra

- New modules: `lint.py`, `validate.py`. Schemas cover `BarkLine`,
  `BarkTrigger`, `BarksConfig`, `VocabularyCeiling`.
- Pipeline iterates intents per NPC via `resolve_intents_for_npc`.
- `run_all` accepts `mode = walk_up | barks | all`.
- Bark model fallback to `afterimage.common.default_model_name`
  because `GeminiProvider` still ships with the deprecated
  `gemini-2.0-flash`.

### Examples

- **Night City 2077** — cyberpunk noir, 5 NPCs (Viktor Vector, Rue,
  Santiago Reyes, Splice, Rebecca Vale), 12 intents, 64 bark targets.
- **Saint Denis 1899** — frontier western, 5 NPCs (Mrs. Castille,
  Old Henri, Reverend Ames, Red Rufus Doyle, Agent Whiting), 12
  intents, 70 bark targets.
- `examples/AUTHORING.md` — step-by-step guide for any new world.

---

## [0.1.0] — 2026-04-17

Initial release.

### Added

- `ConversationGenerator`-backed walk-up dialogue with deterministic
  per-archetype branch coverage (one afterimage run per
  `(NPC, archetype)` pair with a single-persona pool).
- Yarn Spinner 2.0 exporter — one node per NPC with
  `-> [archetype]` options + a shared end node + a `world.yarn`
  master `Start` node.
- Rusted Lantern demo — 5 NPCs, 3 player archetypes.
- 10 smoke tests covering the exporter and YAML loaders.
