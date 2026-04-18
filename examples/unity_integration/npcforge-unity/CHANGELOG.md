# Changelog

Versions follow the Unity package, not the npcforge Python package.

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
