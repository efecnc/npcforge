# Authoring a new world

One-page guide for pointing npcforge at a new setting. Updated for
v0.8.1 — full generator trio (NPCs / intents / barks), stub resolution,
state layer (`time_of_day`, disposition, quest stages), both
state-aware greeting modes (enum-keyed via `gen greetings` and
visit-counter via `gen repeat-greeting`), **character depth**
(cross-cast relationships + structured knowledge gates), and
**character state evolution** (voice shifts at quest beats).

## The four files

```
my_game/
├── lore/
│   └── <anything>.md        Any number of markdown files. All are
│                            concatenated (lexicographic order) and
│                            used as the world bible.
├── characters.yaml          Top-level `npcs:` list. Hand-author some,
│                            let `gen npcs` append more — both work.
├── player_intents.yaml      Top-level `intents:` list.
├── variables.yaml           Optional. Top-level `variables:` list —
│                            project state (time_of_day, bounty,
│                            disposition) that generators can reference.
└── barks.yaml               Optional. Top-level `barks:` list.
```

Plus a cache that npcforge writes itself:

```
my_game/.npcforge/
└── world_profile.json       Auto-inferred from lore/*.md on first use.
                             Editable; downstream generators respect
                             whatever is in it.
```

## The recommended flow

### 1. Write the world bible

Drop one or more `.md` files into `my_game/lore/`. Cover:

- **Where** — city / region / planet. Districts or quarters if relevant.
- **When** — year, season, recent political shift.
- **Who rules** — factions, corps, guilds, gangs. Not NPCs —
  the power blocs NPCs answer to.
- **Canonical terms** — what the setting calls money, law enforcement,
  communication, magic/tech. (`eddies` not `dollars` in 2077;
  `wire` not `text` in 1899.)
- **Tone** — one paragraph naming the register.

No word count required. 300–800 words per file is typical.

### 2. Let npcforge read your lore

```bash
npcforge world infer --demo-dir my_game
```

One LLM call. Produces `my_game/.npcforge/world_profile.json` with
genre, era, tone, rating, register ceiling, canonical terms,
anachronism blocklist, and notes. **Inspect it** — if anything is
wrong, edit the JSON directly and every downstream generator picks it
up.

```bash
# re-read the cached profile without calling the LLM
npcforge world show --demo-dir my_game

# force a fresh inference (overwrites cache)
npcforge world infer --demo-dir my_game --refresh
```

### 3. Generate — or hand-author — your cast

Three authoring modes, mix and match in the same `characters.yaml`:

```bash
# Option A: hand-author NPCs in characters.yaml. Untouched forever.

# Option B: let npcforge propose NPCs from a brief / roles. ADDITIVE —
# never overwrites existing entries.
npcforge gen npcs --demo-dir my_game --n 3 \
    --brief "the surviving cast of an abandoned frontier mining town"

# Option C: one NPC per role, maximum determinism.
npcforge gen npcs --demo-dir my_game \
    --roles "quest-giver with a map, drunk regular with rumors, suspicious stranger"

# Preview without writing:
npcforge gen npcs --demo-dir my_game --n 3 --dry-run
```

Each call reads the cached world profile, the lore, the existing
cast, and the project-wide intent ids — so new NPCs are stylistically
consistent and do not duplicate roles already in the file.

### 4. Write (or generate) the intent catalog

Three authoring modes here too, mix and match in the same
`player_intents.yaml`:

```bash
# Option A: hand-author intents. Best when you already know the verbs
# players need in this setting.

# Option B: let npcforge propose additions. ADDITIVE — never overwrites.
npcforge gen intents --demo-dir my_game --n 8 \
    --brief "physical / social conflict intents this setting is missing"

# Option C: preview before writing.
npcforge gen intents --demo-dir my_game --n 5 --dry-run
```

A minimal hand-authored entry looks like:

```yaml
# player_intents.yaml
intents:
  - id: ask_about_bounty
    name: "Ask About a Bounty"
    description: >
      Ask about a named fugitive, a wanted poster, or a standing reward.
    opening_intent: >
      Produce a poster or name a wanted person.
```

See the intents files in the three starter worlds under
[`examples/`](.) for tone-appropriate catalogs.

Assign each NPC a subset via `allowed_intents` in `characters.yaml`.
Keep lists to 4–8 items per NPC. A ripperdoc does not accept `flirt`
mid-operation. A Pinkerton agent does not accept `barter_wares`.

### 5. (Optional) Bark triggers — hand-author or generate

```bash
# Hand-author triggers in barks.yaml, OR:
npcforge gen barks --demo-dir my_game --for-npcs mira_vesser --n 3
npcforge gen barks --demo-dir my_game --n 2   # 2 triggers per NPC across the cast
```

A hand-authored entry:

```yaml
# barks.yaml
barks:
  - npc: mira_vesser
    triggers:
      - id: greet_patron
        description: "A new patron crosses the threshold at dusk."
        n: 10
```

Triggers are situational cues — not directives. Good: *"A corp suit
walks into the Mox."* Bad: *"React to seeing a corp."*

`gen barks` produces `(id, description, n)` proposals; the actual
1-line bark utterances are still produced by `build --mode barks`.

### 5b. Stubs — hand-author the hint, let npcforge fill the rest

Drop a minimal entry into `characters.yaml` and mark it with
`_generate: true`. The next `resolve stubs` call expands it.

```yaml
# characters.yaml — mixed authoring modes
npcs:
  # fully hand-authored — untouched forever
  - id: mira_vesser
    name: "Mira Vesser"
    role: "Tavernkeeper of the Rusted Lantern"
    voice: "Gruff, dry, pragmatic."
    # ...

  # stub — role + voice hints only. resolve stubs fills the rest.
  - id: the_rival_tavernkeeper
    _generate: true
    role_hint: "a competing tavernkeeper who moved into Emberfall last spring"
    voice_hint: "slick, smiling — Mira's exact opposite"
```

Then:

```bash
npcforge resolve stubs --demo-dir my_game
# Only fills entries with `_generate: true`. Preserves everything else.
# Rewrites characters.yaml in place; non-stub ordering and top-level
# keys (`world:`, `tone:`) survive.
```

The expanded sheet inherits the world profile's anachronism blocklist,
the project-wide intent ids, and respects the hints you provided —
ids stay exactly as you wrote them.

### 5c. Declare project state (v0.6.0+)

Drop a `variables.yaml` with the state your game cares about:

```yaml
# variables.yaml
variables:
  - id: time_of_day
    type: enum
    values: [dawn, morning, afternoon, dusk, night]
    default: morning
    description: "Hour-bucket of the in-game clock."

  - id: player_bounty
    type: int
    range: [0, 1000]
    default: 0

  - id: disposition_mira
    type: int
    range: [0, 100]
    default: 50
    description: "Mira's opinion of the player."
```

Supported types: `enum` (string with fixed value set), `int`, `float`,
`bool`, `string`. `enum` variables drive the `gen greetings` generator;
all types appear at the top of `world.yarn` as `<<declare>>` lines so
generated Yarn compiles standalone.

Generate time-of-day greetings for some or all of the cast:

```bash
npcforge gen greetings --demo-dir my_game --variable time_of_day
# → one <npc>_greet_time_of_day.yarn per NPC, with a 5-branch <<if>>
# chain keyed on $time_of_day.
```

Your game engine just sets `$time_of_day` on scene load and jumps into
the greeting node. Mira says something different at dawn vs. night.

And for visit-count-gated greetings (no project variable required —
Yarn's `visited_count()` tracks it for you):

```bash
npcforge gen repeat-greeting --demo-dir my_game --only-npcs mira_vesser --n 4
# → mira_vesser_repeat_greet.yarn:
#   <<if visited_count(node) == 0>>  "Table's empty. Drink?"
#   <<elseif visited_count(node) == 1>>  "Seen you before."
#   <<elseif visited_count(node) == 2>>  "You're getting comfortable."
#   <<else>>  "Don't bother with a menu; you know what you like."
```

Opt each NPC in to the variables they react to via the new `reacts_to`
field on the character sheet:

```yaml
- id: mira_vesser
  # ... other fields ...
  reacts_to: [time_of_day, player_bounty, disposition_mira]
```

Reserved for state-aware dialogue coming in v0.7+; harmless no-op today.

### 6. Build the Yarn files

```bash
npcforge build --demo-dir my_game --mode all
```

Outputs land in `my_game/out/`: `<npc>.yarn`, `<npc>_bark_<trigger>.yarn`,
`world.yarn`, `lint.md`, `manifest.json`.

## Voice ceiling — pick by reading level, not by character class

| Ceiling | Feels like |
|---|---|
| `grade_3` | a child, a trauma survivor, someone drunk or very old |
| `grade_5` | field workers, drifters, traumatized miners, swamp guides |
| `grade_8` | craftspeople, bartenders, guards, street vendors |
| `high_school` | fixers, merchants, most middle-class characters |
| `college` | scholars, detectives, clerics, corp suits |
| `academic` | aristocrats, senior priests, pulpit-ready clergy |

Setting this right on the first draft is 80% of voice consistency.
`gen_npcs` picks appropriately from role keywords, but you can always
override by hand in the YAML.

## Character depth — relationships and knowledge gates (v0.8.0)

Two optional fields on every NPC sheet unlock cross-cast awareness
and gated reveals:

```yaml
npcs:
  - id: mira_vesser
    # ... standard fields ...

    relationships:
      - npc_id: gereth_blackstone
        opinion: "protective, guilty"
        reason: >
          She sold the mine lease to the dwarven expedition; Gereth
          surviving is a daily reminder.
      - npc_id: kess_the_knife
        opinion: "sees through her, lets her stay anyway"
        reason: "Whoever Kess works for, their coin still spends here."

    knowledge:
      - id: sold_mine_lease
        fact: >
          Mira signed the lease over to the Grindholt dwarves. The
          original document is in the strongbox under the bar.
        gate: >
          Reveals only if the player has already mentioned the
          expedition AND offered coin or shown a Moon Court token.
        reveal_lines:
          - "Aye. The paper's mine. Was."
          - "I signed it over, friend. That's the last honest thing I'll say about the deep."
        deflect_lines:
          - "The deep keeps its own paperwork."
          - "Expedition's business. Not mine."

      - id: broken_seal
        fact: >
          Mira broke the original sealing ward on the lower mine
          herself, without understanding what it was.
        gate: "Never reveals directly. Players must infer."
        deflect_lines:
          - "Some questions aren't drink-sized."
```

**What the fields do**

- **`relationships`** — the LLM references other NPCs with the declared
  opinion + reason instead of inventing stances. Ground the reason in
  world-bible detail so the model has less room to drift into generic
  fantasy priors ("dwarves are blacksmiths").
- **`knowledge`** — structured facts each NPC possesses. `gate` is
  free-text describing when the fact can be revealed; `reveal_lines`
  and `deflect_lines` are tone exemplars (not quoted verbatim) that
  steer the model's register on each side of the gate.

Works on Gemini 2.5-flash: Gereth's trauma gate opens only when the
player names a parallel loss first; Mira's locket gate opens
incrementally as the player offers coin + mentions the expedition.

### Character state evolution (v0.8.1)

NPCs whose voice should shift at quest beats declare it on the sheet:

```yaml
- id: gereth_blackstone
  state_evolution:
    - trigger: "quest_locket_stage >= 3"
      voice_shift: >
        The four-note hum halves in frequency. Sentences grow longer and
        more complete. The 'twelve, one' repetition still surfaces but only
        in moments of real grief.
      description: >
        After the player has investigated the lower mine alongside Gereth,
        his trauma eases — the locket is no longer his alone.

    - trigger: "disposition_mira < 20"
      voice_shift: "Stops defending Mira. Will answer questions about her sold lease if asked."
      description: "When the town has turned on Mira, Gereth's quiet loyalty breaks."
```

Each entry applies as a **modifier** on the NPC's core voice, not a
replacement. The respondent prompt lists active shifts; the LLM layers
them onto whatever it would otherwise generate. Trigger syntax is
free-text — same pattern as `knowledge.gate`. Writers describe the
condition in prose; the LLM honours it. A structured
`{variable, op, value}` resolver that reads the state layer at build
time is on the v0.8.2 roadmap.

## Common mistakes

1. **Writing the lore and then hand-authoring characters.yaml from
   scratch.** With v0.4.0 you can let `gen npcs` do 80% of it and fill
   specific characters with stubs. Even if you want full control,
   generate a draft, then overwrite the fields you disagree with.
2. **Typos in `allowed_intents`.** Silently dropped. Run
   `npcforge list-npcs --demo-dir my_game` and check the intents
   column.
3. **Tone in the character sheet instead of the world bible.**
   "Night City is kinetic" is lore. "This NPC is tired today" is the
   sheet.
4. **`sample_lines` that are too punchy.** The LLM will quote them
   verbatim. Write them as *tone*, not as hits.
5. **Bark triggers written as instructions.** *"Say something about
   the fog"* is a directive. *"White swamp-fog rolls in"* is a world
   event.
6. **Editing `.npcforge/world_profile.json` and then running
   `world infer` without `--refresh`.** The cache is respected by
   default. Use `--refresh` when you want a fresh LLM pass.

## Ready-to-run starters

- [`examples/rusted_lantern/`](rusted_lantern/) — low fantasy, small town, 5 NPCs
- [`examples/night_city_2077/`](night_city_2077/) — cyberpunk noir, 5 NPCs
- [`examples/saint_denis_1899/`](saint_denis_1899/) — frontier western, 5 NPCs

Copy any of them, rename the folder, edit the lore in place. That is
the fastest path to a new world.
