---
name: outline
stage: 11
model_tier: planner
inputs:
  - concept.yaml (target_words, tone_dial)
  - stages/08-character_creation/cast.json
  - stages/10-series_bible/rules.json
  - stages/05-premise_inversion and 06-theme_premise when they exist
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

Turn the approved cast and the bible into a chapter-by-chapter outline. Code and the
randomizer own the constraints; the planner model writes each chapter's title, hook, beats
and ending inside them. The outline is what human gate 2 approves, so the five code
validators below have to pass first.

## Inputs

- `concept.yaml`: `target_words` sets the chapter count, `tone_dial` sets the background threat.
- `stages/08-character_creation/cast.json`: the cast, with each secondary's debut chapter.
- `stages/10-series_bible/rules.json`: the rules the proposed additions must fit.
- `stages/05-premise_inversion` and `06-theme_premise`: the theme and premise the chapters serve.
- `craft_targets.json` when it exists: `chapters.words` is sampled inside its range.
- Earlier stage outputs when they exist; missing stages are notes, never failures.

## Steps

1. Derive the chapter count from `target_words` and the words per chapter: at least 8
   chapters, and at least one chapter per secondary character plus one.
2. Assign the code-owned constraints per chapter: one shape from the randomizer's
   `chapter_shapes` (chapter 1 uses the roll, never three in a row), an imagery domain from
   `imagery_domains`, a tension from 1 to 5 on a curve that rises and falls, the actor whose
   debut the chapter carries, a complication card every third chapter, the threat schedule
   and an optional illustration slot at tension 4 or 5.
3. For each chapter in order, call the planner with the concept, theme and premise, cast
   sheets, rules summary, that chapter's constraints and summaries of the chapters before it.
   Allowed actors are the protagonist and the secondaries whose debut has arrived.
4. Require one JSON object: `title`, `hook`, `beats` of
   `{actor, action, obstacle, outcome}`, and `ends_on`.
5. Validate it: the schema, real cast ids, one actor per beat, at least three beats, no empty
   text, the closing beat acted by the protagonist, no banned phrase, and no beat text that
   repeats or nearly repeats a beat from an earlier chapter.
6. Retry up to three times, feeding the validation errors back. A chapter that is still
   invalid fails the stage with the details; there is no template fallback.
7. Run the five validators over the assembled outline. A failed outline is a failed stage,
   and gate 2 refuses it until the outline is fixed or approved with `--force`.
8. Propose additive rules in `rules_additions.json`: items with sources, one recipe whose
   ingredients exist, locations with travel times, and a skill with prerequisites.
9. `--skeleton` builds the deterministic skeleton instead, for tests and dry runs only. A real
   run never uses it and never mixes skeleton chapters into an authored outline.

## Output format

`outline.json`, one entry per chapter:

```json
{
  "title": "The Sealed Ledger",
  "target_words": 60000,
  "words_per_chapter": 2500,
  "background_threat": "the pressure of a debt called in",
  "act_proportions": [0.25, 0.5, 0.25],
  "craft_targets": {"path": "... or null", "words_per_chapter": 2500, "sampled": false},
  "chapters": [
    {
      "number": 1, "title": "...", "hook": "...", "ends_on": "...", "act": 1,
      "shape": "a plan, a rehearsal, a first attempt that half works",
      "imagery": "river engineering: sluices, silt, flood marks",
      "tension": 2, "words": 2500, "complication": null,
      "illustration": {"slot": "ch01-scene-1", "status": "optional", "focus": "river engineering"},
      "threat": false, "actor": "mara",
      "beats": [
        {"id": "ch01-b1", "kind": "setup", "actor": "mara", "action": "...",
         "obstacle": "...", "outcome": "..."}
      ]
    }
  ]
}
```

`meta.json` records `model.mode` (model or skeleton), the model call count, the largest
attempt count and, on failure, `failed_chapter`. `rules_additions.json` uses the
`rules.json` shape for `items`, `recipes`, `locations` and `skills` only.

## Do not

- Do not let the model set the chapter count, the shapes, the tension values or the debut schedule.
- Do not accept a reply that is not one JSON object with exactly the required keys.
- Do not fall back to template beats when the model fails; fail the stage and say why.
- Do not debut two secondary characters in the same chapter, or leave one out entirely.
- Do not put the background threat in fewer than 40% of chapters.
- Do not make the protagonist a spectator in more than 30% of resolution beats.
- Do not let the tension curve only rise or only fall.
- Do not add a rules entry that overwrites or contradicts `rules.json`.

## Self-check

- Every validator reports `pass` in `meta.json` and in the outline's Validators section.
- Every chapter has a shape from the table, an imagery domain, tension 1-5, a hook, an
  ending and beats that name exactly one cast id each.
- Every secondary appears first in a different chapter, and every chapter closes on the
  protagonist.
- No beat repeats an earlier chapter's beat, and no banned phrase appears.
- A failed model reply leaves no `outline.json` and no `rules_additions.json` behind.
- `rules_additions.json` only contains new ids, and every recipe ingredient and exit target
  exists in the merged rules.
- Every missing upstream stage is a note.
