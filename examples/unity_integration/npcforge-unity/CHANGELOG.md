# Changelog

Versions follow the Unity package, not the npcforge Python package.

## [1.9.0] — 2026-04-19

Runtime relationship trajectory, matching Python v0.17.0 — the
**final roadmap item** for npcforge's NPC-personality stack. Each
NPC carries a per-NPC score curve with named waypoints (stranger →
tolerated → trusted → confidant → intimate, or whatever the writer
names). Score moves with memory events; knowledge and register
unlock per waypoint. Mira slow-builds; Kess fast-flips; each NPC
authors their own shape.

### Added — Runtime

- **`NpcForgeRelationshipTrajectory`** — per-NPC MonoBehaviour
  reading the shared memory store, accumulating scored deltas per
  event_type, returning the current waypoint.
- **`DefaultEventDeltas`** mirrors Python's `DEFAULT_EVENT_DELTAS`
  across 16 event types.
- Per-NPC `eventDeltas` list in the Inspector OVERRIDES the
  defaults for that NPC (set `gift_given: 0` to make a particular
  NPC immune to bribery; set `secret_shared: 0.5` to make another
  warm faster on confidences).
- `decayPerTurn` scales magnitudes down as memories age; clamped
  so decay never flips an event's sign.
- `onWaypointChanged(oldId, newId)` UnityEvent fires on transition
  — wire to music, UI glyphs, portrait swaps.
- `SummarizeForPrompt()` renders the block shape Python emits, with
  the same `Never say the waypoint name aloud` guard clause.

### Verified

- 130 / 130 EditMode tests pass in Unity 6000.4.3f1 — 116 prior
  plus 14 new covering empty-store baseline, gift-nudge accumulation,
  threshold crossing + reversal, unknown-event no-op, per-NPC
  override, decay magnitude reduction + sign clamp, faction
  folding, top-events abs sort, waypoint-transition event firing
  (including the initial `""` → `"stranger"` load), summary
  empty-below-lowest case, and summary exposing unlocked knowledge.
- Python 332 tests still pass; the score math matches on both
  sides for the same input.

### Upgrading from 1.8.0

Remove + re-add from the Package Manager git URL. Typical wiring:

1. Drop `NpcForgeRelationshipTrajectory` on the NPC GameObject.
2. Configure `npcId`, `primaryFactionId`, and the shared
   `memoryStore` reference.
3. Author waypoints in the Inspector (or paste from the NPC's
   characters.yaml `trajectory:` block).
4. Optionally author `eventDeltas` overrides + a `decayPerTurn`.
5. Call `Evaluate()` at scene transitions; hook `onWaypointChanged`
   for side effects; splice `SummarizeForPrompt()` into improv
   context.

---

## [1.8.0] — 2026-04-19

Runtime ethical reader, matching Python v0.16.0. Each NPC can carry
a hidden ethical profile (honor_bound / pragmatic / self_serving /
zealot / communal); the reader judges the player's accumulated
memory events through THAT NPC's values and produces the prompt
block observer NPCs use to shift tone without narrating the
judgment.

### Added — Runtime

- **`NpcForgeEthicalProfile`** — serialised weight vector over the
  five axes (sliders in the Inspector), matching Python's schema.
- **`NpcForgeEthicsReader`** — per-NPC MonoBehaviour. Reads from
  `NpcForgeMemoryStore` (direct + faction-shared events), weights
  each event's axis-delta by this NPC's stance, returns an
  `NpcForgeEthicalReading` (score, per-axis contributions,
  top-weighted events).
- **`DefaultEventJudgements`** — static per-event-type × per-axis
  delta table mirroring Python's `DEFAULT_EVENT_JUDGEMENTS` line-
  for-line (16 event types: hostile, honorable, transactional,
  curious, theatrical).
- **`SummarizeReading()`** — produces the prompt block with
  verdict (net approving / disapproving / mixed), dominant axes,
  top events, and the same closing guard clause Python emits ("no
  lectures, no moralising, no listing of transgressions").

### Verified

- 116 / 116 EditMode tests pass in Unity 6000.4.3f1 — 105 prior plus
  11 new (profile weight + dominant axes, evaluator: empty-store
  no-op, zealot-vs-pragmatic divergence, honor-bound approval,
  faction folding, unknown-event silence, top-events abs-sort,
  summariser empty + populated, verdict threshold classification).
- Python 314 tests still pass; the judgement table values match on
  both sides for every event type covered.

### Upgrading from 1.7.0

Remove + re-add from the Package Manager git URL. Typical wiring:

1. Drop `NpcForgeEthicsReader` on each NPC GameObject that should
   judge the player.
2. Set the profile axis sliders in the Inspector (or leave at 0
   for NPCs with no ethical stance — the reader returns an empty
   block for those).
3. Wire the `memoryStore` reference to the NPC's
   `NpcForgeMemoryStore` + set `npcId` + faction ids.
4. Before a scripted dialogue or improv request, call
   `reader.SummarizeReading()` and splice the result into the
   prompt context alongside `SummarizeForObserver` (from the
   player profile).

---

## [1.7.0] — 2026-04-19

Runtime unseen-character registry, matching Python v0.15.0. Tracks
mentioned-but-never-met NPCs across sessions so when the player
finally encounters one, the offline `npcforge unseen materialize`
CLI can generate a sheet consistent with every recorded mention.

### Added — Runtime

- **`NpcForgeUnseenRegistry`** — MonoBehaviour holding
  `NpcForgeUnseenCharacter[]` slots with declared-up-front
  canonical ids and accumulating `NpcForgeMentionRecord` entries.
  - `Declare(canonicalId, hint, role)` — idempotent slot creation
  - `RecordMention(canonicalId, sourceNpcId, context, turn, scene?)` —
    appends; throws if slot not declared (typos fail loud)
  - `StillUnseen(canonicalId)` / `MarkMaterialised(canonicalId, newNpcId)` —
    slot lifecycle
  - `onSlotDeclared` / `onMentionRecorded` UnityEvents
- **Byte-compatible JSON with Python** — Unity emits Python's
  dict-keyed `{"characters": {...}}` shape by hand and reads it back
  with a small regex-based parser (same pattern NpcForgePlayerProfile
  uses). One registry file feeds both runtimes.

### Verified

- 105 / 105 EditMode tests pass in Unity 6000.4.3f1 — 95 prior plus
  10 new covering declare idempotency, record-requires-declare,
  event firing, still-unseen lifecycle, full save/load round-trip,
  reading a Python-emitted file, missing-file no-op, escaped-quote
  tolerance in the parser.
- Python 296 tests still pass; the JSON shape round-trips cleanly
  between the two runtimes.

### Upgrading from 1.6.0

Remove + re-add from the Package Manager git URL. Typical wiring:

1. Drop `NpcForgeUnseenRegistry` on a persistent GameObject.
2. At game start, call `Declare("borin_of_grindholt", "Borin",
   "dwarven foreman")` for each character your writers know they'll
   introduce by name later.
3. When scripted dialogue or improv replies mention them, call
   `RecordMention(canonicalId, sourceNpcId, context, turn)` so the
   slot accumulates canon.
4. When it's time to materialise — after player encounters the
   character — run `npcforge unseen materialize --id <id> --commit`
   on the Python side (reads the same JSON Unity wrote).
5. Back in Unity, call `MarkMaterialised(canonicalId, newNpcId)` to
   stop accumulating mentions against a now-realised slot.

---

## [1.6.0] — 2026-04-19

Runtime voice lens tracking, matching Python v0.14.0. An NPC's voice
isn't one register per character — it's a composition of the base
voice plus however many situational modifiers are active
(state / audience / cultural lenses). This component tracks which
lenses are on and composes the prompt block the improv client
splices into its system prompt.

### Added — Runtime

- **`NpcForgeVoiceLensTracker`** — per-NPC MonoBehaviour holding
  `NpcForgeVoiceLensSpec[]` authored in the Inspector (or imported
  from Python's characters.yaml via export tooling) plus a set of
  currently-active lens ids.
- **`ActivateLens` / `DeactivateLens` / `ToggleLens` /
  `SetActiveLenses`** — activation API. Unknown ids are silent
  no-ops; events fire only on genuine state changes.
- **`onLensActivated` / `onLensDeactivated`** UnityEvents so UI,
  audio routing (the music / SFX kind, not dialogue audio), and
  analytics can hook transitions.
- **`SummarizeActive()`** — renders the same block shape Python's
  `_render_voice_lenses` produces, including deduplicated extra
  forbidden words + accent markers across active lenses.

### Verified

- 95 / 95 EditMode tests pass in Unity 6000.4.3f1 — 86 prior plus
  9 new covering unknown-lens no-op, idempotent activate/deactivate,
  toggle flipping, SetActiveLenses replace semantics with
  transition events, declaration-order iteration, summary empty
  case, multi-lens render shape, and dedup of forbidden-words +
  accent markers across overlapping lens declarations.

### Upgrading from 1.5.0

Remove + re-add from the Package Manager git URL. To use:

1. Drop `NpcForgeVoiceLensTracker` on the NPC GameObject.
2. Author lens specs in the Inspector or paste from
   `characters.yaml` (one lens per list entry, matching the Python
   VoiceLens shape: id, label, kind, cadence_shift,
   extra_forbidden_words, extra_accent_markers).
3. From gameplay code, call `ActivateLens("tipsy")` when the
   character pours a third drink, `ActivateLens("inspector_present")`
   when the inspector walks in, etc.
4. Before calling `NpcForgeImprovClient.RequestImprov`, splice
   `tracker.SummarizeActive()` into the prompt context (the
   improv client already accepts a pre-composed system prompt via
   `ComposeSystemPrompt` + delegate).

---

## [1.5.0] — 2026-04-19

Runtime player modeling, matching Python v0.13.0. Observer NPCs can
now notice the player's conversational pattern across many
encounters — aggressive / patient / deceptive / curious / theatrical /
loyal — without an LLM call in the hot path.

### Added — Runtime

- **`NpcForgePlayerProfile`** — MonoBehaviour tracking per-axis
  weights in [0, 1], persisted to
  `Application.persistentDataPath/npcforge_player_profile.json` in a
  layout byte-compatible with the Python side. Python and Unity can
  read each other's file.
- **`DefaultAxisDeltas`** — static map from event_type → axis deltas,
  mirroring Python's DEFAULT_AXIS_DELTAS line-for-line. Customise in
  both places.
- `RegisterEvent(eventType, turn?)` applies deltas, clamps to [0, 1],
  updates the monotonic turn stamp, fires `onAxisChanged(axis, value)`.
- `SummarizeForObserver()` produces the same prose block Python's
  observers receive — returns empty string when no trait crosses the
  default 0.25 threshold, so early-campaign NPCs don't narrate
  phantom patterns.
- `TopTraits`, `BandFor` helpers for UI (status bars, glyphs).

### Verified

- 86 / 86 EditMode tests pass in Unity 6000.4.3f1 — 73 prior plus
  13 new covering RegisterEvent math, clamp, unknown-event no-op,
  monotonic turn, onAxisChanged firing count, TopTraits filtering
  + ordering, BandFor thresholds, summariser (empty / above-
  threshold / unknown-axis-fallback), Python dict-shape JSON parse,
  save/load round-trip.
- Python 270 tests pass; the axis-delta map is live-verified on
  both sides against the same event_types.

### Upgrading from 1.4.0

Remove + re-add from the Package Manager git URL. To wire player
modeling:

1. Drop `NpcForgePlayerProfile` onto a persistent GameObject (same
   bootstrap GO as the memory store).
2. Whenever gameplay code calls
   `NpcForgeMemoryStore.Record(..., eventType: "threat", ...)`,
   also call `NpcForgePlayerProfile.RegisterEvent("threat")`.
3. For observer NPCs, fetch
   `profile.SummarizeForObserver()` and feed it into the improv
   request prompt before calling `NpcForgeImprovClient.RequestImprov`.

---

## [1.4.0] — 2026-04-19

Lore-consistent improvisation runtime, matching Python v0.12.0. When
the player asks an NPC something that wasn't pre-scripted, the client
retrieves relevant lore paragraphs, composes a prompt, and hands it
to a user-supplied LLM delegate. Model-agnostic by design — npcforge
never ships a specific provider SDK; you bring your own.

### Added — Runtime

- **`NpcForgeImprovClient`** — MonoBehaviour that loads a JSON
  context bundle produced by `npcforge export improv-context`,
  performs local IDF-weighted retrieval, and coordinates with a
  user-supplied `NpcForgeImprovLlmDelegate` to get the actual reply.
- **Built-in retrieval** — port of Python's `retrieve_lore_chunks`
  with the same stopword list, same IDF scoring, same fallback-
  to-first-K behaviour. Query-to-output produces the same top-K
  for the same input on both sides.
- **`ComposeSystemPrompt(query)`** — exposes the fully-composed
  prompt without issuing an LLM call. Useful for debugging,
  prompt-budget tuning, and testing.
- **Structured-reply parsing** — `NpcForgeImprovReply` (text,
  used_gate_id, declined_reason) with tolerance for fenced code
  blocks some models wrap JSON in.
- **`onReplyReceived` / `onError` UnityEvents** for wiring dialogue
  UI without polling.

### Verified

- 73 / 73 EditMode tests pass in Unity 6000.4.3f1 — 59 prior plus
  14 new covering retrieval port (split, tokens, IDF preference,
  novel-query fallback, stopword-only fallback), prompt
  composition, reply parsing (raw JSON, fenced, empty/invalid),
  and delegate-flow error paths.
- Python 248 tests pass; the retrieval algorithm is live-verified
  on both sides with the Rusted Lantern lore bundle.

### Upgrading from 1.3.0

Remove + re-add from the Package Manager git URL. To use improv:

1. Run `npcforge export improv-context --demo-dir <proj> --npc X`
   to write `<npc>_improv_context.json`.
2. Drop the JSON into `Assets/` as a TextAsset.
3. Add `NpcForgeImprovClient` to the NPC GameObject and assign the
   TextAsset.
4. In game code, call `SetLlmDelegate((systemPrompt, query, ct) =>
   yourLlmCall(...))` once at startup — delegate returns the raw
   JSON `ImprovReply`.
5. Call `RequestImprov("player question")` when an off-script
   question needs a reply; listen on `onReplyReceived`.

---

## [1.3.0] — 2026-04-19

Disposition-curated line banks in the runtime — ambient dialogue
without an LLM call in the hot path. Matches Python's v0.11.0
release.

### Added — Runtime

- **`NpcForgeLineBank`** — MonoBehaviour that loads a pre-generated
  bank JSON (Python's ``*.unity.json`` companion file) and picks
  context-matched variants per turn. Ranking mirrors Python's
  ``select_line`` exactly: more specific tag matches beat generic
  fallbacks, salience_boost breaks equal-specificity ties, an LRU
  cache (configurable ``lruSize``) avoids repeats.
- Context projection (``NpcForgeLineContext`` struct) — closed
  vocabulary ``{ disposition_tier, arc_stage, mood,
  recent_event_type, time_of_day, faction_present }`` mirroring
  Python's dimensions.
- ``ImportBankJson(string)`` accepts the Python side's
  ``LineBank.to_unity_json()`` output so one bank definition drives
  both runtimes without duplicated authoring.
- ``onLinePicked(slotId, text)`` UnityEvent for analytics / UI hooks.

### Verified

- 59 / 59 EditMode tests pass in Unity 6000.4.3f1 — 49 prior plus
  10 new covering JSON import, missing-slot fallback, generic-
  fallback matching, specificity ranking, salience tie-break, LRU
  avoidance, event firing, tag-match predicate edge cases.
- Python-side 229 tests pass; the JSON shape shared between engines
  is exercised by both suites.

### Upgrading from 1.2.0

Remove + re-add from the Package Manager git URL. Wiring for a new
NPC:

1. Generate a bank with ``npcforge gen lines --npc X --slot-id Y
   --axes disposition_tier=... time_of_day=...``. Python writes
   both the native and ``*.unity.json`` files.
2. Drop the ``*.unity.json`` file into ``Assets/`` (or anywhere
   under ``Application.persistentDataPath``).
3. Drop ``NpcForgeLineBank`` on the NPC GameObject and assign the
   TextAsset reference. Optionally assign ``NpcForgeMemoryStore`` /
   ``NpcForgeFactionStanding`` / ``NpcForgeArcTracker`` to source
   the context in gameplay code.

---

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
