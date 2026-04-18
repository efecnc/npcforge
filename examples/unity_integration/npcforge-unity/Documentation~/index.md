# npcforge — Unity package documentation

This is the per-package documentation (Unity finds it in
`Documentation~/` and wires it into the Package Manager's
"Documentation" link). For the runtime-glue reference, installation
walkthrough, and troubleshooting, see
[`../README.md`](../README.md).

## One-screen overview

```
Tools → npcforge → Open Panel…
  ├── Settings
  │   ├── npcforge binary     (PATH or absolute)
  │   ├── Project directory   (where characters.yaml lives)
  │   ├── GEMINI_API_KEY      (EditorPrefs only)
  │   └── Install runtime scripts toggle
  ├── Generate
  │   ├── World Profile               → npcforge world infer
  │   ├── Generate NPCs (5)           → npcforge gen npcs --n 5
  │   ├── Build All                   → npcforge build --mode all
  │   ├── Generate time-of-day        → npcforge gen greetings
  │   └── Generate repeat-greetings   → npcforge gen repeat-greeting --n 3
  ├── Sync into this Unity project
  │   ├── Sync now                    → npcforge engine-sync --engine unity
  │   └── Dry-run sync                → same + --dry-run --verbose
  └── Log (streams CLI stdout/stderr line-by-line)
```

## Runtime API surface

Everything lives under `Altai.NpcForge`. Four MonoBehaviours you drag
onto scene GameObjects; no ScriptableObjects required.

| Component | Responsibility |
|---|---|
| `NpcForgeDialogueController` | One instance per scene; owns the Yarn `DialogueRunner` reference and exposes `SetTimeOfDay`, `PlayTimeOfDayGreeting`, `PlayRepeatGreeting`, `PlayWalkUp`, `PlayStart`, `AdjustDisposition`. |
| `TimeOfDayController` | UI-button helper; five setters (SetDawn / SetMorning / …). |
| `NpcApproachButton` | Attach to a Button; pick an `npcId` + `DialogueMode` (`TimeOfDayGreeting`, `RepeatGreeting`, `WalkUp`). |
| `NpcForgeStartup` | Seeds default Yarn variables at scene load. |

## Minimal scene wiring

1. Create a DialogueRunner: **GameObject → Yarn Spinner → Dialogue
   System**.
2. Create an empty GameObject `NpcForge` and add:
   - `NpcForgeDialogueController` (drag the DialogueRunner into its slot)
   - `NpcForgeStartup` (same DialogueRunner + the controller)
   - `TimeOfDayController` (drag the controller)
3. Create UI buttons for time-of-day and wire their `OnClick` to the
   `TimeOfDayController`'s five `Set*` methods.
4. Create an `Approach Mira` button; attach `NpcApproachButton`, set
   `npcId = "mira_vesser"`, `mode = TimeOfDayGreeting`.

Press Play, click a time, click Approach Mira. She greets you in the
matching variant.

## Troubleshooting

See [`../README.md#troubleshooting`](../README.md#troubleshooting).

## How this package differs from `examples/unity_integration/Assets/NpcForge/`

That older folder is a **drop-in copy** — for projects that want the
runtime glue without installing a UPM package. This UPM package is the
full Editor integration: menu items, panel, CLI subprocess, sync,
progress streaming. Both consume the same generated `.yarn` files.
