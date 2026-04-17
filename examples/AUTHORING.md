# Authoring a new world

One-page guide for pointing npcforge at a new setting. Updated for
v0.3.0 — the generators-first workflow.

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

### 4. Write the intent catalog (for now, manual)

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

`gen intents` is on the roadmap but not yet shipped — for now,
hand-author 10–20 intents. See the intents files in the three starter
worlds under [`examples/`](.) for tone-appropriate examples.

Assign each NPC a subset via `allowed_intents` in `characters.yaml`.
Keep lists to 4–8 items per NPC. A ripperdoc does not accept `flirt`
mid-operation. A Pinkerton agent does not accept `barter_wares`.

### 5. (Optional) Write bark triggers

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

## Common mistakes

1. **Writing the lore and then hand-authoring characters.yaml from
   scratch.** With v0.3.0 you can let `gen npcs` do 80% of it. Even if
   you want full control, generate a draft, then overwrite the fields
   you disagree with.
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
