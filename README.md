# npcforge

**Production-oriented NPC dialogue generator — walk-up conversations *and* bark libraries — with Yarn Spinner export.**

Drop in a world bible, character sheets, and player intents. Get game-engine-ready dialogue where every intent is a different branch inside every NPC's node, plus dozens of reactive 1-line barks for combat / ambient / witness triggers. Powered by [afterimage](https://github.com/altaidevorg/afterimage).

```
world bible + NPC sheets + player intents + bark triggers
           │
           ▼
   afterimage (two-agent loop + structured output + judge)
           │
           ▼
   Yarn Spinner .yarn (walk-up + barks) + JSONL traces + manifest + lint report
```

## Why

Convai / Inworld are hosted and charge per call. Writing branching dialogue and barks by hand takes months. npcforge trades both costs for one local run: **lore-grounded, voice-consistent, offline-capable, and covering both major NPC dialogue modes** (walk-up and barks — barks are ~80% of what a shipping RPG actually needs).

## Install

```bash
pip install -e .
```

Python 3.10+. afterimage, PyYAML, and pydantic are pulled in as dependencies. For post-run validation install the [Yarn Spinner compiler](https://docs.yarnspinner.dev/getting-started/editing-with-visual-studio-code) so `ysc` is on `PATH`.

## Quick start

```bash
export GEMINI_API_KEY=...

# walk-up dialogue for every NPC × each NPC's allowed intents
npcforge --demo-dir examples/rusted_lantern --mode walk_up

# bark libraries for the triggers declared in barks.yaml
npcforge --demo-dir examples/rusted_lantern --mode barks

# everything
npcforge --demo-dir examples/rusted_lantern --mode all

# iterate on a subset — regen only Mira and Kess
npcforge --demo-dir examples/rusted_lantern --mode all --only-npcs mira_vesser,kess_the_knife
```

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

Three settings ship in the repo — each a full walk-up + barks pipeline:

- **[`examples/rusted_lantern/`](examples/rusted_lantern/)** — low fantasy, 5 NPCs in a mining-town tavern
- **[`examples/night_city_2077/`](examples/night_city_2077/)** — cyberpunk noir in Watson: ripperdoc, Mox bartender, Aldecaldos fixer, Maelstrom initiate, Netwatch agent
- **[`examples/saint_denis_1899/`](examples/saint_denis_1899/)** — frontier western: Creole boarding-house keeper, Cajun swamp guide, clergyman, Lemoyne Raider, Pinkerton agent

```bash
npcforge --demo-dir examples/night_city_2077 --mode all
npcforge --demo-dir examples/saint_denis_1899 --mode all
```

Each covers 12 intents × 28–32 walk-up branches + 52–70 barks on a full run. Copy any of them and edit in place to bootstrap a new setting. Full authoring walkthrough in [`examples/AUTHORING.md`](examples/AUTHORING.md).

## Iteration speed

- `--only-npcs id1,id2` — regen just those NPCs (full walk-up + barks for them).
- `manifest.json` — content hashes for every file so you can diff runs.
- `lint.md` — scan voice violations without opening Yarn files.
- `ysc compile` — automatic post-run syntactic validation when the compiler is available.

## Using it as a library

```python
import asyncio
from pathlib import Path
from npcforge import (
    load_npcs, load_intents, load_barks_config, load_world_bible, run_all,
)

async def main():
    demo = Path("examples/rusted_lantern")
    await run_all(
        npcs=load_npcs(demo / "characters.yaml"),
        intents=load_intents(demo / "player_intents.yaml"),
        world_bible=load_world_bible(demo / "lore"),
        barks_config=load_barks_config(demo / "barks.yaml"),
        api_key="...",
        out_dir=demo / "out",
        mode="all",
    )

asyncio.run(main())
```

## Roadmap

- **Mid-dialog branching** — resample high-valence NPC turns at T=0.9, emit nested `->` options when continuations diverge.
- **Ink and Ren'Py exporters** — same `Branch` data shape, additional writers.
- **World-state variables** — `<<set $quest_stage = 3>>` threaded through prompts and emitted into Yarn conditionals.
- **Knowledge gates** — structured `{fact, gate, reveal_lines, deflect_lines}` per NPC so reveals respect quest state.
- **Relationship graph** — NPC opinions of each other, injected into prompts.
- **Localization scaffold** — deterministic `line_id`, `lines_<locale>.csv` stubs, length-budget hints for lip sync.
- **More modes** — `shop`, `quest_success`, `quest_fail`, `repeat_greeting`, `group_chatter_pair`.
- **NPC-level concurrency** for 1000-NPC scale.
- **Judge-enabled mode** — generate N candidates per branch, keep highest-scored.
- **Local-model recipes** — validated Ollama + vLLM offline pipelines.

## Acknowledgements

Built on [afterimage](https://github.com/altaidevorg/afterimage) — two-agent loop, persona infrastructure, provider abstraction, structured output.

## License

Apache License 2.0. See [LICENSE](LICENSE).
