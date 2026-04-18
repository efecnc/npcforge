# npcforge — Unity Editor package

**Generate characters, conversations, barks, and time-of-day greetings
from inside the Unity Editor.** Adds a `Tools → npcforge` menu and an
EditorWindow that shells out to the [npcforge](https://github.com/efecnc/npcforge)
CLI, then drops generated Yarn Spinner files straight into
`Assets/NpcForge/Dialogue/`.

- Full generator toolchain accessible from a panel: world profile, NPCs,
  intents, barks, greetings, repeat-greetings, walk-up dialogue builds.
- One-click sync into the current Unity project — Yarn Spinner imports
  the new files automatically on the next Editor refresh.
- Runtime glue scripts (`NpcForgeDialogueController`,
  `TimeOfDayController`, `NpcApproachButton`, `NpcForgeStartup`) ship
  inside the package; drop onto GameObjects and wire to UI buttons.

## Requirements

- Unity **2022.3 LTS** or later.
- [Yarn Spinner for Unity](https://github.com/YarnSpinnerTool/YarnSpinner-Unity)
  2.4+ installed **before** this package (it's the only hard dependency;
  we reference the `YarnSpinner.Unity` assembly).
- A working [npcforge](https://github.com/efecnc/npcforge) CLI on the
  machine running the Editor (`pip install -e <repo>` or install from
  PyPI once published).
- A Gemini / OpenAI / OpenRouter / local-LLM API key if you want to
  generate (sync-only workflows don't need one).

## Install

In Unity, open **Window → Package Manager**, click the `+` button,
pick **Add package from git URL…**, and paste:

```
https://github.com/efecnc/npcforge.git?path=examples/unity_integration/npcforge-unity
```

Unity imports the package. You'll see a new **Tools → npcforge**
menu once compilation finishes.

## First-time setup (~60 seconds)

1. **Open the panel:** `Tools → npcforge → Open Panel…` (shortcut
   `Ctrl/Cmd+Shift+Alt+N`).
2. **Point it at your npcforge project:** browse to the folder that
   contains `characters.yaml`, `variables.yaml`, `lore/`. (Not into the
   Unity project — into your npcforge *project* directory.)
3. **Set API key:** paste your `GEMINI_API_KEY` into the panel. Stored
   in EditorPrefs only; never written to the Unity project.
4. **Click "Build All"** — runs `npcforge build --mode all`. Log
   streams into the panel.
5. **Click "Sync now (to this Unity project)"** — copies generated
   `.yarn` + `lines.csv` into `Assets/NpcForge/Dialogue/`. Unity
   reimports automatically; Yarn Spinner compiles the new `.yarn` files.

That's it. Open a scene, drop a `DialogueRunner` + `NpcForgeDialogueController`,
press Play.

## What the panel exposes

**Settings**

| Field | What it does |
|---|---|
| npcforge binary | Absolute path or `npcforge` if on PATH |
| Project directory | Folder with `characters.yaml`, `variables.yaml`, `lore/` |
| GEMINI_API_KEY | Passed as an env var to every CLI call |
| Install runtime scripts on first sync | Only copies C# scripts if absent — safe to leave on |

**Generate**

| Button | CLI equivalent |
|---|---|
| World Profile (infer from lore) | `npcforge world infer --demo-dir X` |
| Generate NPCs (5) | `npcforge gen npcs --demo-dir X --n 5` |
| Build All | `npcforge build --demo-dir X --mode all` |
| Generate time-of-day greetings | `npcforge gen greetings --demo-dir X` |
| Generate repeat-greetings (n=3) | `npcforge gen repeat-greeting --demo-dir X --n 3` |

**Sync**

| Button | What it does |
|---|---|
| Sync now (to this Unity project) | `npcforge engine-sync --engine unity --project-dir <Unity root>` |
| Dry-run sync | Same as above with `--dry-run --verbose` |

## Runtime components (drop onto GameObjects)

All four live in the `Altai.NpcForge` namespace.

### `NpcForgeDialogueController`
Central wrapper around `Yarn.Unity.DialogueRunner`. Exposes
`SetTimeOfDay(value)`, `AdjustDisposition(npcId, delta)`,
`PlayTimeOfDayGreeting(npcId)`, `PlayRepeatGreeting(npcId)`,
`PlayWalkUp(npcId)`, `PlayStart()`. Assign a DialogueRunner in the
Inspector.

### `TimeOfDayController`
Five setter methods (`SetDawn`, `SetMorning`, …, `SetNight`) that wire
one-to-one from UI buttons to the controller.

### `NpcApproachButton`
Attach to a `UnityEngine.UI.Button`. Pick an `npcId` + a `DialogueMode`
(`TimeOfDayGreeting`, `RepeatGreeting`, `WalkUp`). Click triggers the
right generated Yarn node.

### `NpcForgeStartup`
Seeds default Yarn variables at scene load. Toggle `seedDirectly` to
pick between *"set variables in code"* (default) or *"run the Start
node once to fire `<<declare>>` lines"*.

## Conditional compilation

The Runtime assembly defines `NPCFORGE_HAS_YARN` when Yarn Spinner is
present (via `versionDefines` in the asmdef). If Yarn Spinner is
missing the scripts still compile — they log a warning instead of
crashing — so you can author scenes before installing Yarn Spinner.

## File layout the package writes

After a successful Build + Sync:

```
YourUnityProject/
├── Assets/
│   └── NpcForge/
│       └── Dialogue/
│           ├── world.yarn
│           ├── mira_vesser.yarn
│           ├── mira_vesser_bark_greet_patron.yarn
│           ├── mira_vesser_greet_time_of_day.yarn
│           ├── mira_vesser_repeat_greet.yarn
│           ├── ...
│           ├── lines.csv
│           └── .npcforge-sync.json   (sync marker — safe to gitignore)
```

`lines.csv` is the VO / localisation export (see npcforge's
`docs/TOOLS.md`): `line_id, npc_id, speaker, context, source_file,
emotion, intensity, duration_sec, text`. Drop this into Wwise / FMOD /
Unity Audio / your loc pipeline.

## Troubleshooting

**"npcforge: command not found"** — set the full path to the binary in
the panel's *npcforge binary* field. `pip install -e <repo>` places it
in the venv's `bin/` (or Scripts on Windows); use that absolute path.

**"Missing API key"** — the panel's GEMINI_API_KEY field is empty.
Sync-only workflows don't need it.

**"Unknown symbol DialogueRunner"** — Yarn Spinner for Unity isn't
installed. Install the `YarnSpinner-Unity` git package first.

**"Generated files don't appear in Unity"** — Unity hasn't refreshed.
The panel calls `AssetDatabase.Refresh()` after a successful run; if
you still don't see files, try `Assets → Refresh` manually or
right-click the Assets folder and *Reimport*.

## License

Apache-2.0. See [`LICENSE`](https://github.com/efecnc/npcforge/blob/main/LICENSE)
on the main repo.
