# Tools Reference

Every capability npcforge ships is exposed through the tools layer
(`npcforge.tools`). This is the single contract the CLI, MCP server,
and Python library all call.

Pattern:

```python
from npcforge import <ToolName>Input, <tool_name>

output = await <tool_name>(<ToolName>Input(...))
```

Each input and output is a `pydantic.BaseModel`. Full JSON Schemas are
available via `input_model.model_json_schema()` / `list_tool_specs()`.

---

## `infer_world_profile`

Runs one LLM structured call against `lore/*.md` and produces a
`WorldProfile`. Cached to `<demo_dir>/.npcforge/world_profile.json`.

**Input — `InferWorldProfileInput`:**

| Field | Type | Default | Purpose |
|---|---|---|---|
| `demo_dir` | `Path` | required | Project directory containing `lore/`. |
| `overwrite_cache` | `bool` | `False` | Ignore the cached profile and re-infer. |
| `api_key` | `str` | required | LLM provider API key. |
| `provider` | `"gemini" \| "openai" \| "deepseek" \| "openrouter" \| "local"` | `"gemini"` | LLM vendor. |
| `model` | `str \| None` | `None` | Override the provider default. |

**Output — `InferWorldProfileOutput`:**

| Field | Type | Purpose |
|---|---|---|
| `profile` | `WorldProfile` | The inferred (or cached) profile. |
| `cache_path` | `Path` | Where the profile was persisted. |
| `cache_hit` | `bool` | True when a cached profile was returned without an LLM call. |

`WorldProfile` fields: `genre`, `era`, `tone`, `likely_rating`
(`E / E10+ / T / M / AO`), `register_default` (vocabulary ceiling
enum), `canonical_terms` (list of `{category, term}`),
`anachronism_blocklist`, `notes`, `inferred_from`.

```python
from pathlib import Path
from npcforge import InferWorldProfileInput, infer_world_profile

out = await infer_world_profile(InferWorldProfileInput(
    demo_dir=Path("my_game"),
    api_key="...",
))
print(out.profile.genre, out.profile.era)
```

---

## `show_world_profile`

Read-only. Returns the cached profile without calling the LLM.

**Input — `ShowWorldProfileInput`:** `demo_dir: Path`.

**Output — `ShowWorldProfileOutput`:** `profile: WorldProfile | None`,
`cache_path: Path`, `exists: bool`.

```python
out = await show_world_profile(ShowWorldProfileInput(demo_dir=Path("my_game")))
if not out.exists:
    print("Run infer_world_profile first.")
```

---

## `list_npcs`

Read-only. Returns the NPCs currently declared in
`<demo_dir>/characters.yaml`.

**Input — `ListNpcsInput`:** `demo_dir: Path`.

**Output — `ListNpcsOutput`:** `npcs: list[NpcSheet]`, `count: int`.

```python
out = await list_npcs(ListNpcsInput(demo_dir=Path("my_game")))
for npc in out.npcs:
    print(npc.id, npc.role)
```

---

## `gen_npcs`

Generates new NPCs and (by default) **appends** them to
`characters.yaml`. Existing entries are never modified. Uses the
cached world profile when present and auto-infers it otherwise.

**Input — `GenNpcsInput`:**

| Field | Type | Default | Purpose |
|---|---|---|---|
| `demo_dir` | `Path` | required | Project directory. |
| `n` | `int` | `5` | NPCs to generate when `roles` is empty. |
| `brief` | `str \| None` | `None` | Free-text description applied to every call. |
| `roles` | `list[str]` | `[]` | One NPC per role. Overrides `n` when given. |
| `append` | `bool` | `True` | When false, return without writing. |
| `concurrency` | `int` | `3` | Max parallel LLM calls. |
| `api_key` / `provider` / `model` | — | — | See `_LLMOptions`. |

**Output — `GenNpcsOutput`:**

| Field | Type | Purpose |
|---|---|---|
| `added` | `list[NpcSheet]` | Newly generated NPCs. |
| `existing_count` | `int` | How many NPCs were in `characters.yaml` at call time. |
| `characters_yaml` | `Path` | Target file. |
| `wrote` | `bool` | True when the file was modified. |

Behavior:

- Per-NPC structured LLM call with the world profile, lore, existing
  cast, and project-wide intent list injected.
- Id collisions with existing NPCs receive a numeric suffix
  (`lyra_vesser`, `lyra_vesser_2`, ...).
- `append=False` returns the generated sheets without writing — useful
  for agent review-then-commit flows.

```python
out = await gen_npcs(GenNpcsInput(
    demo_dir=Path("my_game"),
    roles=["traveling bard", "young barmaid who is Mira's niece"],
    api_key="...",
))
```

---

## `gen_intents`

Generates new `PlayerIntent` entries consistent with the world and the
existing intent catalogue. Appended to `player_intents.yaml`; existing
entries are never modified. One LLM call per intent; duplicate ids are
dropped.

**Input — `GenIntentsInput`:**

| Field | Type | Default | Purpose |
|---|---|---|---|
| `demo_dir` | `Path` | required | Project directory. |
| `n` | `int` | `8` | How many intents to propose (1–30). |
| `brief` | `str \| None` | `None` | Free-text hint about which intents to focus on. |
| `append` | `bool` | `True` | When false, return without writing. |
| `concurrency` | `int` | `3` | Max parallel LLM calls. |
| `api_key` / `provider` / `model` | — | — | See `_LLMOptions`. |

**Output — `GenIntentsOutput`:**

| Field | Type | Purpose |
|---|---|---|
| `added` | `list[PlayerIntent]` | Newly generated intents. |
| `existing_count` | `int` | Intents already in the file at call time. |
| `intents_yaml` | `Path` | Target file. |
| `wrote` | `bool` | True when the file was modified. |

```python
out = await gen_intents(GenIntentsInput(
    demo_dir=Path("my_game"),
    n=5,
    brief="more physically-grounded intents: challenge, comfort, defend",
    api_key="...",
))
```

---

## `gen_barks`

Generates new bark *triggers* for one or more NPCs — `(id, description, n)`
triples that feed `build_pipeline --mode barks`. Actual bark utterances are
still produced during the build. Appended to `barks.yaml` (additive, nested
by NPC).

**Input — `GenBarksInput`:**

| Field | Type | Default | Purpose |
|---|---|---|---|
| `demo_dir` | `Path` | required | Project directory. |
| `for_npcs` | `list[str]` | `[]` | NPC ids to cover. Empty = every NPC in `characters.yaml`. |
| `n_per_npc` | `int` | `3` | Triggers to propose per NPC (1–15). |
| `brief` | `str \| None` | `None` | Free-text hint about which triggers to focus on. |
| `append` | `bool` | `True` | When false, return without writing. |
| `concurrency` | `int` | `3` | Max parallel LLM calls. |
| `api_key` / `provider` / `model` | — | — | See `_LLMOptions`. |

**Output — `GenBarksOutput`:**

| Field | Type | Purpose |
|---|---|---|
| `added` | `list[{npc: str, triggers: list[BarkTrigger]}]` | New triggers grouped by NPC. |
| `barks_yaml` | `Path` | Target file. |
| `wrote` | `bool` | True when the file was modified. |

```python
out = await gen_barks(GenBarksInput(
    demo_dir=Path("my_game"),
    for_npcs=["mira_vesser"],
    n_per_npc=2,
    api_key="...",
))
```

---

## `resolve_stubs`

Expands every `_generate: true` placeholder entry in `characters.yaml`
into a full `NpcSheet`, honouring `role_hint`, `voice_hint`, and
optional `name` seeds. Rewrites the YAML in place preserving top-level
keys (`world`, `tone`, etc.) and the order of non-stub entries.

A stub entry looks like:

```yaml
npcs:
  - id: the_rival_tavernkeeper
    _generate: true
    role_hint: "a competing tavernkeeper who moved into Emberfall last spring"
    voice_hint: "slick, smiling, smooth-talking — Mira's exact opposite"
```

After `resolve_stubs` the entry is replaced with a fully-populated
sheet (name, role, voice, motivations, secret, speech_quirks,
forbidden_words, vocabulary_ceiling, allowed_intents, ...) whose `id`
matches the stub exactly.

**Input — `ResolveStubsInput`:**

| Field | Type | Default | Purpose |
|---|---|---|---|
| `demo_dir` | `Path` | required | Project directory. |
| `only_ids` | `list[str]` | `[]` | Restrict to a subset of stub ids. Empty = all stubs. |
| `write` | `bool` | `True` | When false, return resolved sheets without touching the file. |
| `concurrency` | `int` | `3` | Max parallel LLM calls. |
| `api_key` / `provider` / `model` | — | — | See `_LLMOptions`. |

**Output — `ResolveStubsOutput`:**

| Field | Type | Purpose |
|---|---|---|
| `resolved` | `list[NpcSheet]` | Successfully expanded sheets. |
| `unresolved_ids` | `list[str]` | Stubs the LLM failed to expand (retry candidates). |
| `characters_yaml` | `Path` | Target file. |
| `wrote` | `bool` | True when the file was modified. |

```python
out = await resolve_stubs(ResolveStubsInput(
    demo_dir=Path("my_game"),
    api_key="...",
))
print(f"resolved={len(out.resolved)} retry={out.unresolved_ids}")
```

---

## `gen_greetings`

Generates one in-character greeting per value of an enum project
variable (typically `time_of_day`), per NPC. Emits a per-NPC Yarn node
using `<<if $var == "value">>` / `<<elseif>>` / `<<else>>` / `<<endif>>`.
The first state-aware output npcforge produces. Requires a
`variables.yaml` in the project directory declaring the chosen variable
as `type: enum`.

**Input — `GenGreetingsInput`:**

| Field | Type | Default | Purpose |
|---|---|---|---|
| `demo_dir` | `Path` | required | Project directory. Must contain `variables.yaml` and `characters.yaml`. |
| `variable_id` | `str` | `"time_of_day"` | Project-variable id to key greetings on. Must be enum-typed. |
| `only_npcs` | `list[str]` | `[]` | Restrict to a subset of NPC ids. |
| `concurrency` | `int` | `4` | Max parallel LLM calls. |
| `write` | `bool` | `True` | Write `.yarn` nodes to `<demo_dir>/out/`. |
| `api_key` / `provider` / `model` | — | — | See `_LLMOptions`. |

**Output — `GenGreetingsOutput`:**

| Field | Type | Purpose |
|---|---|---|
| `added` | `list[{npc: str, variable_id: str, variants: list[(str, str)]}]` | Per-NPC variants as `(value, text)` pairs in declaration order. |
| `variable_id` | `str` | Echoes the variable the variants key on. |
| `out_dir` | `Path` | Where the greeting nodes were written. |
| `wrote` | `bool` | True when files were written. |

```python
out = await gen_greetings(GenGreetingsInput(
    demo_dir=Path("my_game"),
    variable_id="time_of_day",
    only_npcs=["mira_vesser"],
    api_key="...",
))
for entry in out.added:
    for value, text in entry.variants:
        print(f"{entry.npc} [{value}] {text}")
```

---

## `gen_repeat_greeting`

Generates visit-count-gated greeting variants per NPC. Emits a Yarn node
keyed on `visited_count("<node_title>")`: visits 0 .. n-2 play distinct
variants; the final variant is an `<<else>>` fallback played on every
subsequent visit. Unlike `gen_greetings`, this does NOT require a project
variable — Yarn's `visited_count()` builtin handles the state.

**Input — `GenRepeatGreetingInput`:**

| Field | Type | Default | Purpose |
|---|---|---|---|
| `demo_dir` | `Path` | required | Project directory. |
| `n` | `int` | `3` | Total variants per NPC (2–8). Last one is the else-fallback. |
| `only_npcs` | `list[str]` | `[]` | Restrict to a subset of NPC ids. |
| `concurrency` | `int` | `4` | Max parallel LLM calls. |
| `write` | `bool` | `True` | Write `.yarn` nodes to `<demo_dir>/out/`. |
| `api_key` / `provider` / `model` | — | — | See `_LLMOptions`. |

**Output — `GenRepeatGreetingOutput`:**

| Field | Type | Purpose |
|---|---|---|
| `added` | `list[{npc: str, variants: list[str]}]` | Per-NPC variants in visit order (final item is the else-fallback). |
| `out_dir` | `Path` | Where greeting nodes were written. |
| `wrote` | `bool` | True when files were written. |

```python
out = await gen_repeat_greeting(GenRepeatGreetingInput(
    demo_dir=Path("my_game"),
    n=4,
    only_npcs=["mira_vesser"],
    api_key="...",
))
for entry in out.added:
    for idx, text in enumerate(entry.variants):
        label = "else" if idx == len(entry.variants) - 1 else f"visit {idx}"
        print(f"{entry.npc} [{label}] {text}")
```

---

## `engine_sync`

Copies `<demo_dir>/out/` into a game engine's expected project layout
(Unity, Unreal). Skips files whose contents are unchanged; writes
a `.npcforge-sync.json` marker so subsequent runs are incremental.

**Input — `EngineSyncInput`:**

| Field | Type | Default | Purpose |
|---|---|---|---|
| `demo_dir` | `Path` | required | npcforge project directory (the one with `characters.yaml`). |
| `project_dir` | `Path` | required | Engine project root. Unity: folder with `Assets/`. Unreal: folder with `Content/`. |
| `engine` | `"unity"` / `"unreal"` | required | Target engine. |
| `source_dir` | `Path \| None` | `None` | Override the source. Defaults to `<demo_dir>/out`. Use to sync a frozen snapshot (e.g. `sample_output/`). |
| `install_scripts` | `bool` | `False` | Unity-only: also copy the 4 C# runtime-glue scripts from `examples/unity_integration/Assets/NpcForge/Scripts/`. |
| `scripts_source_dir` | `Path \| None` | `None` | Override source directory for glue scripts. Default is discovered from the repo checkout. |
| `dry_run` | `bool` | `False` | Plan the sync without writing anything. |

**Output — `EngineSyncOutput`:**

| Field | Type | Purpose |
|---|---|---|
| `engine` | `str` | Engine name (echoed). |
| `project_dir` | `Path` | Target root. |
| `source_dir` | `Path` | Resolved source directory. |
| `dry_run` | `bool` | True when the run was a dry-run. |
| `marker_path` | `Path \| None` | Where the sync marker was written (or would be). |
| `total_files` | `int` | Count of files actually copied (skips and marker writes excluded). |
| `actions` | `list[SyncAction]` | Per-file `{action, destination, source, reason}` log. |
| `errors` | `list[str]` | Empty on success. |

Each engine's destination layout:

| Engine | Dialogue (`.yarn` + `lines.csv`) | Scripts |
|---|---|---|
| Unity | `Assets/NpcForge/Dialogue/` | `Assets/NpcForge/Scripts/` (when `install_scripts=True`) |
| Unreal | `Content/NpcForge/Dialogue/` for `.yarn`, `Content/NpcForge/Data/` for `lines.csv` | — |

```python
out = await engine_sync(EngineSyncInput(
    demo_dir=Path("my_game"),
    project_dir=Path("~/MyGame").expanduser(),
    engine="unity",
    install_scripts=True,
))
print(f"copied {out.total_files} files; marker {out.marker_path}")
```

**Idempotency.** Every run hashes source files against the previous
marker. Unchanged files emit a `skip` action, not a rewrite. Only
changed files recopy, with reason `"content changed"`.

**Why no sidecars?** Unity's `.meta` and Unreal's
`.uasset` files are all generated by the engine's own importer on first
reimport. Writing them ourselves drifts with whichever Yarn Spinner
version the user has installed — letting each engine handle its own
sidecars is the robust path.

---

## `build_pipeline`

Runs the walk-up / bark / all pipeline, wrapping the existing
`run_all` implementation.

**Input — `BuildPipelineInput`:**

| Field | Type | Default | Purpose |
|---|---|---|---|
| `demo_dir` | `Path` | required | Project directory. |
| `mode` | `"walk_up" \| "barks" \| "all"` | `"walk_up"` | Which stage(s) to run. |
| `only_npcs` | `list[str]` | `[]` | Restrict to a subset of NPC ids. |
| `max_turns` | `int` | `3` | Turns per intent branch. |
| `intent_concurrency` | `int` | `3` | Parallel intent generations per NPC. |
| `bark_concurrency` | `int` | `4` | Parallel bark generations per (NPC, trigger). |
| `score_voice` | `bool` | `False` | Compute per-branch voice-consistency scores via embeddings. Adds one batched embedding call per NPC. |
| `out_dir` | `Path \| None` | `None` | Output directory (defaults to `<demo_dir>/out`). |
| `api_key` / `provider` / `model` | — | — | See `_LLMOptions`. |

**Output — `BuildPipelineOutput`:**

| Field | Type | Purpose |
|---|---|---|
| `manifest` | `Manifest` | Typed manifest (see below), also written to `out_dir/manifest.json`. |
| `out_dir` | `Path` | Where artefacts were written. |

### `Manifest` schema (v0.7.0)

```python
class Manifest(BaseModel):
    version: str                    # e.g. "0.7.0"
    generated_at: str               # ISO-8601 UTC
    provider: str                   # "gemini" | "openai" | ...
    model: str | None
    mode: str                       # "walk_up" | "barks" | "all"
    npcs: dict[str, NpcEntry]
    world: WorldEntry | None
    lint: LintSummary
    lines: LinesExport | None       # v0.7+: lines.csv summary, null when no dialogue
    elapsed_seconds: float
    voice_scoring_enabled: bool     # true when build was run with score_voice

class LinesExport(BaseModel):       # v0.7+
    csv: str                        # filename of lines.csv inside out/
    total: int                      # total LineRecord rows written

class NpcEntry(BaseModel):
    sheet_hash: str                 # 16-hex-char sha256 of the source sheet
    walk_up: NpcWalkUpEntry | None
    barks: list[BarkTriggerEntry]

class NpcWalkUpEntry(BaseModel):
    yarn: str                       # filename inside out/
    yarn_hash: str
    intents: list[str]              # ordered intent ids
    branch_count: int
    voice_scores: dict[str, float]  # intent_id -> [0, 1]; empty when disabled

class BarkTriggerEntry(BaseModel):
    trigger: str
    requested: int
    produced: int
    yarn: str
    yarn_hash: str
    json_path: str                  # serialised on wire as "json"

class WorldEntry(BaseModel):
    yarn: str
    yarn_hash: str

class LintSummary(BaseModel):
    markdown: str                   # filename of the lint report
    total_hits: int
```

**Voice scores** are means across assistant turns in a branch of the
best-match cosine similarity to any of the NPC's `sample_lines`. Values
cluster in `[0.5, 0.9]` in practice — `< 0.5` signals register drift,
`> 0.8` signals the branch is very close in voice to the reference
exemplars.

### `lines.csv` — the VO / localisation export (v0.7.0)

Every walk-up turn and every bark variant emitted by `build_pipeline`
also lands as one row in `out/lines.csv`. Column order is frozen so
downstream tooling can rely on it:

```
line_id, npc_id, speaker, context, source_file, emotion,
intensity, duration_sec, text
```

- **`line_id`** — `<npc_id>_<10-hex>` hash of the canonical English text
  + context. Stable under regeneration as long as the line text itself
  does not change.
- **`context`** — origin tag:
  - `walk_up:<intent_id>:turn_<n>`
  - `bark:<trigger_id>:<variant_index>`
- **`emotion`** / **`intensity`** — structured output from the bark
  generator, heuristic from `infer_emotion` on walk-up assistant turns.
  `infer_emotion` is pure and deterministic; extend or replace it for
  project-specific tagging.
- **`duration_sec`** — syllable-based estimate at ~4 syllables/sec,
  minimum 0.3 s. Use as a *budget*, not a measurement.
- **`text`** — the final dialogue line verbatim (CSV-escaped).

Wwise / FMOD / Unity Audio and loc tools consume this CSV directly. See
`LineRecord` in [`src/npcforge/audio.py`](../src/npcforge/audio.py) for
the Pydantic model and `write_lines_csv` / `read_lines_csv` helpers.

---

## Registering new tools

1. Define `<Name>Input` and `<Name>Output` Pydantic models in
   [`src/npcforge/tools.py`](../src/npcforge/tools.py).
2. Implement `async def <name>(input: <Name>Input) -> <Name>Output`;
   delegate to a feature module.
3. Add an entry to `TOOL_REGISTRY`. The MCP server automatically
   picks it up.
4. Add a CLI subcommand in
   [`src/npcforge/cli.py`](../src/npcforge/cli.py).
5. Export public names from
   [`src/npcforge/__init__.py`](../src/npcforge/__init__.py).

Tests should cover schema shape (presence of `api_key` on LLM tools,
JSON Schema validity) and any pure IO logic your tool touches.
