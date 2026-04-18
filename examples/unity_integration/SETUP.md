# SETUP — Unity + Yarn Spinner + npcforge in 5 minutes

Tested against Unity 2022.3 LTS and Yarn Spinner 2.4+.

## 1. Create a Unity project

New **2D (Core)** project in Unity 2022.3 LTS. Name doesn't matter.

## 2. Install Yarn Spinner

Open **Window → Package Manager**, click the `+` menu in the top-left,
pick **Add package from git URL…**, and paste:

```
https://github.com/YarnSpinnerTool/YarnSpinner-Unity.git
```

Wait for Unity to import it. You'll see a `Yarn Spinner` submenu in
**GameObject →** and `.yarn` files will now have a proper importer.

## 3. Drop in npcforge

Copy this repo's `examples/unity_integration/Assets/NpcForge/` directory
into your project's `Assets/` folder. Your hierarchy should look like:

```
YourProject/Assets/
├── NpcForge/
│   ├── Scripts/
│   └── Dialogue/
└── (Yarn Spinner, etc.)
```

Unity reimports automatically. You should see all four `.yarn` files
show up with the Yarn Spinner icon.

## 4. Make a Yarn Project

Yarn Spinner groups `.yarn` files into a project.

1. Right-click in `Assets/NpcForge/`, choose **Create → Yarn Spinner →
   Yarn Project**. Name it `RustedLantern`.
2. Double-click the created `RustedLantern.yarnproject` — the Inspector
   shows a list of source scripts.
3. Click **+** and add each of the four `.yarn` files from
   `Assets/NpcForge/Dialogue/`.
4. Click **Re-import** at the bottom of the Inspector. You should see a
   green "Compiles" message.

## 5. Make the scene

1. **GameObject → Yarn Spinner → Dialogue System**. This adds a
   `Dialogue Runner` plus a basic on-screen dialogue view (`Dialogue UI`).
2. Drag your `RustedLantern.yarnproject` into the Dialogue Runner's
   **Yarn Project** slot.
3. Create an empty GameObject named `NpcForge`. Add three scripts:
   - `NpcForgeDialogueController` — drag the scene's Dialogue Runner
     into its **Dialogue Runner** slot.
   - `NpcForgeStartup` — drag the controller AND the Dialogue Runner
     into their slots. Leave "Seed Directly" checked.
   - `TimeOfDayController` — drag the controller in.

## 6. Wire the buttons

Create a `Canvas` with five **Buttons** for time of day and one for
"Approach Mira".

**Time-of-day buttons** — on each button's `Button → On Click()` list,
drag the `NpcForge` GameObject in, then select one of:
`TimeOfDayController.SetDawn`, `SetMorning`, `SetAfternoon`, `SetDusk`,
`SetNight`.

**Approach Mira button** — add the `NpcApproachButton` script to it
(it auto-hooks the click handler). In the Inspector set:
- `Controller`: drag the `NpcForge` GameObject.
- `Npc Id`: `mira_vesser`.
- `Mode`: `Time Of Day Greeting`.

## 7. Press Play

Click any time-of-day button, then click Approach Mira. She greets you
in the right register. Click again — same greeting (time hasn't changed).
Click a different time, approach again — different line.

## 8. Try repeat-greeting

Duplicate your "Approach Mira" button. Rename it "Visit Mira Again". On
the duplicate's `NpcApproachButton`, change **Mode** to
`Repeat Greeting`. Click it repeatedly: you'll see the visit-gated arc
play out (stranger → recognised → regular → else-fallback).

## 9. Try walk-up

Duplicate again, rename to "Talk to Mira", set **Mode** to `Walk Up`.
Click it: you get the full 9-intent branching dialogue tree.

## Troubleshooting

**"Yarn Project fails to compile — unknown variable $time_of_day"** —
make sure `world.yarn` is in the Yarn Project's sources list. The
`<<declare>>` lines live there; without them Yarn refuses to reference
the variable.

**"Greetings always play the morning variant"** — you clicked a
time-of-day button but your setup ran before Yarn saw the declare.
Either (a) make sure `NpcForgeStartup.seedDirectly` is true, or (b) wire
your first button click to also run the Start node once.

**"No Yarn Spinner menu in GameObject"** — Unity didn't finish importing
the package. Check **Console** for errors; reimport via the Package
Manager if needed.

**"Dialogue runs but text shows as empty boxes"** — your default Yarn
Spinner `Dialogue UI` uses TMP (TextMeshPro). Import TMP Essentials via
**Window → TextMeshPro → Import TMP Essential Resources** once.
