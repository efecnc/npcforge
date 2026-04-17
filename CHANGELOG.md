# Changelog

All notable changes to npcforge land here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[SemVer](https://semver.org/).

## [0.3.0] — 2026-04-17

Agent-ready architecture. The big shape change.

### Added

- **Tools layer** (`npcforge.tools`) — every capability is now a typed async
  function with Pydantic input/output models. CLI and MCP server both
  dispatch into one registry.
- **`WorldProfile`** auto-inferred from `lore/*.md` via one structured LLM
  call, cached to `<demo_dir>/.npcforge/world_profile.json`. Every
  downstream generator consumes it.
- **`gen_npcs`** tool — generate NPC sheets from lore + brief / roles,
  **additive** (never overwrites existing entries in `characters.yaml`).
  One LLM call per NPC; ids deduplicated automatically.
- **MCP server** (`npcforge-mcp` / `npcforge mcp`) — stdio transport,
  registers every tool. Auto-injects provider API keys from the
  environment so agents can invoke tools without shipping secrets
  through prompts. Requires `pip install 'npcforge[mcp]'`.
- **Five starter tools** in the registry: `infer_world_profile`,
  `show_world_profile`, `list_npcs`, `gen_npcs`, `build_pipeline`.
- New CLI subcommands: `world infer`, `world show`, `list-npcs`,
  `gen npcs`, `mcp`.
- New docs: [`docs/TOOLS.md`](docs/TOOLS.md),
  [`docs/MCP.md`](docs/MCP.md), and this file.

### Changed

- **CLI is subcommand-based.** `npcforge --demo-dir X --mode Y` is gone.
  Use `npcforge build --demo-dir X --mode Y` instead.
- `WorldProfile.canonical_terms` is a `list[CanonicalTerm]`, not
  `dict[str, str]` — Gemini's structured-output API rejects
  `additionalProperties` which the dict form requires.
- README, authoring guide, and starter instructions rewritten for the
  generators-first workflow.

### Tests

- 37 passing (up from 25). New coverage for the tools registry, JSON
  Schema shapes, `list_npcs`, `show_world_profile` round-trip,
  `gen_npcs` IO (id uniqueness, additive append, top-level-key
  preservation).

---

## [0.2.0] — 2026-04-17

The production-readiness pass guided by the veteran-designer review.

### Added

- **Bark generation** (`--mode barks`) — reactive 1-line NPC utterances
  for triggers (`combat_start`, `greet_patron`, `reacts_to_hum`, ...).
  One LLM structured call per variant, deduplicated on exact text.
  Emits `.yarn` with a `visited_count()` variant selector plus a
  machine-readable `.json`.
- **Voice ceiling** on `NpcSheet`: `vocabulary_ceiling`,
  `forbidden_words`, `accent_markers`. Injected into prompts and
  lint-checked after generation (inflections included — `fascinate`
  also flags `fascinated`, `fascinating`, `fascinates`).
- **`LintReport`** + `lint.md` — writer-facing summary of every
  forbidden-word hit, grouped by NPC.
- `--only-npcs` for iteration speed.
- `manifest.json` with content hashes, elapsed time, lint totals.
- Optional `ysc compile` validation when Yarn Spinner tooling is on
  `PATH`.

### Changed

- **Breaking:** `player_archetypes.yaml` renamed to
  `player_intents.yaml`. Intents are finer-grained than archetypes —
  12 in the demo. Each NPC whitelists valid intents via
  `allowed_intents`.
- `NpcSheet` carries `allowed_intents`, `vocabulary_ceiling`,
  `forbidden_words`, `accent_markers`.

### Infra

- New modules: `lint.py`, `validate.py`. Schemas cover `BarkLine`,
  `BarkTrigger`, `BarksConfig`, `VocabularyCeiling`.
- Pipeline iterates intents per NPC via `resolve_intents_for_npc`.
- `run_all` accepts `mode = walk_up | barks | all`.
- Bark model fallback to `afterimage.common.default_model_name`
  because `GeminiProvider` still ships with the deprecated
  `gemini-2.0-flash`.

### Examples

- **Night City 2077** — cyberpunk noir, 5 NPCs (Viktor Vector, Rue,
  Santiago Reyes, Splice, Rebecca Vale), 12 intents, 64 bark targets.
- **Saint Denis 1899** — frontier western, 5 NPCs (Mrs. Castille,
  Old Henri, Reverend Ames, Red Rufus Doyle, Agent Whiting), 12
  intents, 70 bark targets.
- `examples/AUTHORING.md` — step-by-step guide for any new world.

---

## [0.1.0] — 2026-04-17

Initial release.

### Added

- `ConversationGenerator`-backed walk-up dialogue with deterministic
  per-archetype branch coverage (one afterimage run per
  `(NPC, archetype)` pair with a single-persona pool).
- Yarn Spinner 2.0 exporter — one node per NPC with
  `-> [archetype]` options + a shared end node + a `world.yarn`
  master `Start` node.
- Rusted Lantern demo — 5 NPCs, 3 player archetypes.
- 10 smoke tests covering the exporter and YAML loaders.
