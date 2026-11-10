# Story Pipeline: Build Spec (for Freebuff)

Put this file in the project root as `BUILD_SPEC.md`. Run `freebuff` in that folder and give it ONE milestone at a time (see "How to drive Freebuff" at the end). Commit after each milestone.

## 1. What we are building

A Python command-line pipeline that turns a short concept brief into a finished-quality novel through small "skills" (instruction files), code-run randomness, and automatic quality gates. It is story-agnostic: the story is only an input.

Principles:
- Skills are plain Markdown instruction files. Code orchestrates; models write.
- Randomness comes from code (seeded), never from the model alone.
- Every stage saves its output to disk and can be resumed.
- Three human checkpoints: approve concept+cast, approve outline, final read.
- Honest publishing: the tool outputs a KDP disclosure checklist. AI-generated text and images must be disclosed on KDP.
- Never generate near-duplicates of existing books. The originality gate is mandatory.

## 2. Hard constraints

- Python 3.11+, standard library plus `pyyaml`, `requests`, `pytest`. Nothing else unless asked.
- Models and search are behind adapters. Changing the model = changing one config file.
- Adapters to build: `manual` (writes the prompt to a file, waits for the user to paste the reply into another file; works with any chat tool), `openai_compatible` (base_url + model + API key from env vars; works with OpenRouter and similar), `echo` (returns a fixed string, used in tests).
- DO NOT build an adapter that calls Freebuff's backend or any unofficial proxy of it. Freebuff is a coding agent for building this tool, not a story API; using it as one is unsupported and may get the account banned.
- No secrets in files. API keys come from environment variables.
- Every function that touches a model must be testable with the `echo` adapter.

## 3. Directory layout

```
story-pipeline/
  BUILD_SPEC.md
  README.md
  config.yaml                 # active adapters, chaos dial, seed
  skills/                     # one .md per skill (see section 5)
  tables/                     # randomizer tables (JSON)
  pipeline/
    __init__.py
    cli.py                    # `story` command
    runner.py                 # runs stages, saves outputs, handles resume/approve
    adapters/
      base.py                 # LLM / Search / Image interfaces
      manual.py
      openai_compatible.py
      echo.py
    randomizer.py
    ledger.py                 # state ledger (numbers, inventory, locations)
    gates/
      linter.py               # repetition and AI-tell checks (no AI)
      ledger_check.py
      originality.py
      rubric.py               # critique prompts and scoring
    schemas.py                # dataclasses + validation
  projects/<slug>/
    concept.yaml
    rolls.json
    ledger.json
    stages/NN-<name>/         # output.md + meta.json for every stage
    chapters/ch01.md ...
    reports/
  tests/
```

## 4. Data formats

### concept.yaml
```
slug: my-book
working_title: ""
genre: ""
tone_dial: 1          # 0 cozy .. 3 action-comedy
audience: ""
target_words: 60000
pen_name: ""
premise_seed: ""      # the user's raw idea, free text
must_include: []
must_avoid: []
```

### Character sheet (validate in schemas.py)
```
id, name, role (protagonist|foil|mentor|ally|pressure|comic|wildcard)
gender, age, occupation, background
look: {build, hair, skin, signature_clothing, marks: [{what, meaning, placement}]}
physical_differences: [{what, how_it_shapes_behavior}]   # optional, never a gimmick
intelligence_profile: {sharp_at: [], blind_at: [], overconfident_about: []}
emotional_core: {want, need, wound, false_belief, fear, coping_habit, start_state, arc_by_act: [], laughs_at, cries_at}
voice: {rhythm, vocabulary, tics: [], never_says: []}
relationships: [{to, bond, friction}]
locked: []            # field names the user froze
```
Do NOT store a numeric IQ. Use the intelligence profile.

### ledger.json
Structured state: `{ "chapter": n, "entities": { id: { "level":..., "skills": {...}, "inventory": [...], "location": "..." } }, "events": [...] }`. Every chapter's writer step must emit a ledger delta (JSON) and `ledger_check` validates it against rules in the series bible (no stat jumps without an event, no items from nowhere).

### rolls.json
Every random pick: `{stage, key, table, value, seed, locked, timestamp}`.

## 5. Skills (files in skills/)

Each skill file has YAML frontmatter then sections `Purpose`, `Inputs`, `Steps`, `Output format`, `Do not`, `Self-check`.

Frontmatter: `name`, `stage` (number), `model_tier` (planner | writer | checker | none), `inputs`, `outputs`, `human_gate` (true/false), `uses_search` (true/false), `uses_randomizer` (true/false).

Skill list, in run order:
0. `randomizer`: engine, not a prompt; see section 6.
1. `intake`: raw idea to concept brief (one page).
2. `market_research` (search): top comparable titles, tropes, review complaints, a "what's missing" sheet.
3. `reference_analysis` (search): from public reviews and analyses of comparable books, extract chapter shape, cast cadence, tension ratio, set-piece types. NEVER reproduce text from those books.
4. `setting_research` (search): era/place details, daily life, vocabulary, sensory palette, common mistakes. For secondary worlds, produce internal worldbuilding rules instead.
5. `premise_inversion`: list what the genre expects, then choose what to flip. Must differ from the comparison titles.
6. `theme_premise`: central question, emotional arc, the question under the comfort/comedy.
7. `tone_ceiling`: how much conflict each chapter may carry given `tone_dial`.
8. `character_creation` (randomizer): roles first, then sheets. Every secondary character gets their own want and stakes.
9. `ensemble_check`: flag cast problems (see 8). HUMAN GATE 1 after this: approve concept + cast.
10. `series_bible`: world rules, system/progression rules with real numbers, cast, timeline. Writes the initial ledger.
11. `outline` (randomizer): chapter beats, one new cast member at a time, a background threat humming, chapter shapes varied, illustration slots. HUMAN GATE 2: approve outline.
12. `scene_card`: for each chapter, scenes with goal, conflict, turn.
13. `narrator_voice`: narrator voice and POV guide plus a dialogue subtext guide (every line has an unspoken goal; emotion shown as sensation, not named).
14. `chapter_writer` (writer tier): one chapter at a time from bible, voice guide, scene cards, last two chapter summaries, and ledger. Rules: protagonist solves her own problems; no lecture conversions; vary sentence length; banned phrases list applies.
15. `quality_gates`: runs linter, ledger_check, continuity critique, originality check, rubric critique. Failing chapters go back to the writer with the reports, up to 3 loops.
16. `opening_ending_polish`: extra revision budget for chapter 1 and the final chapters.
17. `reader_test_pack`: exports the first 3 chapters plus a feedback form for 3 to 5 real readers. HUMAN GATE 3 includes the final read.
18. `illustration_prompts`: one prompt per marked scene, reusing character look fields verbatim for consistency.
19. `packaging`: blurb, title options, 7 keywords, categories, cover brief, EPUB build, and `KDP_DISCLOSURE.md` (what must be declared).

## 6. Randomizer spec

- Tables live in `tables/*.json` as `{ "name": "...", "entries": [{"value": "...", "weight": 1, "tags": []}] }`. Starter tables: `names_given`, `names_family` (phonetic patterns, not fixed lists), `quirks`, `flaws`, `talents`, `blind_spots`, `physical_marks`, `emotional_starts`, `speech_tics`, `setting_customs`, `smells_tastes`, `weather`, `complications`, `chapter_shapes`, `imagery_domains`, `ending_types`, `banned_names`.
- Deterministic: `random.Random(hash(seed, stage, key))` so the same seed reproduces the same rolls.
- `chaos_dial` 0 to 3 sets how many random constraints are applied per stage.
- Commands: `story roll <stage>` (roll and log), `story lock <key>`, `story reroll <key>`.
- Memory: `tables/used.json` records picks across projects so entries are not reused.
- Anti-default: before applying a roll, check it against `banned_names` and a `ai_default_plots` list (small-town festival, reconnecting with tradition, and similar). Reject and reroll.
- Fit check: after rolls, a `checker`-tier prompt must accept, adapt, or reject each roll with a one-line reason; rejected rolls are rerolled (max 3).

## 7. Quality gates (code first, models second)

- `linter.py` (no AI): flags repeated 3 to 5 word phrases, overused words, uniform sentence length, banned phrases, tic words per 1,000 words, and repeated paragraph openers. Outputs a JSON report with counts and line numbers.
- `ledger_check.py`: verifies the chapter's ledger delta against the bible's rules.
- `originality.py`: takes search-result snippets for the premise and top comparable titles, computes n-gram overlap and compares plot beats and names against them; fails above a set threshold. Must never store or reproduce copyrighted text beyond short snippets in a report.
- `rubric.py`: a critique prompt scoring a chapter 1 to 5 on: scene goal and turn, subtext, sensory specificity, voice consistency, humor/comfort delivery, pacing, and "does the protagonist act". A chapter passes at 4+ on every item.

## 8. Ensemble check rules

Flag: too many "quirky and clever" characters; two characters with the same voice; no character whose want conflicts with another's; a cast of one age, gender, or temperament; stereotyped portrayals; anyone whose flaw exists only to be "fixed" by the protagonist.

## 9. CLI

```
story init <slug>            # create project, copy concept template
story run <stage|all>        # run a stage or everything until the next human gate
story approve <gate>         # pass a human gate
story roll|lock|reroll ...
story check <chapter>        # run gates on one chapter
story status                 # stage table: done / needs approval / failed
story export                 # EPUB + KDP_DISCLOSURE.md
```
Runs must be resumable and idempotent. Never overwrite an approved stage without `--force`.

## 10. Milestones and acceptance tests

M1: scaffold + adapters (`echo`, `manual`, `openai_compatible`) + config + `story init` + `story status`. Tests: init creates the tree; `echo` adapter round-trips; `manual` adapter writes prompt file and reads reply file.
M2: randomizer + tables + rolls log + locks/rerolls. Tests: same seed gives same rolls; locked keys never change; banned names never appear.
M3: schemas + `character_creation` + `ensemble_check` skills and validators. Tests: invalid sheet rejected; no numeric IQ field accepted; ensemble check flags a constructed bad cast.
M4: skills 1 to 7 (intake through tone_ceiling) with search adapter interface (stub + one simple implementation). Tests: each stage saves `output.md` and `meta.json`.
M5: series_bible + ledger + ledger_check. Tests: a delta with an item from nowhere fails.
M6: outline + scene cards + narrator_voice.
M7: chapter_writer + linter + rubric + the 3-loop revision flow.
M8: originality gate, reader_test_pack, illustration_prompts, packaging, EPUB export, KDP_DISCLOSURE.md.

## 11. How to drive Freebuff

- Run `freebuff` inside the project folder. Say: "Read BUILD_SPEC.md. Do only milestone M1. Write the tests first, then the code, then run the tests. Don't start M2."
- After each milestone: run `pytest`, read the diff, `git commit`. Then start the next milestone in a fresh session.
- Keep prompts short and point at spec sections ("see section 6") instead of pasting them.
- Freebuff is ad-supported and has daily credit limits; its model list and limits change. Check them before long sessions.
- Some free models may collect submissions for training. Don't paste private data or API keys into it.
- If it drifts from the spec, say: "Re-read section N of BUILD_SPEC.md and fix to match."