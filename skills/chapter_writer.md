---
name: chapter_writer
stage: 14
model_tier: writer
inputs:
  - stages/11-outline/outline.json
  - stages/12-scene_card/cards.json
  - stages/13-narrator_voice/voice.md
  - stages/10-series_bible/bible.md
  - stages/10-series_bible/rules.json
  - ledger.json
  - summaries.json when it exists
  - craft_targets.json when it exists
outputs:
  - chapters/chNN.md
  - summaries.json
  - reports/chapter-chNN.json
human_gate: false
uses_search: false
uses_randomizer: false
---

## Purpose

Draft one chapter at a time, inside the approved outline, then hand the finished chapter to a
checker that returns a summary and a ledger delta. Code owns every gate: the linter, the word
count, the illustration marker and the ledger rules decide whether the delta is applied. The
protagonist solves her own problems; the prose shows rather than tells, dialogue carries
subtext, and the narrator never lectures or addresses the reader.

## Inputs

- `stages/11-outline/outline.json`: the chapter's title, hook, shape, imagery, tension, word
  target, beats, closing actor and optional illustration slot.
- `stages/12-scene_card/cards.json`: the chapter's scenes, each with goal, conflict and turn.
- `stages/13-narrator_voice/voice.md`: POV, tense, sentence and dialogue targets, subtext guide
  and banned phrases.
- `stages/10-series_bible/bible.md` and `rules.json`: the world, progression and location rules.
- `ledger.json`: the current story state; it is the state the chapter must leave consistent.
- `summaries.json`: accepted chapter summaries; the writer sees the last two.
- `craft_targets.json` when it exists: word count, mean sentence length and dialogue ratio.

## Steps

1. Start from the first chapter not already accepted in `summaries.json`. `--chapter N` drafts
   only that chapter; `--from N` starts at N; without either, run the whole book.
2. Call the writer tier with the chapter constraints, scene cards, bible and rules summaries,
   voice guide, ledger snapshot, previous two summaries, sampled craft targets, the chapter's
   shape and imagery, and the writing rules. Ask for prose only.
3. Put the prose in `chapters/chNN.md`. Where the outline has an illustration slot, insert
   `[[ILLUSTRATION: chNN-sK | short description]]` at the matching scene. No other marker.
4. Gate the prose before spending a checker call: run the linter on it, require the marker, and
   require the word count to be within 20% of the chapter's target.
5. Call the checker tier with the finished chapter, the current ledger and the rules. Require
   strict JSON with exactly `summary` and `delta`; the delta's chapter must match and its
   `ops` must be non-empty and earned. Retry up to three times, feeding every error back.
6. Run `ledger.validate_delta` again. Only when it passes, apply the delta, save `ledger.json`,
   and save the summary in `summaries.json`.
7. A chapter that fails any gate is marked `needs_revision`, its report is written to
   `reports/chapter-chNN.json`, its prose stays on disk for revision, and the ledger and
   summaries are untouched. Stop the run there so later chapters do not start from stale state.
8. On a rerun, skip every chapter with an accepted summary and continue at the first one that
   needs revision.

## Output format

`chapters/chNN.md` contains prose only. An illustrated chapter also contains its marker:

```text
[[ILLUSTRATION: ch01-s1 | the river at dusk]]
```

`summaries.json` holds the accepted summaries in chapter order:

```json
{
  "chapters": [
    {"number": 1, "summary": "...", "chapter": "chapters/ch01.md",
     "words": 2500, "target_words": 2500, "delta": "auto-...", "accepted_at": "..."}
  ]
}
```

The checker's strict JSON is:

```json
{
  "summary": "two to four concrete sentences",
  "delta": {
    "chapter": 1,
    "ops": [{"op": "event", "id": "ch01-e1", "summary": "what changed"}]
  }
}
```

`reports/chapter-chNN.json` records the linter report, the word count and target, the checker
attempts, the delta, the ledger check and, on failure, the errors. `meta.json` records the
scope, per-chapter status (`accepted` or `needs_revision`), writer/checker calls and resumes.

## Do not

- Do not apply a delta before the linter, word count and ledger checks all pass.
- Do not touch the ledger or `summaries.json` for a chapter that needs revision.
- Do not let the checker invent entities, items, locations or events that the chapter did not
  earn.
- Do not accept a summary without a delta, or a delta for another chapter.
- Do not add or move an illustration marker the outline did not assign.
- Do not write a title, heading, note or meta commentary into the chapter file.
- Do not recap the previous chapters at the start of the prose.
- Do not fall back to template prose when the model fails; flag the chapter and stop.

## Self-check

- `chapters/chNN.md` is prose only and contains the assigned illustration marker exactly once.
- The prose's word count is within 20% of the chapter's target.
- The linter passes: no banned phrases, repeated phrases, overused words, uniform sentence
  length, tic words or repeated paragraph openers.
- The checker returned strict JSON after at most three attempts.
- `ledger.validate_delta` passed before `ledger.json` changed.
- The summary in `summaries.json` belongs to the accepted chapter and matches its report.
- A failed chapter has `needs_revision` in `meta.json` and a report, and the ledger is unchanged.
- A rerun makes no call for an accepted chapter and resumes at the first unfinished one.
