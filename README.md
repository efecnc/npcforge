# npcforge

**Branching NPC dialogue generator with Yarn Spinner export.**
Drop in a world bible and a set of character sheets, get game-engine-ready
dialogue where every player archetype produces a different branch inside
every NPC's node. Powered by [afterimage](https://github.com/altaidevorg/afterimage).

```
world bible + NPC sheets + player archetypes
           │
           ▼
   afterimage (two-agent loop + judge)
           │
           ▼
   Yarn Spinner .yarn files (+ JSONL traces)
```

## Why

Convai / Inworld are hosted and charge per call. Writing branching NPC
dialogue by hand takes months. npcforge trades both costs for one afterimage
run: **lore-grounded, persona-stable, offline-capable.** The same pipeline
can later feed fine-tuning data for a 3B local NPC model that ships inside
your game.

## Install

```bash
pip install -e .
```

Requires Python 3.10+. afterimage, PyYAML, and pydantic are pulled in as
dependencies.

## Quick start

```bash
export GEMINI_API_KEY=...
npcforge --demo-dir examples/rusted_lantern
```

Outputs land in `examples/rusted_lantern/out/`:

```
<npc_id>.yarn      Yarn Spinner node, one branch per player archetype
<npc_id>.jsonl     raw afterimage conversation rows (with scores when
                   the judge is enabled)
world.yarn         master Start node routing to each NPC
```

Swap providers with `--provider openai|openrouter|deepseek|local` and
`--model <name>`. Pass `--api-key-env MY_KEY_VAR` to override the default
environment variable.

## What the output looks like

```yarn
title: kess_the_knife
---
Kess (the Knife) waits. How do you approach them?
-> [Curious Scholar]
    Player: Greetings, good sir. My apologies for the intrusion...
    Kess (the Knife): Good sir? Oh, bless your heart, love, I haven't been
        a 'sir' in a good many years, if ever!
    Player: Faint scraping, mostly. And a low groan.
    Kess (the Knife): Mines always have their own creaks and groans.
    <<jump kess_the_knife_End>>
-> [Hostile Mercenary]
    Player: Kess. I'm not here for your wares. There's a tarnished iron
        locket in this town.
    Kess (the Knife): Oh, a locket, you say? You're a man who knows what
        he wants, I like that!
    <<jump kess_the_knife_End>>
-> [Deceptive Trader]
    ...
===
title: kess_the_knife_End
---
Kess (the Knife): (returns to their work)
===
```

## How it works

Afterimage runs a two-agent loop per `(NPC, archetype)` pair:

1. **Correspondent** plays the player, seeded with the archetype persona.
2. **Respondent** plays the NPC, grounded in the world bible + character sheet.
3. The hybrid judge (optional, opt-in) scores coherence, grounding, and
   voice-consistency; dialogs below threshold auto-retry.
4. npcforge groups the resulting conversations by archetype and emits one
   Yarn node per NPC.

**Determinism:** each branch is generated in its own afterimage run with a
single-archetype persona pool, so coverage is 100% by construction — no
reliance on persona cycling across concurrent calls.

## Authoring your own world

Drop three things into a demo directory:

```
my_game/
├── lore/
│   ├── world.md
│   └── region_north.md
├── characters.yaml
└── player_archetypes.yaml
```

### `characters.yaml`

```yaml
npcs:
  - id: elena_stonekeeper
    name: "Elena Stonekeeper"
    role: "Archivist of the Ninth Circle"
    voice: >
      Measured, precise, answers in the fewest words necessary.
    background: >
      Guarded the archives for forty-three winters.
    motivations:
      - "Never let the wrong hand touch the wrong book."
    secret: "She burned chapter seven herself, long ago."
    speech_quirks:
      - "Cites shelf codes the way most people cite names."
    sample_lines:
      - "You wanted G-44. G-44 does not answer."
```

### `player_archetypes.yaml`

```yaml
archetypes:
  - id: scholar
    name: "Earnest Scholar"
    description: >
      Polite, note-taking, asks for permission before asking for facts.
    opening_intent: "introduce themselves and ask for permission to research"
```

Each archetype becomes one `-> [archetype]` option on every NPC's node.

## Using it as a library

```python
import asyncio
from pathlib import Path
from npcforge import load_npcs, load_archetypes, load_world_bible, run_all

async def main():
    demo = Path("examples/rusted_lantern")
    await run_all(
        npcs=load_npcs(demo / "characters.yaml"),
        archetypes=load_archetypes(demo / "player_archetypes.yaml"),
        world_bible=load_world_bible(demo / "lore"),
        api_key="...",
        out_dir=demo / "out",
    )

asyncio.run(main())
```

## Roadmap

- **Ink and Ren'Py exporters** — same branch data, additional formats.
- **Mid-dialog branching** — detect turns where the NPC has multiple
  equally-valid replies (T=0.9 resampling + embedding divergence) and emit
  nested `->` options inside a branch, not just at the top.
- **Judge-enabled mode by default** — generate 2-3 candidates per archetype,
  keep the highest-scored, surface scores in the JSONL metadata.
- **Local-model path** — validated Ollama + vLLM recipes for an
  offline-capable pipeline.
- **Godot / Unity / Unreal plugin recipes** — drop the generated Yarn files
  in, wire them to your dialog runtime.

## Acknowledgements

Built on [afterimage](https://github.com/altaidevorg/afterimage) — the
two-agent loop, persona tree, hybrid judge, and provider infrastructure all
come from there.

## License

Apache License 2.0. See [LICENSE](LICENSE).
