# Changelog

Versions follow the Unity package, not the npcforge Python package.

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
