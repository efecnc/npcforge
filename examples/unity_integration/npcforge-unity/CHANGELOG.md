# Changelog

Versions follow the Unity package, not the npcforge Python package.

## [1.2.0] — 2026-04-19

Campaign-scale character arcs in the runtime, matching Python's
v0.10.0 release. NPCs now evolve across the whole campaign, not
just within a single scene, driven by a structured evaluator over
the v0.9 MemoryStore + FactionStanding components.

### Added — Runtime

- **`NpcForgeArcTracker`** — per-NPC MonoBehaviour that holds an
  ordered list of `NpcForgeArcStage`s and computes which ones are
  currently active given the memory store and faction standings.
  - `ActiveStages()` returns the cumulative stack (stage N active
    implies stages 0..N-1 too) so callers can compose voice shifts
    for presentation logic.
  - `NewlyLatchableStages()` returns stages whose trigger is newly
    satisfied; `CommitLatches()` persists those back into the
    memory store as `arc_latched` events and fires `onStageLatched`.
  - `ImportArcJson(string)` accepts the Python side's
    `NpcArc.model_dump_json()` so one source of truth can drive
    both sides.
- **`NpcForgeTriggerSpec`** — serialised mirror of Python's
  `TriggerSpec`: `min_pivotal_events`, `min_total_events`,
  `required_event_types`, `min_standing` / `max_standing` per
  faction, `custom_condition` (narrative gate the runtime ignores
  and the LLM applies).
- **`NpcForgeArcStage`** / **`NpcForgeArcSpec`** — data containers
  with JSON layouts compatible with the Python schemas.

### Verified

- 49 / 49 EditMode tests pass in Unity 6000.4.3f1 — 39 prior plus
  10 new covering baseline activation, min_total_events triggers,
  faction-shared event folding, standing floors, latch persistence
  + event firing, latch records excluded from counting, always-
  active baseline skipped by NewlyLatchable, JSON import.
- Python-side 211 tests pass; the JSON shape shared between
  engines is exercised by both suites.

### Upgrading from 1.1.0

Remove + re-add from the Package Manager git URL. The new tracker
component is additive; existing memory and faction-standing
components are untouched. Typical wiring: drop one
`NpcForgeArcTracker` per major NPC, assign its `NpcForgeMemoryStore`
and (if any stage gates on faction) `NpcForgeFactionStanding`
references, and either author stages in the Inspector or paste the
JSON from `npcforge arc show --npc X --json`.

---

## [1.1.0] — 2026-04-18

Social graph foundation in the runtime, matching the v0.9.0 Python
release. Two new runtime components give scenes and gameplay code a
way to remember what happened and track how the player stands with
each faction — and the formats are JSON-interop with the Python side
so one store can feed both.

### Added — Runtime

- **`NpcForgeMemoryStore`** — log of `(turn, npc_id, event_type,
  summary, salience, faction_id)` records, persisted as JSON under
  `Application.persistentDataPath`. Salience drives decay (trivial
  prunes after 3 turns, notable after 10, pivotal stays forever).
  `ForNpc(id, primaryFactionId, secondaryFactionId)` folds the NPC's
  own events with faction-shared ones and deduplicates double-faction
  hits. `SummarizeForNpc` renders the same prompt block the Python
  generator would inject, so runtime + next-generation stay in sync.
  JSON format matches `src/npcforge/memory.py` byte-for-byte — one
  store can feed both.
- **`NpcForgeFactionStanding`** — player standing per faction on a
  clamped -100..+100 scale with five named tiers (Hostile / Wary /
  Neutral / Friendly / Trusted). `AdjustStanding` fires two
  `UnityEvent`s: `onStandingChanged` on every delta with full before/
  after payload, `onTierChanged` only when crossing a threshold so
  UI can cheaply ignore within-tier noise. `IsAlly` / `IsRival`
  convenience predicates drive scene-setup logic.

### Verified

- 39 / 39 EditMode tests pass in Unity 6000.4.3f1 — 23 pre-existing
  plus 16 new for memory (decay horizons, faction folding, dedup,
  JSON round-trip) and faction standing (tier thresholds, event
  firing, clamping, persistence).
- Python-side 193 / 194 tests pass, covering the cross-language
  schema parity.

### Upgrading from 1.0.2

Remove + re-add from the Package Manager git URL. The new components
are additive — nothing in the 1.0.x runtime changed. To use them:

1. Drop `NpcForgeMemoryStore` and / or `NpcForgeFactionStanding` onto
   a scene-root GameObject that survives reloads (or a dedicated
   persistent bootstrap GO).
2. From gameplay code, call `Record(...)` / `AdjustStanding(...)` at
   narrative beats.
3. Copy `memory.json` into your npcforge project's demo dir
   (`<demo>/memory.json`) so `npcforge gen scene` sees the same
   history the runtime does.

---

## [1.0.2] — 2026-04-18

Second validation pass — caught by running a 23-test NUnit EditMode
suite plus a window-instantiation harness live inside the Editor.
All 23 tests now pass; every EditorWindow + CustomEditor + Asset
Postprocessor opens and teardown-s without throwing.

### Fixed

- **`NpcForgeStateStore` silently dropped writes when no DialogueRunner
  was assigned.** `SetString` / `SetNumber` / `SetBool` all had
  `if (dialogueRunner == null) return;` inside the `NPCFORGE_HAS_YARN`
  guard — which meant the snapshot dictionary was never updated and
  `OnVariableChanged` never fired. Symptoms: the State Inspector stayed
  empty even after writes, save/load round-trips shipped empty JSON,
  and `AddClamped` always read 0 as the base. Reshaped the guard to
  only skip the Yarn-side SetValue — snapshot + event fire always
  run. `Get*` now also falls back to the snapshot cache so headless
  edit-mode use works.
- **`NpcForgeSaveLoad.onSaved / onLoaded / onLoadMissing` could be
  null** in edit-mode tests where Unity's serializer didn't auto-
  instantiate the UnityEvent fields. Added explicit
  `= new UnityEvent()` initializers so AddListener is always safe.

### Verified (not changed)

- 23 / 23 EditMode tests green: YarnParser (8) + SaveLoad (5) +
  YamlReader (5) + StateStore/Bark (5).
- All 6 EditorWindows open and close cleanly in batchmode:
  NpcForgeWindow (IMGUI), NpcForgePanelUIT, NpcForgeBrowserWindow,
  NpcForgeStateInspectorWindow, NpcForgeDialoguePreviewWindow,
  NpcForgeRelationshipGraphWindow.
- Both CustomEditor instantiate cleanly: NpcForgeStateStoreInspector,
  NpcForgeBarkTriggerInspector.
- NpcForgeYarnAssetPostprocessor.ResolveYarnProjectPath executes
  without error.

### Upgrading from 1.0.1

Remove + re-add from the Package Manager git URL. If you built a
scene against 1.0.1 where `NpcForgeStateStore` writes appeared to be
no-ops, those writes now actually take effect — expect real state
transitions where previously you had silent drops.

---

## [1.0.1] — 2026-04-18

Validated against **Unity 6 (6000.4.3f1)** + **Yarn Spinner for Unity
2.4.2** in a clean batchmode compile: **zero errors, zero warnings**,
both the Runtime and Editor assemblies ship.

### Fixed

- **`NPCFORGE_HAS_YARN` was never defined.** The Runtime asmdef's
  `versionDefines` used `"name": "YarnSpinner"` — but Unity matches
  against the *package* name, not an assembly name, so the symbol
  never activated. Every `#if NPCFORGE_HAS_YARN` block (and there
  are many) compiled to stubs that silently did nothing. Changed to
  `"name": "dev.yarnspinner.unity"` — Yarn-dependent runtime code now
  actually executes. Affects every prior version (0.1.0 → 1.0.0).
- **Duplicate "Tools → npcforge → Open Panel…" menu item.** Both
  `NpcForgeMenu` and `NpcForgeWindow` declared the attribute, which
  Unity logs as a collision. Removed the redundant declaration in
  `NpcForgeWindow`; `NpcForgeMenu` keeps the entry (with the
  `Ctrl/Cmd+Shift+Alt+N` shortcut) and routes to `NpcForgeWindow.Open()`.
- **Unity 6 deprecations** — `FindObjectsOfType` /
  `FindObjectOfType` in `NpcForgeStateInspectorWindow` → the modern
  `FindObjectsByType<T>(FindObjectsInactive.Exclude)` /
  `FindAnyObjectByType<T>()`.
- **Unused serialized fields** — `NpcForgeStartup.defaultDisposition`
  (never referenced) removed; `defaultTimeOfDay` moved inside
  `#if NPCFORGE_HAS_YARN` so it no longer triggers CS0414 when
  Yarn Spinner isn't installed.
- **Unused locals** — `nestedKey` and `previousKeyBeforeContinuation`
  in `NpcForgeYamlReader` (dead since v0.2.0) deleted.

### Upgrading from 1.0.0

Remove + re-add from the Package Manager git URL. Note that if you
were using an earlier version under the (quiet) assumption that the
Yarn wiring "just worked," you may now see actual dialogue behavior
for the first time. Variable writes, time-of-day changes, bark
triggers, and walk-up nodes all now round-trip through Yarn.

---

## [1.0.0] — 2026-04-18

First production-intended release. Completes the seven roadmap items
from 0.2.0 and ships as an opinionated Unity dialogue engine rather
than a CLI wrapper: every step of the authoring loop has a dedicated
Editor surface, runtime components cover save/load, and the
Postprocessor removes the last piece of manual wiring.

### Added — Editor

- **`NpcForgeYarnAssetPostprocessor`** — watches
  `Assets/NpcForge/Dialogue/**/*.yarn` and force-reimports the
  configured Yarn Project whenever new `.yarn` files land from
  `engine-sync`. Auto-selects the only YarnProject in the project when
  the user hasn't picked one yet; persists the choice.
- **`Tools → npcforge → Dialogue Preview…`** — parse-and-step viewer
  for every generated `.yarn` file. Classifies node kind (walk-up,
  bark rotation, enum greeting, repeat greeting, world start) and
  renders variants inline. Pure static parsing — no Play mode needed.
  Ships with `NpcForgeYarnParser`, a C# port of the Python
  `npcforge.play` parser covering every Yarn construct npcforge emits.
- **`Tools → npcforge → Relationship Graph…`** — IMGUI graph view of
  the cast's relationship network. Circular layout, curved edges per
  direction, colour-coded by opinion tone (ally / hostile / neutral),
  click-to-focus filtering, zoom + pan.
- **`Tools → npcforge → Open Panel (UI Toolkit)…`** — modern
  UI Toolkit counterpart to the IMGUI panel. Full settings / generate /
  sync / log parity with the classic panel. Lives alongside, not
  instead of, the IMGUI window.
- **Custom Inspectors** — `NpcForgeStateStoreInspector` shows a live
  snapshot table in Play mode with typed quick-set fields; 
  `NpcForgeBarkTriggerInspector` adds a Fire-now button and an animated
  cooldown progress bar plus clickable trigger-id suggestions.

### Added — Runtime

- **`NpcForgeSaveLoad`** — MonoBehaviour with `Save()`, `Load()`,
  `DeleteSlot()` methods wireable to UI buttons via UnityEvents.
  Serializes every Yarn variable it can see to diff-friendly JSON under
  `Application.persistentDataPath`. Uses reflection into
  `VariableStorage.GetAllVariables` for complete coverage; falls back
  to `NpcForgeStateStore.Snapshot` when unavailable. Slot naming is
  supported (`default`, `slot2`, …).
- `NpcForgeBarkTrigger` exposes `NextFireTime` and `CooldownSeconds`
  public getters so the custom inspector can draw an accurate
  cooldown bar without reflection.

### Added — Samples

- **`Samples~/RustedLantern`** — importable via Package Manager → Samples
  → Import. Contains:
  - `RustedLanternScaffold` — one-click menu that delegates to the
    core Scene Setup command so the sample scaffolding stays in sync.
  - `BarkOnProximity` — example distance-based proximity bark trigger.
  - `AutoSaveOnSceneUnload` — demonstrates `NpcForgeSaveLoad.Save()`
    wired to `OnApplicationPause` / `OnApplicationQuit` / `OnDestroy`.
  - A standalone README covering install + run steps.

### Changed

- `package.json` — `version` bumped 0.2.0 → 1.0.0, `description`
  rewritten to reflect the engine-scale scope, `samples` array
  declared for the Rusted Lantern demo.
- Meta files regenerated — the package now ships .meta for every new
  Editor + Runtime source file plus the Samples~ tree.

### Compatibility

- Unity 2022.3 LTS or later. UI Toolkit panel uses APIs that have been
  stable since 2022.3.
- Yarn Spinner for Unity 2.4+ (2.3 may work; the Asset Postprocessor's
  YarnProject t-filter and reflection fallback should cover both).
- No new package dependencies.

### Upgrading from 0.2.x

Remove the package from Package Manager, re-add it from the same git
URL. All prior APIs (`NpcForgeDialogueController`, `NpcForgeStateStore`,
`NpcForgeBarkTrigger`, `TimeOfDayController`, `NpcApproachButton`,
`NpcForgeStartup`) stay binary-compatible; new types (`NpcForgeSaveLoad`,
the inspectors, the new windows) are additive.

---

## [0.2.0] — 2026-04-18

First pass toward "npcforge as an advanced Unity engine" — two new
Editor windows, two new runtime components, one-click scene setup,
and a CLI progress bar.

### Added — Editor

- **`Tools → npcforge → NPC Browser…`** — lists every NPC declared in
  the project's `characters.yaml` with full detail view: voice,
  motivations, secret, speech quirks, sample lines, forbidden words,
  accent markers, allowed intents, reacts-to, relationships,
  knowledge gates, state evolution. Searchable, read-only, reloads on
  focus. Ships with `NpcForgeYamlReader` — a minimal indent-aware YAML
  reader tailored to the npcforge schema (no YamlDotNet dependency).
- **`Tools → npcforge → State Inspector…`** — live Yarn-variable
  viewer. Polls every `DialogueRunner` in the scene at 5 Hz during
  Play mode plus folds in `NpcForgeStateStore` snapshots. Values
  editable in Play mode — changes flow back through the StateStore.
  Uses reflection for `GetAllVariables` so the package stays compatible
  across Yarn Spinner versions.
- **`Tools → npcforge → Create Dialogue Scene Setup`** — one-click
  scaffolding. Drops a complete `NpcForge_Setup` hierarchy into the
  active scene: DialogueRunner + NpcForge GameObject (controller +
  StateStore + Startup + TimeOfDayController, auto-wired via
  reflection) + Canvas with five time-of-day buttons + sample Approach
  Mira button. Users only need to assign a YarnProject to finish.

### Added — Runtime

- **`NpcForgeStateStore`** — typed wrapper around Yarn's
  VariableStorage. `GetString` / `SetString` / `GetNumber` / `SetNumber`
  / `GetBool` / `SetBool` / `AddClamped` / `SetMany`. Fires
  `OnVariableChanged(name, value)` on every write. Keeps a snapshot
  of observed values for Editor inspection.
- **`NpcForgeBarkTrigger`** — fire a bark library from any gameplay
  event. Three entry points: public `TriggerBark()` for UnityEvents /
  animation events / code, `FireFor(triggerId)` for code-driven picks,
  optional `OnTriggerEnter` / `OnTriggerEnter2D` with tag whitelist.
  Configurable cooldown. Never interrupts an in-flight scripted
  conversation.

### Changed

- `NpcForgeCliRunner` displays an `EditorUtility.DisplayProgressBar`
  while a subprocess is running and clears it on completion — Editor
  UI no longer looks idle during 90-second generations.
- `NpcForgeMenu` gets a logical separator before the new windows.
- `package.json` version bumped 0.1.1 → 0.2.0.

### Meta files

Regenerated via `scripts/gen_unity_meta.py`; 21 `.meta` files now
ship (was 15). New: browser + state-inspector + scene-setup + yaml-reader
+ state-store + bark-trigger.

### Not in 0.2.0 (roadmap)

- UI Toolkit rewrite of the main panel (still IMGUI).
- Visual node editor for relationships / dialogue graphs.
- In-Editor dialogue preview without entering Play mode.
- Asset postprocessor that auto-wires new `.yarn` files into a default
  Yarn Project.
- Custom Inspectors for the runtime components beyond Unity defaults.

### Upgrading from 0.1.x

Remove from Package Manager, re-add from the same git URL. Unity
reimports cleanly with the regenerated `.meta` files.

---

## [0.1.1] — 2026-04-18

Fix: ship `.meta` files for every package asset so Unity stops
warning "no meta file, but it's in an immutable folder" on import.

### Added

- Deterministic `.meta` sidecars for all 15 package assets (folder +
  file meta for Runtime/, Editor/, asmdefs, C# scripts, README,
  CHANGELOG, package.json). GUIDs derived from `md5("dev.altai.npcforge/<rel-path>")`
  so they're identical across checkouts and byte-stable under
  regeneration.
- `scripts/gen_unity_meta.py` in the main repo — one-command
  regeneration of every meta if the package's file list changes in
  a future release.

### Upgrading from 0.1.0

If you already installed 0.1.0 and saw the "no meta file" warnings:
remove the package from Package Manager, then re-add it from the git
URL. Unity picks up the committed `.meta` files on the fresh import.

---

## [0.1.0] — 2026-04-18

Initial release. Adds a `Tools → npcforge` menu, an EditorWindow that
shells out to the npcforge CLI, and four runtime glue scripts
(`NpcForgeDialogueController`, `TimeOfDayController`,
`NpcApproachButton`, `NpcForgeStartup`).

### Added

- `Tools → npcforge` menu:
  - **Open Panel…** (shortcut `Ctrl/Cmd+Shift+Alt+N`)
  - **Quick Sync to This Project**
  - **Build All (walk-up + barks + lines.csv)**
  - **Documentation** (opens the main npcforge README)
- `NpcForgeWindow` — IMGUI EditorWindow with Settings, Generate, Sync,
  and Log sections. Streams CLI stdout/stderr line-by-line.
- `NpcForgeCliRunner` — background-thread subprocess runner with
  main-thread callback dispatch. No freezing of the Editor UI during
  multi-minute generations.
- `NpcForgePreferences` — per-project EditorPrefs scoped by
  `PlayerSettings.productGUID`. Remembers npcforge binary path,
  project directory, API key, and install-scripts toggle.
- Runtime package (`Altai.NpcForge` assembly):
  - References `YarnSpinner.Unity`; `versionDefines` gate a
    `NPCFORGE_HAS_YARN` symbol so code compiles cleanly when Yarn
    Spinner is missing.
  - `rootNamespace` set to `Altai.NpcForge`.
- Editor package (`Altai.NpcForge.Editor` assembly) — `includePlatforms:
  ["Editor"]`, references only the Runtime assembly.
- Documentation~/index.md bundled with the package.

### Requirements

- Unity 2022.3 LTS or later.
- Yarn Spinner for Unity 2.4+ installed separately.
- npcforge Python CLI available on PATH (or absolute path configured
  in the panel).
