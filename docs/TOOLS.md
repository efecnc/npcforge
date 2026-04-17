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
| `out_dir` | `Path \| None` | `None` | Output directory (defaults to `<demo_dir>/out`). |
| `api_key` / `provider` / `model` | — | — | See `_LLMOptions`. |

**Output — `BuildPipelineOutput`:**

| Field | Type | Purpose |
|---|---|---|
| `manifest` | `dict` | The manifest dict (also written to `out_dir/manifest.json`). |
| `out_dir` | `Path` | Where artefacts were written. |

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
