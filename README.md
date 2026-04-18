# npcforge

**Agent-ready NPC content generator — casts, dialogue, and bark libraries — with Yarn Spinner export.**

Drop in a world bible. npcforge infers the setting, generates the cast, writes the dialogue, ships Yarn Spinner files. Every capability is a typed tool callable from the CLI, from an MCP-enabled agent (Claude Desktop, Cursor, Cline), or from Python. Powered by [afterimage](https://github.com/altaidevorg/afterimage).

```
lore/*.md  ──►  WorldProfile (auto-inferred, cached)
                     │
                     ▼
        gen_npcs → characters.yaml (additive)
        gen_intents / gen_barks (additive, coming)
                     │
                     ▼
        build_pipeline → Yarn .yarn (walk-up + barks)
                       + JSONL traces + manifest + lint report
```

## Why

Convai / Inworld are hosted and charge per call. Writing a full cast plus branching dialogue plus barks by hand takes months. npcforge turns the whole pipeline into typed tools: point it at your lore, get a cast, get dialogue, get barks — locally, offline-capable, and scriptable by any agent that speaks MCP.

## Install

```bash
pip install -e .               # core CLI
pip install -e '.[mcp]'        # also install the MCP server deps
```

Python 3.10+. afterimage, PyYAML, and pydantic are pulled in as dependencies. For post-run Yarn validation install the [Yarn Spinner compiler](https://docs.yarnspinner.dev/getting-started/editing-with-visual-studio-code) so `ysc` is on `PATH`.

## Quick start

```bash
export GEMINI_API_KEY=...

# 1. Infer the world from your lore (once per project)
npcforge world infer --demo-dir examples/rusted_lantern

# 2. Generate more NPCs on top of whatever is already there (additive)
npcforge gen npcs --demo-dir examples/rusted_lantern \
    --roles "traveling bard spooked by the humming, young barmaid who is Mira's niece"

# 2b. Or hand-author stubs and let npcforge fill them in
#     (drop {id: x, _generate: true, role_hint: "..."} into characters.yaml)
npcforge resolve stubs --demo-dir examples/rusted_lantern

# 2c. Generate more player intents and bark triggers (both additive)
npcforge gen intents --demo-dir examples/rusted_lantern --n 5 --brief "physical / social conflict"
npcforge gen barks   --demo-dir examples/rusted_lantern --for-npcs mira_vesser --n 2

# 3. Run the full dialogue + bark pipeline
npcforge build --demo-dir examples/rusted_lantern --mode all

# 3b. Opt-in voice-consistency scoring — per-branch embedding distance
#     from the NPC's sample_lines. Surfaced in manifest.json.
npcforge build --demo-dir examples/rusted_lantern --mode walk_up --score-voice

# 3c. State-aware greetings — one per declared enum value (e.g. time_of_day)
npcforge gen greetings --demo-dir examples/rusted_lantern --only-npcs mira_vesser
# → examples/rusted_lantern/out/mira_vesser_greet_time_of_day.yarn with
#   <<if $time_of_day == "morning">> ... <<elseif $time_of_day == "night">> ...

# 3d. Visit-count-gated greetings — stranger → recognised → regular
npcforge gen repeat-greeting --demo-dir examples/rusted_lantern --only-npcs mira_vesser --n 4
# → examples/rusted_lantern/out/mira_vesser_repeat_greet.yarn with
#   <<if visited_count("mira_vesser_RepeatGreet") == 0>> ... <<else>> ...

# 4. Read it like a writer — playback in the terminal at speaking pace.
npcforge play --demo-dir examples/rusted_lantern --npc mira_vesser
npcforge play --demo-dir examples/rusted_lantern --npc mira_vesser --intent "threaten for info"
npcforge play --demo-dir examples/rusted_lantern --npc mira_vesser --bark reacts_to_hum --tempo 1.0
npcforge play --demo-dir examples/rusted_lantern --npc mira_vesser --greet time_of_day
npcforge play --demo-dir examples/rusted_lantern --npc mira_vesser --repeat-greet

# 5. Push everything straight into your Unity / Godot / Unreal project.
#    No manual copy — files land in the layout each engine's importer expects.
npcforge engine-sync --engine unity  --demo-dir examples/rusted_lantern --project-dir ~/MyGame --install-scripts
npcforge engine-sync --engine godot  --demo-dir examples/rusted_lantern --project-dir ~/MyGodotGame
npcforge engine-sync --engine unreal --demo-dir examples/rusted_lantern --project-dir ~/MyUnrealGame

# Start the MCP server so an agent can drive everything:
npcforge mcp            # stdio transport, used by Claude Desktop / Cursor / Cline
```

**More `build` options:**

```bash
# walk-up dialogue only
npcforge build --demo-dir examples/rusted_lantern --mode walk_up

# bark libraries only
npcforge build --demo-dir examples/rusted_lantern --mode barks

# iterate on a subset — regen Mira and Kess only
npcforge build --demo-dir examples/rusted_lantern --mode all \
    --only-npcs mira_vesser,kess_the_knife
```

**Migrating from v0.2.x:** the top-level `npcforge --demo-dir X --mode Y` form is gone. Prefix every invocation with `build`: `npcforge build --demo-dir X --mode Y`.

Outputs land in `examples/rusted_lantern/out/`:

```
<npc_id>.yarn                 walk-up node with one -> [intent] per allowed intent
<npc_id>.jsonl                raw afterimage conversation rows for that NPC
<npc_id>_bark_<trigger>.yarn  bark library node (visited-counter variant selector)
<npc_id>_bark_<trigger>.json  machine-readable barks (text + emotion + intensity)
world.yarn                    master Start node routing to each NPC
lint.md                       voice-ceiling violations, grouped by NPC
manifest.json                 content hashes, elapsed, lint totals, model used
```

Swap providers with `--provider openai|openrouter|deepseek|local` and `--model <name>`. Pass `--api-key-env MY_KEY_VAR` to override the default env var. `--no-validate` skips the `ysc compile` check.

## Tools layer (what the CLI, MCP server, and your agent all call)

Every capability is a single async function with Pydantic input/output. Defined once in [`npcforge.tools`](src/npcforge/tools.py), registered once in `TOOL_REGISTRY`. The CLI, the MCP server, and anything importing `npcforge` all call the same five functions.

| Tool | Purpose | LLM? |
|---|---|---|
| `infer_world_profile` | Read `lore/*.md`, produce a structured `WorldProfile`, cache to `.npcforge/world_profile.json` | one call |
| `show_world_profile` | Return the cached profile so the writer (or agent) can inspect / correct it | no |
| `list_npcs` | Read-only list of NPCs currently in `characters.yaml` | no |
| `gen_npcs` | Generate new NPCs from lore + brief / roles, **append** to `characters.yaml` (never overwrite) | one per NPC |
| `gen_intents` | Generate new `PlayerIntent` entries consistent with the world, **append** to `player_intents.yaml` | one per intent |
| `gen_barks` | Propose new bark *triggers* for one or more NPCs, **append** to `barks.yaml` (trigger contexts that feed the build pipeline) | one per trigger |
| `resolve_stubs` | Expand `_generate: true` placeholder entries in `characters.yaml` into full `NpcSheet`s, honouring `role_hint` / `voice_hint` | one per stub |
| `gen_greetings` | Generate one time-of-day greeting per enum-value, per NPC. Emits state-aware Yarn with `<<if $var == "value">>` chains | one per (NPC, value) |
| `gen_repeat_greeting` | Generate visit-count-gated greetings per NPC; emits Yarn keyed on `visited_count()` | one per (NPC, visit) |
| `engine_sync` | Copy generated `.yarn` + `lines.csv` into Unity / Godot / Unreal's expected project tree. Marker-tracked and idempotent | no |
| `build_pipeline` | Run the walk-up + bark pipeline; writes Yarn, `lines.csv` (v0.7+), manifest, lint report | many |

### MCP server

```bash
pip install 'npcforge[mcp]'
npcforge-mcp      # or: npcforge mcp
```

Register with any MCP-capable agent:

```jsonc
// Claude Desktop / Cursor / Cline
{
  "mcpServers": {
    "npcforge": {
      "command": "npcforge-mcp",
      "env": { "GEMINI_API_KEY": "..." }
    }
  }
}
```

Your agent now has tools like `infer_world_profile`, `gen_npcs`, `build_pipeline` — it can read your lore, propose a cast, ask you to review, tweak the profile, and produce Yarn files without ever leaving the chat.

### From Python

```python
import asyncio
from pathlib import Path
from npcforge import GenNpcsInput, gen_npcs

async def main():
    result = await gen_npcs(GenNpcsInput(
        demo_dir=Path("examples/rusted_lantern"),
        roles=["traveling bard spooked by the humming", "young barmaid who is Mira's niece"],
        api_key="...",
    ))
    for npc in result.added:
        print(npc.id, npc.name, npc.role)

asyncio.run(main())
```

## Two dialogue modes, one tool

### Walk-up dialogue

A player approaches an NPC. Player chooses an intent (ask, barter, threaten, flirt, ...). NPC responds in voice, in world, in context. Each NPC declares which intents they accept via `allowed_intents`.

```yaml
# characters.yaml (excerpt)
- id: mira_vesser
  name: "Mira Vesser"
  role: "Tavernkeeper of the Rusted Lantern"
  voice: "Gruff, dry, pragmatic. Short sentences."
  vocabulary_ceiling: grade_8
  forbidden_words: [intriguing, peculiar, quintessential, solemnity]
  accent_markers:
    - "Never says 'mine'; always 'the deep'."
  allowed_intents:
    - ask_about_local_events
    - ask_about_locket
    - threaten_for_info
    - bribe_for_info
    - barter_wares
    - accept_refuge
    - farewell
```

```yarn
title: mira_vesser
tags: walk_up
---
Mira Vesser waits. How do you approach them?
-> [Threaten for Info]
    Player: Where is the locket.
    Mira Vesser: Door's behind you, friend. Use it.
    <<jump mira_vesser_End>>
-> [Bribe for Info]
    Player: Three coppers for a name.
    Mira Vesser: Four. — and I won't ask twice.
    <<jump mira_vesser_End>>
-> [Barter Wares]
    ...
===
```

### Bark libraries

Reactive 1-liners for combat, ambient, witness, greeting, refusal — the 80% of NPC speech players actually hear in open-world games.

```yaml
# barks.yaml
barks:
  - npc: mira_vesser
    triggers:
      - id: greet_patron
        description: "A new traveler crosses the threshold at dusk."
        n: 10
      - id: reacts_to_hum
        description: "The four-note hum rises loud enough to shift cups on the bar."
        n: 6
```

Emits a Yarn node that cycles through variants via the `visited_count()` counter, plus a JSON file for game-runtime consumers:

```yarn
title: mira_vesser_Bark_greet_patron
tags: bark,trigger:greet_patron,npc:mira_vesser
---
<<if visited_count("mira_vesser_Bark_greet_patron") % 10 == 0>>
    Mira Vesser: Drink's two coppers. Kitchen closes at dark.
<<elseif visited_count("mira_vesser_Bark_greet_patron") % 10 == 1>>
    Mira Vesser: Sit where you like. Don't bleed on the floor.
...
<<endif>>
===
```

## Voice ceiling — no more "solemnity" in a miner's mouth

Per-NPC constraints injected into every prompt **and** lint-checked after generation:

- **`vocabulary_ceiling`** — `grade_3` / `grade_5` / `grade_8` / `high_school` / `college` / `academic`. Keeps a traumatized dwarven miner away from "intriguing."
- **`forbidden_words`** — hard no-gos. Lint catches inflections (`fascinate` also flags `fascinated`, `fascinating`, `fascinates`).
- **`accent_markers`** — positive instructions ("never says 'mine'; always 'the deep'").

After every run, `lint.md` lists every violation with snippet + location:

```markdown
## Voice-Ceiling Lint

**Total hits:** 2

### gereth_blackstone  (2 hits)

- `intriguing` in **walk_up:ask_about_locket:turn_3** — `...that is an intriguing idea, but...`
- `solemnity` in **bark:sees_new_face:4** — `...with such solemnity...`
```

## Player intents — finer-grained than archetypes

v0.2.0 replaces `player_archetypes.yaml` with `player_intents.yaml`. Intents describe **what the player is trying to do this turn**, not who the player is. A shipped project typically defines 15–30 intents; each NPC whitelists a subset. This is how dialogue trees actually key in the major RPGs.

```yaml
# player_intents.yaml (excerpt)
intents:
  - id: threaten_for_info
    name: "Threaten for Information"
    description: >
      Use implied violence, leverage, or menace to extract information. No
      actual violence.
    opening_intent: >
      Cut to the point and make clear the conversation will go badly.
```

## Ready-to-run starter worlds

Plus a **[Unity 2022 integration](examples/unity_integration/)** — drop the `Assets/NpcForge/` folder into any Unity project, follow the [5-minute setup](examples/unity_integration/SETUP.md), and press Play to see Mira greet you differently at dawn vs. night and remember you across visits. Ships four real `.yarn` files (walk-up + time-of-day greetings + repeat-greet + world.yarn with `<<declare>>`) plus four C# scripts that wire the Yarn Spinner runtime to npcforge's naming conventions.

Three settings ship in the repo — each a full walk-up + barks pipeline:

- **[`examples/rusted_lantern/`](examples/rusted_lantern/)** — low fantasy, 5 NPCs in a mining-town tavern
- **[`examples/night_city_2077/`](examples/night_city_2077/)** — cyberpunk noir in Watson: ripperdoc, Mox bartender, Aldecaldos fixer, Maelstrom initiate, Netwatch agent
- **[`examples/saint_denis_1899/`](examples/saint_denis_1899/)** — frontier western: Creole boarding-house keeper, Cajun swamp guide, clergyman, Lemoyne Raider, Pinkerton agent

```bash
npcforge world infer --demo-dir examples/night_city_2077
npcforge build       --demo-dir examples/night_city_2077 --mode all

npcforge world infer --demo-dir examples/saint_denis_1899
npcforge build       --demo-dir examples/saint_denis_1899 --mode all
```

Each covers 12 intents × 28–32 walk-up branches + 52–70 barks on a full run. Copy any of them and edit in place to bootstrap a new setting. Full authoring walkthrough in [`examples/AUTHORING.md`](examples/AUTHORING.md).

## Iteration speed

- `--only-npcs id1,id2` — rebuild just those NPCs.
- `npcforge gen npcs --dry-run` — preview generated NPCs without writing.
- `.npcforge/world_profile.json` — cached inference; edit the JSON directly to correct any misread.
- `manifest.json` — content hashes for every file so you can diff runs.
- `lint.md` — voice-ceiling violations grouped by NPC.
- `ysc compile` — automatic post-run syntactic validation when the Yarn Spinner compiler is on `PATH`.

## Using it as a library

Prefer the tools layer — one contract for every call:

```python
import asyncio
from pathlib import Path
from npcforge import (
    BuildPipelineInput,
    GenNpcsInput,
    InferWorldProfileInput,
    build_pipeline,
    gen_npcs,
    infer_world_profile,
)

async def main():
    demo = Path("examples/rusted_lantern")
    key = "..."

    # 1. Infer the world (cached on disk after the first call)
    await infer_world_profile(InferWorldProfileInput(demo_dir=demo, api_key=key))

    # 2. Generate new NPCs additively
    gen = await gen_npcs(GenNpcsInput(
        demo_dir=demo,
        roles=["traveling bard", "young barmaid"],
        api_key=key,
    ))
    for npc in gen.added:
        print(npc.id, npc.name)

    # 3. Run the dialogue + bark pipeline
    build = await build_pipeline(BuildPipelineInput(
        demo_dir=demo, mode="all", api_key=key,
    ))
    print("elapsed:", build.manifest["elapsed_seconds"], "seconds")

asyncio.run(main())
```

See [`docs/TOOLS.md`](docs/TOOLS.md) for every input / output schema and [`docs/MCP.md`](docs/MCP.md) for MCP client setup.

## Roadmap

### Shipped in v0.7.1

- **`npcforge engine-sync`** — copy generated `.yarn` + `lines.csv` into Unity, Godot, or Unreal's expected project tree with a single command. Marker-tracked (`.npcforge-sync.json`) so subsequent runs only copy what changed. Unity sync optionally installs the C# runtime-glue scripts too.
- **Engine adapter layer** (`npcforge.engines`) — per-engine path resolution + script installation, usable from Python directly when building your own build pipeline.

### Shipped in v0.7.0

- **`lines.csv` audio-pipeline export** — every walk-up turn and every bark variant lands with a deterministic `line_id`, speaker, context, emotion + intensity, syllable-based duration estimate, and source file. Wwise / FMOD / Unity Audio / loc teams read this column-stable CSV directly.
- **New `npcforge.audio` module** — pure helpers: `line_id`, `count_syllables`, `estimate_duration_seconds`, `infer_emotion`, `write_lines_csv`, `read_lines_csv`.
- **Typed `Manifest.lines`** — `LinesExport {csv, total}` surfaced in `manifest.json`.

### Shipped in v0.6.1

- **`gen repeat-greeting`** — visit-count-gated greetings (stranger → recognised → regular → else-fallback) via Yarn's `visited_count()` builtin; no project variable needed.
- **`play --greet <variable>` and `play --repeat-greet`** — terminal playback for both state-aware greeting node types, with labelled variants (`[time_of_day=morning]`, `[visit #0]`, `[visit else]`).

### Shipped in v0.6.0

- **State layer** — `variables.yaml` declares `time_of_day`, `disposition_*`, `quest_*_stage`, any enum / int / bool / string. Values feed every downstream generator's prompt; `build` emits `<<declare>>` lines at the top of `world.yarn` so the output compiles standalone.
- **`gen greetings`** — first state-aware output. One in-character greeting per enum value (e.g. dawn / morning / afternoon / dusk / night) per NPC, wrapped in a Yarn `<<if $var == "value">>` chain that any Yarn Spinner 2 runtime plays directly.
- **`NpcSheet.reacts_to`** — opt-in list of variable ids an NPC cares about; foundation for future reactive dialogue.

### Shipped in v0.5.0

- **`npcforge play`** — terminal playback for walk-up branches and bark libraries; colourised per speaker, optional `--tempo` pacing and `--wait` between lines.
- **Voice-consistency scoring** (`build --score-voice`) — per-branch embedding similarity to each NPC's `sample_lines`; scores land in `manifest.json -> npcs.<id>.walk_up.voice_scores`.
- **Typed `Manifest` Pydantic model** replaces the v0.4.x dict; schema in [`docs/TOOLS.md`](docs/TOOLS.md#manifest-schema-v050).
- `gen barks` flag rename `--for-npcs` → `--only-npcs` for consistency with `build`.

### Shipped in v0.4.0

- **`gen intents` + `gen barks` + `resolve stubs`** — the generator trio, all additive. [`docs/TOOLS.md`](docs/TOOLS.md) has details.

### Next up

- **Recipe files** (`requests/*.yaml`) — reusable cast recipes for diff-friendly version control.
- **Mid-dialog branching** — resample high-valence NPC turns at T=0.9, emit nested `->` options when continuations diverge.
- **Judge-enabled mode** — generate N candidates per branch, keep highest-scored, surface scores in manifest metadata.

### Further out

- **Ink and Ren'Py exporters** — same `Branch` data shape, additional writers.
- **World-state variables** — `<<set $quest_stage = 3>>` threaded through prompts and emitted into Yarn conditionals.
- **Knowledge gates** — structured `{fact, gate, reveal_lines, deflect_lines}` per NPC so reveals respect quest state.
- **Relationship graph** — NPC opinions of each other, injected into prompts.
- **Localization scaffold** — deterministic `line_id`, `lines_<locale>.csv` stubs, length-budget hints for lip sync.
- **More modes** — `shop`, `quest_success`, `quest_fail`, `repeat_greeting`, `group_chatter_pair`.
- **NPC-level concurrency** for 1000-NPC scale.
- **Judge-enabled mode** — generate N candidates per branch, keep highest-scored.
- **Local-model recipes** — validated Ollama + vLLM offline pipelines.

### Version history

See [`CHANGELOG.md`](CHANGELOG.md).

## Acknowledgements

Built on [afterimage](https://github.com/altaidevorg/afterimage) — two-agent loop, persona infrastructure, provider abstraction, structured output.

## License

Apache License 2.0. See [LICENSE](LICENSE).
