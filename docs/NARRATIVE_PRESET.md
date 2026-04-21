# Narrative preset (`npcforge_project.yaml`)

Shippable games differ in how much **character sheet** and **walk-up dialogue**
complexity they need. npcforge uses a single project-level switch so teams
can align generators with their scope (solo indie vs. large RPG cast).

## Configuration

Create **`npcforge_project.yaml`** next to `characters.yaml`.

### Legacy single knob

```yaml
# indie_minimal | rpg_standard | cinematic_rpg
narrative_preset: indie_minimal
```

When only `narrative_preset` is set, npcforge **infers** a default
`topology` + `depth` (e.g. `indie_minimal` → `ambient_indie` + `lean`) so
newer generators stay consistent. You can still omit the file entirely:
defaults are **`quest_rpg`** + **`standard`**, which map to
**`rpg_standard`** for the three legacy prompt packs.

### Topology + depth (preferred for new projects)

```yaml
topology: quest_rpg        # see list in src/npcforge/project_config.py
depth: standard            # lean | standard | cinematic
experimental: []           # optional string list for future flags
review_workflow: false     # when true, optional NpcSheet.status is meaningful
```

**CLI overrides** for one run (`build`, `gen npcs`, `resolve stubs`):

```bash
npcforge build --demo-dir my_game --narrative-preset indie_minimal
npcforge build --demo-dir my_game --topology social_sim --depth cinematic
npcforge gen npcs --demo-dir my_game --narrative-preset cinematic_rpg
npcforge resolve stubs --demo-dir my_game --narrative-preset rpg_standard
```

Scaffold: `npcforge init --demo-dir my_game --topology quest_rpg --depth standard`.

The same fields exist on **MCP / Python** `GenNpcsInput`, `ResolveStubsInput`,
and `BuildPipelineInput` (`narrative_preset`, `topology`, `depth`).

## Presets

| Preset | Use when | NPC generation | Walk-up dialogue |
|--------|----------|----------------|------------------|
| **indie_minimal** | Small team, tight cast, fast iteration | Lean sheets, fewer intents, shorter voice blocks | Shorter assistant turns, less exposition |
| **rpg_standard** | Default CRPG / adventure scope | Balanced rules (4–8 intents, moderate detail) | Clear answers without dumps |
| **cinematic_rpg** | Cast-first, higher production value | Richer voice, more intents, more sample lines | Longer beats, more subtext |

Implementation: `src/npcforge/narrative_preset.py` holds the three legacy
preset paragraphs; `src/npcforge/project_config.py` appends **topology** and
**depth** guidance on top of those blocks for NPC generation and the walk-up
`build` pipeline.

## Roadmap (not implemented here)

- Preset-aware **intent** and **bark** generators.
- **Quest-conditioned** branch stubs (designer-visible gates).
- **Localization** profile keyed off preset.
