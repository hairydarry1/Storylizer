---
name: outline
stage: 11
model_tier: planner
inputs:
  - concept.yaml (target_words)
  - stages/08-character_creation/cast.json
  - stages/10-series_bible/rules.json
  - outputs of stages 1-10 when they exist
  - craft_targets.json when it exists
outputs:
  - outline.json
  - rules_additions.json
human_gate: true
uses_search: false
uses_randomizer: true
---

## Purpose

Turn the approved cast and the bible into a chapter-by-chapter outline with real numbers:
beats, who acts in each beat, a tension value, a chapter shape, an imagery domain, a
complication every few chapters, and optional illustration slots. The outline is what human
gate 2 approves, so the five code validators below have to pass first.

## Inputs

- `concept.yaml`: `target_words` sets the chapter count, `tone_dial` sets the background threat.
- `stages/08-character_creation/cast.json`: the cast; every secondary debuts once.
- `stages/10-series_bible/rules.json`: the rules the proposed additions must fit.
- `craft_targets.json` when it exists: `chapters.words` is sampled inside its range.
- Earlier stage outputs when they exist; missing stages are notes, never failures.

## Steps

1. Derive the chapter count from `target_words` and the words per chapter: at least 8
   chapters, and at least one chapter per secondary character plus one.
2. Assign one chapter shape per chapter from the randomizer's `chapter_shapes` table, with
   the stage roll fixed as chapter 1. Never use one shape more than twice in a row.
3. Assign an imagery domain per chapter from `imagery_domains`; chapter 1 uses the roll.
4. Give every chapter a tension from 1 to 5 on a curve that both rises and falls.
5. Write 3 to 4 beats per chapter: setup, complication, reversal, resolution, plus a threat
   beat on the even chapters. Every beat names exactly one actor by cast id.
6. Debut one secondary character per chapter, starting at chapter 2, so no two share a first
   appearance.
7. Drop one complication card every third chapter, taken from the `complications` table.
8. Mark an optional illustration slot on chapters with tension 4 or 5.
9. Propose additive rules in `rules_additions.json`: items with sources, one recipe whose
   ingredients exist, locations with travel times, and a skill with prerequisites.
10. Run the five validators. A failed outline is a failed stage, and gate 2 refuses it until
    the outline is fixed or approved with `--force`.
11. Ask the model for prose notes only; the numbers, shapes and actors above are code-owned.

## Output format

`outline.json`:

```json
{
  "title": "...",
  "target_words": 60000,
  "words_per_chapter": 2500,
  "background_threat": "...",
  "act_proportions": [0.25, 0.5, 0.25],
  "craft_targets": {"path": "... or null", "words_per_chapter": 2500},
  "chapters": [
    {
      "number": 1, "title": "...", "act": 1,
      "shape": "a plan, a rehearsal, a first attempt that half works",
      "imagery": "river engineering: sluices, silt, flood marks",
      "tension": 2, "words": 2500, "complication": null,
      "illustration": {"slot": "ch01-scene-1", "status": "optional", "focus": "river engineering"},
      "beats": [
        {"id": "ch01-b1", "kind": "setup", "who_acts": "protagonist", "text": "..."}
      ]
    }
  ]
}
```

`rules_additions.json` uses the `rules.json` shape for `items`, `recipes`, `locations` and
`skills` only. It is merged by `story rules merge`, which never overwrites an existing entry.

## Do not

- Do not let the model set the chapter count, the shapes, the tension values or the actors.
- Do not debut two secondary characters in the same chapter, or leave one out entirely.
- Do not put the background threat in fewer than 40% of chapters.
- Do not make the protagonist a spectator in more than 30% of resolution beats.
- Do not let the tension curve only rise or only fall.
- Do not add a rules entry that overwrites or contradicts `rules.json`.

## Self-check

- Every validator reports `pass` in `meta.json` and in the outline's Validators section.
- Every chapter has a shape from the table, an imagery domain, tension 1-5 and named actors.
- Every secondary appears first in a different chapter, and every chapter's resolution is
  the protagonist's.
- `rules_additions.json` only contains new ids, and every recipe ingredient and exit target
  exists in the merged rules.
- Every missing upstream stage is a note.
