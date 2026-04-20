# npcforge

**Agent-ready NPC dialogue and cast tooling** — lore-driven world profiles, additive generators, walk-up branches and bark libraries with **Yarn Spinner** export, plus memory, quests, arcs, ethics, improv, and engine sync for **Unity**, **Godot 4**, and **Unreal**.

Powered by [afterimage](https://github.com/altaidevorg/afterimage) (structured LLM calls, provider abstraction).

```
lore/*.md  ──►  WorldProfile (cached in .npcforge/world_profile.json)
                     │
                     ▼
   gen npcs / intents / barks / greetings / …  (YAML, additive)
                     │
                     ▼
   build  ──►  .yarn + lines.csv + manifest.json + lint.md
                     │
                     ├── play / game     (terminal, no LLM)
                     ├── eval            (curated quality suite)
                     └── engine-sync     (copy into your engine project)
```

## Why npcforge

Hosted NPC APIs bill per call and keep your canon off-disk. Hand-authoring a full cast, branching dialogue, and bark pools takes months. npcforge turns the workflow into **typed tools**: same contracts for **CLI**, **Python**, and **MCP** (Claude Desktop, Cursor, Cline). Run locally with your keys; script everything an agent can drive.

## Install

```bash
pip install -e .               # core CLI + library
pip install -e '.[mcp]'        # MCP server dependencies
```

- **Python** 3.10+ (see `pyproject.toml` for supported minors).
- **Optional:** [Yarn Spinner compiler](https://docs.yarnspinner.dev/getting-started/editing-with-visual-studio-code) (`ysc` on `PATH`) so `npcforge build` can run `ysc compile` after generation.

Set the API key for your provider (default provider is `gemini`):

| Provider   | Typical env var      |
|-----------|----------------------|
| gemini  | `GEMINI_API_KEY`     |
| openai  | `OPENAI_API_KEY`     |
| deepseek| `DEEPSEEK_API_KEY`   |
| openrouter | `OPENROUTER_API_KEY` |
| local   | `LOCAL_API_KEY`      |

Override with `--api-key-env` and `--provider` / `--model` on LLM subcommands.

## Quick start

```bash
export GEMINI_API_KEY=...

npcforge world infer --demo-dir examples/rusted_lantern
npcforge build --demo-dir examples/rusted_lantern --mode all
npcforge play --demo-dir examples/rusted_lantern --npc mira_vesser
npcforge game --demo-dir examples/rusted_lantern    # interactive tavern loop (needs walk-up .yarn in out/)
```

**Narrow rebuilds:** `npcforge build --demo-dir … --only-npcs id1,id2`  
**Voice lint + optional embedding score:** `--score-voice` on `build`  
**Skip Yarn compile:** `--no-validate` on `build`

### Migrating from v0.2.x

Use `npcforge build --demo-dir …` instead of the old top-level `npcforge --demo-dir …`.

## CLI overview

Subcommands are grouped by job. Only a subset is exposed as **MCP tools** (see below); the rest are **CLI / library** today.

| Area | Commands |
|------|----------|
| **Pipeline** | `build` — walk-up / barks / all; writes `out/`, manifest, lint |
| **World** | `world infer`, `world show` — profile from `lore/*.md` |
| **Cast & content** | `list-npcs`, `list-factions`, `resolve stubs` |
| **Generators (`gen`)** | `npcs`, `intents`, `barks`, `greetings`, `repeat-greeting`, `scene` (multi-NPC Yarn), `lines` (tagged line bank) |
| **Playback** | `play` — stream one branch / bark / greeting; `game` — stateful terminal loop from built walk-up Yarn |
| **Quality** | `eval` — curated case suite → `out/eval_report.md` + `.json`; exit `2` if any case fails (CI-friendly) |
| **Narrative state** | `memory show|record`, `quest list|show|set|advance`, `arc show|simulate` |
| **Character depth** | `voice show`, `player show|rebuild|update`, `trajectory show|simulate`, `ethics judge`, `emotion show` |
| **World secrets** | `unseen list|show|declare|record|materialize` — off-screen NPCs that accumulate canon until met |
| **Runtime bundles** | `export improv-context` — JSON for engine-side improv / RAG delegates |
| **Off-script** | `improv` — one-turn, lore-grounded reply (`--query …`) |
| **Engine** | `engine-sync` — copy `.yarn` + `lines.csv` (+ optional glue) into Unity / Godot / Unreal |
| **Agent transport** | `mcp` — stdio MCP server |

Run `npcforge <command> --help` for flags.

## Tools layer (Python + MCP)

Core workflows are **async functions** with **Pydantic** inputs/outputs in [`src/npcforge/tools.py`](src/npcforge/tools.py), registered in `TOOL_REGISTRY`. The CLI and **`npcforge mcp`** both call this registry.

**Registered tools (MCP + Python):** `infer_world_profile`, `show_world_profile`, `list_npcs`, `gen_npcs`, `gen_intents`, `gen_barks`, `resolve_stubs`, `gen_greetings`, `gen_repeat_greeting`, `engine_sync`, `build_pipeline`.

**CLI-only (today):** memory, quests, arcs, unseen, player profile, voice lenses, trajectory, ethics, emotion, eval, improv, export, `gen scene`, `gen lines`, `play`, `game`, etc.

```bash
pip install 'npcforge[mcp]'
npcforge-mcp    # or: npcforge mcp
```

Example MCP config:

```jsonc
{
  "mcpServers": {
    "npcforge": {
      "command": "npcforge-mcp",
      "env": { "GEMINI_API_KEY": "..." }
    }
  }
}
```

### From Python

```python
import asyncio
from pathlib import Path
from npcforge import BuildPipelineInput, GenNpcsInput, build_pipeline, gen_npcs

async def main():
    demo = Path("examples/rusted_lantern")
    key = "..."  # or os.environ["GEMINI_API_KEY"]

    await gen_npcs(GenNpcsInput(demo_dir=demo, roles=["traveling bard"], api_key=key))
    out = await build_pipeline(BuildPipelineInput(demo_dir=demo, mode="all", api_key=key))
    print(out.manifest.elapsed_seconds, "s")

asyncio.run(main())
```

## Dialogue outputs

### Walk-up

Player approaches an NPC; each branch matches a **player intent** from `player_intents.yaml`. NPCs whitelist intents via `allowed_intents` on their sheet in `characters.yaml`.

### Barks

Triggers in `barks.yaml` drive variant pools; the builder emits Yarn using `visited_count()`-style rotation plus JSON sidecars where configured.

### Richer sheets (v0.8+)

`NpcSheet` supports **relationships**, **gated knowledge**, and **state evolution** so respondents stay grounded in cast opinions and quest beats. See [`CHANGELOG.md`](CHANGELOG.md) and the Rusted Lantern `characters.yaml`.

### Voice ceiling

Per-NPC `vocabulary_ceiling`, `forbidden_words`, and `accent_markers` are enforced in prompts and **post-checked** into `lint.md`.

### Audio / loc

`lines.csv` exports stable **`line_id`**, speaker, emotion hints, and duration estimates for pipelines (see `npcforge.audio` and manifest `lines` metadata).

## Engine integration

```bash
npcforge engine-sync --engine unity  --demo-dir path/to/world --project-dir path/to/UnityProject  --install-scripts
npcforge engine-sync --engine godot  --demo-dir path/to/world --project-dir path/to/GodotProject --install-scripts
npcforge engine-sync --engine unreal --demo-dir path/to/world --project-dir path/to/UnrealProject
```

- **`--install-scripts` (Unity):** copies the C# runtime glue from this repo’s Unity integration paths.
- **`--install-scripts` (Godot):** copies the **`addons/npcforge`** plugin when the source tree is available (from a checkout, or pass `--scripts-source` to the `npcforge-godot` package root). See [`examples/godot_integration/npcforge-godot/README.md`](examples/godot_integration/npcforge-godot/README.md).

**Unity UPM:** add from git URL (path to the UPM package):

`https://github.com/efecnc/npcforge.git?path=examples/unity_integration/npcforge-unity`

A mirror folder layout also lives under [`examples/unity_integration/Assets/NpcForge/`](examples/unity_integration/Assets/NpcForge/) for non-UPM projects.

## Example worlds

| Directory | Setting |
|-----------|---------|
| [`examples/rusted_lantern/`](examples/rusted_lantern/) | Low-fantasy mining-town tavern |
| [`examples/night_city_2077/`](examples/night_city_2077/) | Cyberpunk noir, Watson |
| [`examples/saint_denis_1899/`](examples/saint_denis_1899/) | Frontier western |

Copy one as a template and replace `lore/`, YAML, and `quests.yaml` / `memory.json` as needed. Authoring notes: [`examples/AUTHORING.md`](examples/AUTHORING.md).

## Documentation

- **[`docs/TOOLS.md`](docs/TOOLS.md)** — tool input/output schemas, manifest shape  
- **[`docs/MCP.md`](docs/MCP.md)** — MCP client wiring  
- **[`CHANGELOG.md`](CHANGELOG.md)** — version history  

## Repository

- **Package metadata / PyPI-facing URLs:** [`pyproject.toml`](pyproject.toml)  
- **Upstream homepage** may differ from your fork remote; this checkout tracks **`https://github.com/efecnc/npcforge`**.

## License

Apache License 2.0 — see [`LICENSE`](LICENSE).
