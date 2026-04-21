# npcforge

**Lore-grounded NPC cast and dialogue** for games: structured **synthetic text** (character sheets, branching walk-up lines, bark pools) with **Yarn Spinner** export, linting, and optional engine sync for **Unity** and **Unreal**.

Powered by [afterimage](https://github.com/altaidevorg/afterimage) (structured LLM calls and multi-provider support). The same workflows run from the **CLI**, **Python async tools**, or an **MCP** server so agents and CI can drive generation locally with your API keys.

---

## What you get

| Layer | Role |
|--------|------|
| **World** | `lore/*.md` → cached **world profile** (genre, tone, rating, taboo terms). |
| **Cast** | `characters.yaml` — full **NpcSheet** rows or `_generate` stubs; optional **tier** / **status** for production tracking. |
| **Player** | `player_intents.yaml` — what the player *does* per turn; NPCs may whitelist via `allowed_intents`. |
| **Pipeline** | `npcforge build` — one branch per **(NPC, intent)** walk-up dialogue, plus **barks** from `barks.yaml`. |
| **Artefacts** | `out/*.yarn`, `manifest.json`, `lines.csv`, `lint.md` — diffable, engine-ready **synthetic dialogue data**. |

---

## Repository layout

```
src/npcforge/          # installable package
├── cli.py             # Command-line entrypoint
├── tools.py           # Pydantic tool inputs/outputs + TOOL_REGISTRY
├── generation.py      # gen_npcs, gen_intents, gen_barks, resolve_stubs, greetings, …
├── pipeline.py        # walk-up + barks → Yarn (run_all)
├── schemas.py         # NpcSheet, intents, barks, factions, memory, …
├── prompts.py         # Respondent / generator prompt bodies
├── world_profile.py   # Infer + cache setting profile
├── project_config.py # npcforge_project.yaml: topology, depth, experimental, review_workflow
├── narrative_preset.py
├── narrative_scope.py # layers.yaml + scope_tags filtering
├── game.py            # Stateful terminal loop over built walk-up Yarn
├── tape_game.py       # Terminal “tape” demo (optional Pillow)
├── doctor.py          # npcforge doctor sanity checks
├── export_cast.py     # export cast → CSV
├── project_init.py    # npcforge init scaffold
├── engines/           # unity / unreal sync adapters
├── audio.py, lint.py, yarn.py, manifest.py, …
examples/              # demo worlds + Unity UPM sample under unity_integration/
docs/                  # TOOLS, MCP, NARRATIVE_PRESET, AFTERIMAGE, …
tests/                 # pytest suite
recording_sim/       # Static HTML playback demo (Fallen Oak Inn style)
```

---

## Install

```bash
pip install -e .                 # CLI + library
pip install -e '.[mcp]'          # MCP stdio server
pip install -e '.[tape]'         # npcforge tape (GIF / terminal capture helpers)
```

- **Python** 3.10+ (see `pyproject.toml`).
- **Optional:** [Yarn Spinner compiler](https://docs.yarnspinner.dev/) (`ysc` on `PATH`) so `npcforge build` can run `ysc compile`.

**API keys** (override with `--api-key-env` / `--provider` / `--model` on LLM commands):

| Provider | Typical env var |
|----------|-----------------|
| gemini (default) | `GEMINI_API_KEY` |
| openai | `OPENAI_API_KEY` |
| deepseek | `DEEPSEEK_API_KEY` |
| openrouter | `OPENROUTER_API_KEY` |
| local | `LOCAL_API_KEY` |

---

## Quick start

```bash
export GEMINI_API_KEY=...

# Optional: scaffold narrative defaults next to your YAML
npcforge init --demo-dir examples/rusted_lantern
npcforge doctor --demo-dir examples/rusted_lantern

npcforge world infer --demo-dir examples/rusted_lantern
npcforge build --demo-dir examples/rusted_lantern --mode all
npcforge play --demo-dir examples/rusted_lantern --npc mira_vesser
```

**Narrow rebuild:** `npcforge build --demo-dir … --only-npcs id1,id2`  
**Voice scoring (embeddings):** `--score-voice` on `build`  
**Skip Yarn compile:** `--no-validate` on `build`  
**Cast spreadsheet:** `npcforge export cast --demo-dir …` → `out/cast.csv`

---

## Project file: `npcforge_project.yaml`

Drop this beside `characters.yaml` (or run `npcforge init`). It steers **how much** character detail and **how tight** walk-up dialogue should feel.

- **`topology`** — one of six narrative shapes (e.g. `quest_rpg`, `social_sim`, `immersive_sim`).
- **`depth`** — `lean` | `standard` | `cinematic`.
- **`experimental`** — optional string list for future flags.
- **`review_workflow`** — when `true`, optional **`NpcSheet.status`** is meaningful for writer pipelines.
- **Legacy:** a single **`narrative_preset`** line (`indie_minimal` | `rpg_standard` | `cinematic_rpg`) still works; topology + depth are inferred if omitted.

CLI overrides for one run: `--topology`, `--depth`, `--narrative-preset` on **`build`**, **`gen npcs`**, **`resolve stubs`**.

Details: [`docs/NARRATIVE_PRESET.md`](docs/NARRATIVE_PRESET.md).

---

## Command overview

| Area | Commands |
|------|----------|
| **Project** | `init`, `doctor` |
| **Pipeline** | `build` — `walk_up` / `barks` / `all` → `out/`, manifest, lint |
| **World** | `world infer`, `world show` |
| **Cast** | `list-npcs`, `list-factions`, `resolve stubs`, `export cast` |
| **Generators (`gen`)** | `npcs`, `intents`, `barks`, `greetings`, `repeat-greeting`, `scene`, `lines` |
| **Playback** | `play` — one branch / bark / greeting; `game` — stateful loop from built `.yarn` |
| **Demos** | `tape` — terminal tape + optional GIF (`pip install -e '.[tape]'`) |
| **Narrative state** | `memory …`, `quest …`, `arc …` |
| **Depth systems** | `voice …`, `player …`, `trajectory …`, `ethics …`, `emotion …`, `unseen …` |
| **Quality** | `eval` — curated suite → `out/eval_report.*` (exit `2` on failure) |
| **Runtime bundles** | `export improv-context` — JSON for engine-side improv |
| **Off-script** | `improv` — single-turn lore-grounded reply |
| **Engine** | `engine-sync` — copy `.yarn` + `lines.csv` into Unity / Unreal |
| **Agents** | `mcp` — stdio MCP server |

Run `npcforge <command> --help` for flags. **MCP-registered** tools today: `infer_world_profile`, `show_world_profile`, `list_npcs`, `gen_npcs`, `gen_intents`, `gen_barks`, `resolve_stubs`, `gen_greetings`, `gen_repeat_greeting`, `engine_sync`, `build_pipeline` (see [`docs/MCP.md`](docs/MCP.md)).

---

## Python API

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

Schema reference: [`docs/TOOLS.md`](docs/TOOLS.md).

---

## Example worlds

| Path | Notes |
|------|--------|
| [`examples/rusted_lantern/`](examples/rusted_lantern/) | Low-fantasy tavern cast; relationships, knowledge, state evolution. |
| [`examples/night_city_2077/`](examples/night_city_2077/) | Cyberpunk noir reference demo. |
| [`examples/night_city_game/`](examples/night_city_game/) | Alternate / slimmer night-city sample. |
| [`examples/saint_denis_1899/`](examples/saint_denis_1899/) | Frontier western tone. |
| [`examples/tape_game/`](examples/tape_game/) | Minimal demo for `npcforge tape` + small lore footprint. |
| [`examples/fallen_oak_inn/`](examples/fallen_oak_inn/) | Sword Coast inn slice (lore + cast). |

Authoring checklist for **your** folder: [`examples/AUTHORING.md`](examples/AUTHORING.md).

---

## Engine integration

```bash
npcforge engine-sync --engine unity   --demo-dir path/to/world --project-dir path/to/UnityProject   --install-scripts
npcforge engine-sync --engine unreal  --demo-dir path/to/world --project-dir path/to/UnrealProject
```

**Unity UPM** package tree: [`examples/unity_integration/npcforge-unity/`](examples/unity_integration/npcforge-unity/) (see package `README` inside). A mirrored **Assets** layout also lives under [`examples/unity_integration/Assets/NpcForge/`](examples/unity_integration/Assets/NpcForge/) for non-UPM workflows.

---

## Static playback demo

[`recording_sim/index.html`](recording_sim/index.html) — self-contained HTML terminal-style playback (no Python server); open in a browser after pointing it at exported dialogue if you wire paths for your project.

---

## Documentation

| Doc | Purpose |
|-----|---------|
| [`docs/TOOLS.md`](docs/TOOLS.md) | Tool I/O models, manifest shape |
| [`docs/MCP.md`](docs/MCP.md) | MCP client configuration |
| [`docs/NARRATIVE_PRESET.md`](docs/NARRATIVE_PRESET.md) | `npcforge_project.yaml` narrative knobs |
| [`docs/AFTERIMAGE.md`](docs/AFTERIMAGE.md) | afterimage / walk-up pipeline notes |
| [`CHANGELOG.md`](CHANGELOG.md) | Version history |

---

## Tests

```bash
pip install -e '.[dev]'
pytest
```

---

## License

Apache License 2.0 — see [`LICENSE`](LICENSE).
