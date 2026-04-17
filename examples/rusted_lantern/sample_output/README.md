# Sample output — The Rusted Lantern (Gemini 2.5-flash)

Frozen reference of what a full `npcforge build --mode all` run produces
for the Rusted Lantern demo. Committed so anyone browsing the repo can
read real generated dialogue without installing the package.

Regenerate into a fresh `examples/rusted_lantern/out/` directory with:

```bash
export GEMINI_API_KEY=...
npcforge build --demo-dir examples/rusted_lantern --mode all
```

`out/` is `.gitignore`-excluded; only `sample_output/` lives in git.

## What's in here

| File | What it shows |
|---|---|
| `<npc>.yarn` | Walk-up dialogue node — one `-> [intent]` option per intent this NPC accepts. |
| `<npc>.jsonl` | Raw afterimage conversation rows that produced the Yarn (every turn, every score when the judge is enabled). |
| `<npc>_bark_<trigger>.yarn` | Bark library node that cycles through variants via `visited_count()`. |
| `<npc>_bark_<trigger>.json` | Machine-readable bark library: text + emotion + intensity per variant. |
| `world.yarn` | Master `Start` node routing to every NPC. |
| `lint.md` | Voice-ceiling lint — forbidden-word hits per NPC (zero in this run). |
| `manifest.json` | Content hashes, elapsed time, model used, lint totals. |

## Highlights — what to open first

- **`mira_vesser.yarn`** — 9 intent branches. Watch her accent markers hold: she says "the deep" never "mine", drops "the" in short clauses, stays transactional under both threats and bribes.
- **`gereth_blackstone_bark_sees_new_face.json`** — 10 bark variants. Every single one carries his hum (`hmm-hmm-hmm-hmm`) and the `twelve, one` trauma motif. 10/10 `scared`.
- **`sister_adelie.yarn`** — 7 intent branches. Formal lilting voice holds across every branch; she asks questions as an interrogation technique.
- **`kess_the_knife.yarn`** — 7 intent branches. Flirtation, banter, deflection. Never misgendered the player in the generated output.
- **`lint.md`** — empty. Every forbidden word list (Mira's "intriguing/peculiar", Gereth's "fascinating/undoubtedly") held across all 84 generated artefacts.

## Run stats (from `manifest.json`)

- 5 NPCs × their allowed intents → 32 walk-up branches
- 6 bark triggers × 6-10 variants each → 52 unique barks
- 332 seconds end-to-end on Gemini 2.5-flash
- Zero lint hits
