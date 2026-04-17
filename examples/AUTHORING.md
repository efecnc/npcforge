# Authoring a new world

One-page guide for pointing npcforge at a new setting.

## The four files

```
my_game/
├── lore/
│   └── <anything>.md        Any number of markdown files. All are
│                            concatenated (lexicographic order) and
│                            stacked under every NPC's grounding context.
├── characters.yaml          Top-level `npcs:` list.
├── player_intents.yaml      Top-level `intents:` list.
└── barks.yaml               Optional. Top-level `barks:` list.
```

Run it with:

```bash
npcforge --demo-dir my_game --mode all
```

That's the whole contract.

## Step by step

### 1. Draft the world bible (`lore/*.md`)

Write 300–800 words per file. Cover:

- **Where** — city / region / planet. Districts or quarters if relevant.
- **When** — year, season, recent political shift.
- **Who rules** — factions, corps, guilds, gangs, crowns. Not NPCs — the
  power blocs NPCs answer to.
- **Canonical terms** — the words your setting uses for money, law
  enforcement, communication, magic/tech. ("eddies" not "dollars" in
  2077; "wire" not "text message" in 1899.)
- **Tone** — one paragraph at the bottom naming the register ("kinetic
  and funny when scared"; "humid and tired").

Split into multiple files if you want chapters. All files get loaded.

### 2. Draft `player_intents.yaml` (10–20 intents)

Intents are **what a player can try to do this turn** — not who the
player is. Reusable across genres:

| Universal | Setting-flavored examples |
|---|---|
| `ask_for_directions` | `ask_about_braindance` (2077) |
| `bribe_for_info` | `ask_about_bayou_guide` (1899) |
| `threaten_for_info` | `hack_request` (2077) |
| `flirt` | `ask_about_clergy` (1899) |
| `barter_wares` | `ask_about_fixer_jobs` (2077) |
| `farewell` | `ask_about_raiders` (1899) |
| `confess_desperation` or `confess_sin` | |

Each intent needs an `id` (snake_case, stable), a `name` (pretty,
shows up as the Yarn option label), a `description` (2–4 lines the LLM
reads), and an `opening_intent` (how the player opens when this intent
is selected).

### 3. Draft `characters.yaml`

Each NPC entry fills these fields (all except `id`, `name`, `role`,
`voice` are optional — but you want them):

| Field | Purpose |
|---|---|
| `id` | snake_case, stable, used in Yarn titles |
| `name` | display name, used in dialog lines |
| `role` | one-line job/archetype |
| `voice` | 2–4 sentence voice bible |
| `background` | 2–4 sentence history, NPC knows this about themselves |
| `motivations` | ordered list. Top one drives most answers. |
| `secret` | one thing the NPC never discloses directly |
| `speech_quirks` | 2–4 tics that should show up naturally |
| `sample_lines` | 2–4 reference lines, tone only, not verbatim |
| `vocabulary_ceiling` | `grade_3` / `grade_5` / `grade_8` / `high_school` / `college` / `academic` |
| `forbidden_words` | hard no-gos. Inflections are caught automatically. |
| `accent_markers` | positive constraints ("drops 'the' in short sentences") |
| `allowed_intents` | subset of intent ids this NPC accepts. Empty = all. |

### 4. Draft `barks.yaml` (optional but recommended)

Triggers are **situational cues** — how you'd describe the moment to a
voice actor. Not directives.

Good: *"A corp suit in a clean Arasaka cut walks into the Mox."*
Bad: *"React to seeing a corp."*

Typical triggers per character:
- **Merchants**: `greet_patron`, `refuse_sale`, `haggle_response`
- **Combatants**: `combat_start`, `takes_hit`, `sees_flatline`
- **Authority**: `begins_interview`, `catches_lie`, `confirms_bounty`
- **Service**: `offers_blessing`, `warns_of_fog`, `finishes_install`
- **Ambient**: `idle_by_fire`, `spots_lawman`, `notices_lie`

Aim for `n: 6–10` per trigger — enough that games rotate without
feeling looped.

## Voice ceiling — pick by reading level, not by character class

| Ceiling | Feels like |
|---|---|
| `grade_3` | a child, a trauma survivor, someone drunk or very old |
| `grade_5` | field workers, drifters, traumatized miners, swamp guides |
| `grade_8` | most craftspeople, bartenders, guards, street vendors |
| `high_school` | fixers, merchants, most middle-class characters |
| `college` | scholars, detectives, clerics, corp suits |
| `academic` | clerics at prayer, professors, aristocrats, senior priests |

Getting this right on the first draft is 80% of voice consistency.

## Intent whitelists — prune aggressively

The wrong `allowed_intents` list is the single biggest quality killer.
Rules of thumb:

- **A ripperdoc** does not accept `flirt` mid-operation. Remove it.
- **A Pinkerton agent** does not accept `barter_wares`. Remove it.
- **A traumatized NPC** does not accept `flirt`. They accept
  `confess_desperation`.
- **A corp suit** accepts `threaten_for_info` (they are unmoved) and
  `bribe_for_info` (they take notes) but not both as equals —
  prioritize by character.

Keep each NPC at 4–8 intents. More than 8 = the character is doing
too many jobs.

## Common mistakes

1. **Typos in `allowed_intents`.** Silently dropped. Run `--only-npcs <id>`
   and check the branch count matches what you expected.
2. **Tone in the character sheet instead of the world bible.** "Night
   City is kinetic" is lore. "This NPC is tired today" is the sheet.
3. **`sample_lines` that are too punchy.** The LLM will quote them
   verbatim. Write them as *tone*, not as hits.
4. **Bark triggers written as instructions.** "Say something about the
   fog" is a directive. "White swamp-fog rolls in" is a world event.
5. **Copying the demo's `forbidden_words` into a modern setting.**
   `intriguing` belongs in the fantasy demo; in Night City you want
   to forbid `doth`, `verily`, `hitherto`. Match forbidden words to
   the era.

## The command

```bash
# walk-up dialogue for every NPC × each NPC's allowed intents
npcforge --demo-dir my_game --mode walk_up

# bark libraries for the triggers declared in barks.yaml
npcforge --demo-dir my_game --mode barks

# both
npcforge --demo-dir my_game --mode all

# iterate on one NPC while you tune their sheet
npcforge --demo-dir my_game --mode all --only-npcs elena_stonekeeper
```

Outputs land in `my_game/out/`. After every run, check `lint.md` for
voice-ceiling hits and `manifest.json` for content hashes and elapsed
time. When Yarn Spinner's `ysc` is on PATH the CLI runs a compile
check automatically.

## Ready-to-run starters

- `examples/rusted_lantern/` — low fantasy, small town, 5 NPCs
- `examples/night_city_2077/` — cyberpunk noir, Watson district, 5 NPCs
- `examples/saint_denis_1899/` — frontier western, 5 NPCs

Copy any of them, rename the folder, and edit in place. That is the
fastest path to a new world.
