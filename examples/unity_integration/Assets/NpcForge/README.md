# Assets/NpcForge — drop-in folder

Everything in this directory is designed to be copied straight into a
Unity project's `Assets/` folder. Nothing here is Unity-serialized;
everything is human-readable.

## Scripts

| Script | Purpose |
|---|---|
| `NpcForgeDialogueController.cs` | Central wrapper around Yarn Spinner's `DialogueRunner`. Exposes `SetTimeOfDay()`, `PlayTimeOfDayGreeting(npcId)`, `PlayRepeatGreeting(npcId)`, `PlayWalkUp(npcId)`, `PlayStart()`. Wire this to one GameObject in your scene. |
| `TimeOfDayController.cs` | Plain UI binding — five public methods (SetDawn / SetMorning / ...) that the time-of-day buttons call. |
| `NpcApproachButton.cs` | Attach to a UI Button. Pick an NPC id + a `DialogueMode` in the Inspector; clicks run the right Yarn node. |
| `NpcForgeStartup.cs` | Seeds default Yarn variable values at scene load so scenes that skip the Start node still work. Toggle `seedDirectly` to choose between "set variables in code" and "run the Start node once". |

## Dialogue

| File | Generator that produced it | Purpose |
|---|---|---|
| `world.yarn` | `build --mode walk_up` (v0.6.0+) | Start node with `<<declare $time_of_day = "morning" as string>>` + `<<declare $disposition_mira = 50 as number>>` etc. |
| `mira_vesser.yarn` | `build --mode walk_up` | 9 intent branches (ask-about-locket, threaten, bribe, barter, accept-refuge, ...) |
| `mira_vesser_greet_time_of_day.yarn` | `gen greetings --variable time_of_day` | `<<if $time_of_day == "dawn">>` / `<<elseif>>` / `<<else>>` chain with 5 variants |
| `mira_vesser_repeat_greet.yarn` | `gen repeat-greeting --n 4` | `<<if visited_count == 0>>` / ... / `<<else>>` chain with 4 variants (stranger → recognised → regular → else-fallback) |

These are a snapshot. See the parent [`README`](../../README.md) for how
to regenerate against a modified world bible.

## What's deliberately missing

- No `.unity` scene file. Unity scene files are editor-authored and
  binary-ish; we prefer to document the scene setup in [`SETUP.md`](../../SETUP.md)
  so you can wire it up cleanly in your own project.
- No art, no audio, no animations. This is a dialogue-system demo.
- No save/load. Dialogue state resets every Play.
