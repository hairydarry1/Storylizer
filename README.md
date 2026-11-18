# Story Pipeline

Turns a short concept brief into a finished novel through small Markdown "skills", code-run
randomness and automatic quality gates. The target design is in `BUILD_SPEC.md`; this README
describes what actually works today.

**Status: milestone M7b (chapter writer).** Scaffold, config, the three LLM adapters, four search adapters,
`story init`, `story status`, the seeded randomizer (`story roll`, `story lock`, `story reroll`),
skills 1–14, `story run <stage>`, `story run all`, `story approve` (gates 1 and 2), the series
bible (stage 10), the ledger gate (`story ledger show`, `story ledger validate`), the
model-authored outline and scene cards (strict JSON, three attempts each, no template
fallback), the narrator voice and `story rules merge`. M6c adds per-tier providers, HTTP retries with exponential backoff
and quota-header reporting, `--max-calls` with a persisted per-day call counter, resumable
outline and scene-card stages, and code-assigned closing actors. Stages 15+ are not built yet, so
`export` still prints the milestone that will build it and exits with code 2. M7a adds the
no-AI linter, `story check`, and a 44-entry banned-phrase table; `story check --delta` also
runs the existing ledger gate. M7b adds stage 14: the writer drafts one chapter, a
checker returns a summary and a ledger delta, and the linter, word-count and ledger gates
decide whether the delta is applied.

## Requirements

Python 3.11+, plus `pyyaml`, `requests` and `pytest`. Nothing else.

```bash
pip install -e .        # gives you the `story` command
python -m pytest        # 399 tests
```

Without installing, `python -m pipeline.cli` works from the project folder.

## Use

```bash
story init my-book      # creates projects/my-book/ and a concept template
story status            # stage table: pending / done / needs approval / failed
story status -p my-book # when there is more than one project

story roll 8            # roll and log the character-creation constraints
story lock flaw          # pin a roll so no later reroll can change it
story reroll quirk       # replace one unlocked roll and append to the log

story run all                 # stages 1-9, stopping at human gate 1
story run character_creation   # or run one stage: stage 8
story run ensemble_check       # stage 9: code checks + checker-tier judgment
story approve 1               # human gate 1: approve concept + cast

story run series_bible        # stage 10: bible.md, rules.json, initial ledger.json
story ledger show             # level, xp, inventory, skills and events per character
story ledger validate ch03.json   # the delta gate for one chapter

story check ch01                   # lint a chapter; writes reports/lint-ch01.json + .md
story check ch01 --delta ch03.json # lint and run the ledger gate on one delta

story run outline             # stage 11: the planner writes each chapter (gate 2)
story run outline --skeleton  # deterministic chapters instead (tests / offline dry runs)
story approve 2               # human gate 2: approve the outline
story run scene_card          # stage 12: model-written goal / conflict / turn per scene
story run narrator_voice      # stage 13: voice.md + tables/banned_phrases.json
story run chapter_writer --chapter 3  # stage 14: draft only chapter 3
story run chapter_writer --from 4     # draft from 4, skipping accepted chapters
story rules merge             # merge rules_additions.json and print the diff

story run outline --max-calls 25   # cap model calls for this run
```

`story run` writes `stages/NN-<name>/output.md` and `meta.json` (`cast.json` too for stage 8).
An approved stage is never overwritten without `--force`, and running a stage that has no
`skills/<name>.md` file names the milestone that builds it. `--skeleton` makes stages 11
and 12 write their deterministic text instead of calling the model; it exists for tests and
dry runs, and a real run never falls back to it. `story run all` skips done
stages, retries a failed one, runs stages 1–9 in order and stops at gate 1 with
`story approve 1` as the next command; after gate 1 it runs stages 10–11 and stops at gate 2
(`story approve 2`), then runs stages 12–14 before the next unbuilt stage reports M7c.

Stages 1–7 each write `output.md` and `meta.json` with deterministic structure first:

- **1 intake** restates the concept, fixes genre/audience/tone/length, turns must-include and
  must-avoid into constraints, and lists empty concept fields as open questions.
- **2 market_research** reads `projects/<slug>/inputs/market_notes.md` (ranks, review counts,
  prices) and the configured search adapter, then writes the "What's missing" gap sheet.
- **3 reference_analysis** uses search snippets and the market comparables to describe craft;
  it stores no book text.
- **4 setting_research** covers daily life, vocabulary, sensory detail, scene locations and
  common mistakes, with a real-period/secondary-world split.
- **5 premise_inversion** lists what the genre expects, chooses two or three flips, writes the
  resulting one-line premise and compares it with the stage 2 comparables.
- **6 theme_premise** writes the central question, pressure and emotional arc; stage 8 reads it.
- **7 tone_ceiling** turns `tone_dial` into a conflict ceiling, per-chapter budget and an
  off-the-table list; stage 8 reads the ceiling.

`character_creation` turns the stage 8 rolls into a cast, sends the skill prompt at the
planner tier, and uses the model's cast only if it validates; otherwise the deterministic
draft stands with a note. Its prompt includes a `Story constraints` block with the theme,
premise and tone ceiling from stages 1–7 when they exist, and `meta.json` records them.
Every secondary character needs its own `want` and `stakes`, relationships must point at
existing ids, a numeric IQ field is rejected anywhere in a sheet (`intelligence_profile` is
the only intelligence field), and `locked` fields survive regeneration, including a stage 8
rerun.

`ensemble_check` flags one age, one gender or one temperament, two characters sharing a
voice tic, and more than a third of the cast tagged "quirky and clever" in code. Conflicting
wants, a flaw that exists only to be fixed, and stereotypes go to the checker tier. A
flagged cast leaves stage 9 `failed`; `story approve 1` refuses until it is fixed, or passes
with `--force`. A checker that cannot answer is recorded as a note, never as a silent pass.

`series_bible` is stage 10. It writes `bible.md` (world rules, system and progression, cast,
locations and travel, timeline) and `rules.json` (the machine-readable half: `system_type`
none / litrpg / magic / other, the XP curve and level thresholds, skill unlocks and
prerequisites, item sources and recipes, and a location graph with travel times), then seeds
`projects/<slug>/ledger.json` from `cast.json`. A story without a stat system is valid:
`system_type: none` skips the XP, level and skill checks. An existing ledger with chapters or
applied deltas is kept, never reset.

`story ledger show` prints each entity's level, xp, location, inventory, skills and the
recorded events. `story ledger validate <delta.json>` runs the ledger gate: a delta is a list
of operations (`add_item`, `remove_item`, `xp_gain`, `level_up`, `skill_unlock`, `move`,
`event`) and every one has to be earned. An item needs a recorded event or a recipe whose
ingredients are present, a level-up needs the XP threshold, a skill unlock needs its level and
prerequisites, a move needs an edge in the location graph, and an unknown entity is an error.
Rejected deltas exit 1 with their reasons, and a delta is applied once, so replaying it is
rejected.

`story check <chapter>` takes a path or a chapter name under the project and writes
`reports/lint-<stem>.json` plus a Markdown summary. It flags repeated 3–5 word phrases,
overused words, uniform sentence length, banned phrases, tic words per 1,000 words, and
repeated paragraph openers; thresholds live under `gates.linter` in `config.yaml`. Any flag
exits 1. `--delta` additionally validates that delta with the ledger gate, and either gate
failing exits 1.

`outline` is stage 11, behind gate 2, and it is model-authored. Code and the randomizer fix
the constraints: the chapter count from `target_words` (at least eight, one per secondary
plus one), a shape from `chapter_shapes`, an imagery domain, a tension from 1 to 5, the
actor whose debut the chapter carries, a complication card every third chapter, the threat
schedule and an optional illustration slot on the loud chapters. For each chapter the
planner is called with the concept, theme and premise, the cast sheets, a rules summary,
that chapter's constraints and summaries of the chapters before it; it returns one JSON
object with `title`, `hook`, `beats` of `{actor, action, obstacle, outcome}` and `ends_on`.
The reply must use real cast ids, one actor per beat, at least three beats and non-empty
text, with no banned phrase and no beat that repeats an earlier chapter's beat. Invalid
replies are retried up to three times with the errors fed back; a chapter that still fails
fails the stage and leaves no `outline.json` behind. There is no template fallback.
Five code validators still gate the stage: no more than two chapters in a row share a
shape, every secondary debuts in a different chapter, the background threat reaches at
least 40% of chapters, the protagonist acts in at least 70% of resolution beats, and the
tension curve is not monotonic. `story approve 2` refuses a failed outline unless
`--force`. Each validated chapter is written to `stages/11-outline/partial.json` as soon as it passes,
so a rerun continues from the first missing chapter (`meta.json` records `model.resumed`);
the partial file is deleted only when the whole stage completes. A code-assigned closing
actor keeps the protagonist closing at least 70% of chapters: chapter 1 always closes on the
protagonist, a seeded randomizer picks the other chapters, and each one closes on a
secondary who has already debuted. The prompt states the assigned actor, the checks reject a
chapter that ends on anyone else, and the five code validators are unchanged. The stage also
writes `rules_additions.json`; `story rules merge` validates
those entries against the rules schema and merges them additively, never overwriting an
existing entry, printing a `+` / `=` diff first.

`scene_card` is stage 12: the planner writes a goal, a conflict and a turn for every scene,
one chapter and one JSON object per call, checked and retried the same way, and resumes from
the same sort of `partial.json`. `narrator_voice`
is stage 13: `voice.md` with the POV, tense, sentence and paragraph targets (from
`craft_targets.json` when present), a dialogue subtext guide and the banned-phrase list,
plus the starter `tables/banned_phrases.json` when the table is missing. Neither has a
human gate.

`chapter_writer` is stage 14, one chapter at a time. The writer tier gets the chapter's
outline beats and scene cards, `voice.md`, bible and rules summaries, the current ledger, the
last two accepted chapter summaries, sampled craft targets and the writing rules (the
protagonist solves her own problems, no lecture conversions, show don't tell, dialogue
carries subtext, no banned phrases, no meta commentary). It writes `chapters/chNN.md` and
inserts `[[ILLUSTRATION: chNN-sK | short description]]` where the outline assigned a slot.
The checker tier then returns strict JSON with a `summary` and a `ledger delta`, retried up to
three times with errors fed back. Before anything is applied, code runs the linter, checks the
word count is within 20% of target and validates the delta; only then does the delta update
`ledger.json` and the summary enter `summaries.json`. A failing chapter is marked
`needs_revision`, its report is saved in `reports/chapter-chNN.json`, and the ledger is left
alone. `--chapter N` drafts one chapter, `--from N` resumes at N, and accepted chapters are
skipped on a rerun.

`story roll` prints the stage header, the chaos count, and a `key | table | value` table.
Rolls are deterministic: the RNG seed is `sha256("{seed}|{stage}|{key}")`, so the same
`config.yaml` seed gives the same book constraints on any machine, in any Python process.
`chaos_dial` in `config.yaml` (0–3) decides how many optional extra constraints accompany
the essentials — stage 8 rolls 5 + chaos, stage 11 rolls 3 + chaos.

Every pick is appended to `projects/<slug>/rolls.json` (`stage`, `key`, `table`, `value`,
`seed`, `locked`, `timestamp`); the newest record for a key is its current value. A lock
marks all of that key's records, and `story reroll` refuses locked keys. `tables/used.json`
remembers picks across projects so two books are not handed the same quirk or syllable-name,
falling back to reuse only when a table has no unused entries left.

Names are generated from the syllable pools in `tables/names_given.json` and
`tables/names_family.json`, then filtered for pronounceability and checked against
`tables/banned_names.json` (AI-default names such as Elara, Voss, Kael, Lyra and Thorne).
If the configured model returns JSON verdicts (`accept` / `adapt` / `reject`), rolls are fit
-checked at the `checker` tier and rejected picks are rerolled up to three times; a model
that cannot answer never blocks a roll, it just prints a warning.

`story init` is idempotent: it creates what is missing and keeps your edits. Pass `--force`
to reset `concept.yaml`, `rolls.json` and `ledger.json` back to their templates.

A project is a folder:

```
projects/my-book/
  concept.yaml     # the brief you fill in
  rolls.json       # randomizer audit log, append-only
  ledger.json      # story state (seeded by stage 10)
  summaries.json   # accepted chapter summaries (stage 14)
  calls.json       # per-day model call counter (M6c)
  inputs/          # market_notes.md and other pasted research
  stages/          # NN-<stage>/output.md + meta.json per stage (+ cast.json at stage 8,
                   #  partial.json while stages 11-12 are unfinished)
  chapters/        # ch01.md, ch02.md, ...
  reports/         # lint, chapter-gate, rubric and originality reports
```

`story status` reads `stages/NN-<name>/output.md` and `meta.json`:
no `output.md` → `pending`; `meta.json` with `"status": "failed"` → `failed`; a stage that
carries a human gate (9 ensemble check, 11 outline, 17 reader test pack) → `needs approval`
until its `meta.json` has `"approved": true`; otherwise `done`.

## Adapters

Adapters are chosen in `config.yaml`, never in code. Three LLM adapters exist:

| type | what it does |
| --- | --- |
| `echo` | returns a fixed string; the default, used by tests |
| `manual` | writes each prompt to a file and waits for you to paste a reply; works with any chat tool |
| `openai_compatible` | `POST {base_url}/chat/completions`; works with OpenRouter, Together, vLLM, LM Studio and similar |

### manual

```yaml
adapters:
  llm:
    type: manual
    options:
      directory: .manual
      timeout: 3600      # seconds to wait for the reply (0 checks once)
      poll_interval: 2
```

Each call writes `.manual/0001.prompt.md` and waits for `.manual/0001.reply.md`. Create the
reply file, paste the model's answer into it, and the run continues. If the wait times out the
command tells you both paths and you can run it again — the same reply file is picked up.

### openai_compatible

```yaml
adapters:
  llm:
    type: openai_compatible
    options:
      base_url: https://openrouter.ai/api/v1
      model: meta-llama/llama-3.3-70b-instruct
      api_key_env: OPENROUTER_API_KEY
      models:            # optional per-tier models (planner / writer / checker)
        writer: meta-llama/llama-3.3-70b-instruct
```

Keys are read from the environment variable named by `api_key_env`. They are never written to
a config file, `meta.json` or a log.

For local runs, `story` reads a `.env` file from the project root (the folder holding
`config.yaml`) at startup, before config loading. Copy `.env.example` to `.env` and fill in
the key; variables already set in the real environment win. The loader ignores blank lines
and `#` comments, accepts `KEY=value`, quoted values and an optional `export` prefix, and
never prints or writes values — errors name variables only.

`retries` (default 2) retries HTTP 429 and 5xx replies with exponential backoff (`backoff`
1.0s, doubled, capped by `max_backoff`); a `Retry-After` header wins over the computed delay.
When the API reports remaining quota in its headers (`x-ratelimit-*`, `x-quota-*`), the
counts are recorded in the stage `meta.json` and in the failure message.

Each model tier can use its own provider; Gemini, Groq and OpenRouter all speak the
OpenAI-compatible API, so only `base_url`, `model` and `api_key_env` change per tier:

```yaml
adapters:
  llm:
    type: openai_compatible
    options:
      providers:
        planner: {base_url: "https://generativelanguage.googleapis.com/v1beta/openai", model: gemini-2.0-flash, api_key_env: GEMINI_API_KEY}
        writer: {base_url: "https://api.groq.com/openai/v1", model: llama-3.3-70b-versatile, api_key_env: GROQ_API_KEY}
        checker: {base_url: "https://openrouter.ai/api/v1", model: meta-llama/llama-3.1-8b-instruct, api_key_env: OPENROUTER_API_KEY}
```

The shared options (timeout, retries, backoff) are inherited by every tier. `providers` is
only valid for `openai_compatible`; tiers are `planner`, `writer` and `checker`.

### Model call budget

`story run <stage> --max-calls N` (and `story run all --max-calls N`) stops the run before
the N+1th call and fails the stage with a clear reason. The per-day count is kept in
`projects/<slug>/calls.json` (`{"days": {"YYYY-MM-DD": n}}`, pruned to 90 days), updated on
every call and printed after each run, whether it succeeded or not.

Four search adapters exist for stages 2–4:

| type | what it does |
| --- | --- |
| `stub` | returns canned results and records queries; the default, so runs work offline |
| `manual` | writes each query to a file and waits for pasted `Title \| URL \| snippet` lines or JSON |
| `wikipedia` | public MediaWiki JSON API; no key |
| `generic_json` | configurable JSON API (Brave, Tavily, ...) with the key in an env var |

```yaml
adapters:
  search:
    type: wikipedia
    options:
      language: en
```

For a hosted API, set `base_url`, `api_key_env`, `results_path` and `fields`. GET is the
default; Tavily needs `method: POST`, `auth: body`, `api_key_field: api_key`,
`query_param: query`, `max_results_param: max_results` and `results_path: results`.

Search adapters never scrape pages and every result list drops Amazon links. Market numbers
come from the notes you paste into `inputs/market_notes.md`, not from a storefront.

## Publishing note

AI-generated text and images must be disclosed on KDP. The disclosure checklist is produced by
the packaging stage in M8; it is not generated yet.

## Layout

```
pipeline/
  cli.py                  story command
  runner.py               config, projects, stage registry, skills, run/approve
  randomizer.py           seeded rolls, tables, locks, used-name memory, fit check
  schemas.py              character sheet and cast validation, locked-field merge
  ensemble.py             section 8 checks: code first, checker model second
  early_stages.py         deterministic builders for stages 1-7 and market-note parsing
  character_creation.py   deterministic cast draft, model cast parsing, rendering
  ledger.py               rules.json, ledger.json, delta validation, the stage 10 bible
  outline.py              stage 11: chapters, closing actors, validators, rules additions
  scene_card.py           stage 12: goal / conflict / turn cards
  narrator_voice.py       stage 13: voice.md and the banned-phrase table
  chapter_writer.py       stage 14: prose, illustration markers, summaries and ledger gates
  budget.py               per-day call counter and the --max-calls wrapper
  model_json.py           strict JSON replies: extraction, banned phrases, retries, partials
  craft_targets.py        craft_targets.json ranges, sampled with the run seed
  model_notes.py          the optional model-prose layer for stage 13
  adapters/               base, echo, manual, openai_compatible, tiered, stub_search,
                          manual_search, wikipedia, generic_json
  gates/                  ledger_check and linter; rubric and originality come later
skills/                   one Markdown skill per built stage (with YAML frontmatter)
tables/                   starter randomizer tables (JSON; used.json is local memory)
tests/                    one module per acceptance test group
```
