# Rusted Lantern — npcforge sample

The `rusted_lantern` demo adapted into a one-click Unity scene so you
can see npcforge's runtime components working together without writing
any wiring code.

## What's in the sample

| File | Purpose |
|---|---|
| `Editor/RustedLanternScaffold.cs` | One-click menu item that scaffolds a scene with a DialogueRunner, NpcForge controller + StateStore + Startup + TimeOfDayController, five TOD buttons, and an Approach-Mira button. |
| `Scripts/BarkOnProximity.cs` | Demonstrates wiring `NpcForgeBarkTrigger` to a simple distance-based proximity check. Drop onto an NPC and set its bark trigger id. |
| `Scripts/AutoSaveOnSceneUnload.cs` | Demonstrates `NpcForgeSaveLoad.Save()` on scene teardown — game-style autosave. |

## Importing

After installing the `dev.altai.npcforge` package via the Package Manager:

1. Click the package entry, then expand **Samples** in the right pane.
2. Click **Import** next to "Rusted Lantern Demo".
3. Unity copies the sample into
   `Assets/Samples/npcforge/<version>/Rusted Lantern Demo/`.

## Running

Prerequisite: run `npcforge build --mode all` + `npcforge engine-sync
--engine unity --project-dir <this Unity project>` at least once, so
the `Assets/NpcForge/Dialogue/` folder contains the five sample NPCs.

Then:

1. **`Tools → npcforge → Samples → Scaffold Rusted Lantern Scene`** —
   drops the full hierarchy into your active scene.
2. Assign a YarnProject to the DialogueRunner (or let the Asset
   Postprocessor auto-pick it if you only have one in the project).
3. Press **Play**.
4. Click a time-of-day button, then "Approach Mira".

## What you should see

- Mira greets differently per time of day (morning vs. dusk vs. night).
- Second approach of the same time returns the repeat-greeting variant.
- Entering the trigger area of any NPC with `BarkOnProximity` fires a
  bark (rotating through variants each entry).
- Disposition changes from player intents persist across saves if you
  wire `NpcForgeSaveLoad.Save()` into your UI.

## Known limitations

The scaffolded scene is authoring-focused — no visuals, no camera
choreography. Use it as wiring reference, not as a ready-to-ship demo.
