---
name: series_bible
stage: 10
model_tier: planner
inputs:
  - concept.yaml
  - stages/08-character_creation/cast.json
  - outputs of stages 1-9 when they exist
outputs:
  - bible.md
  - rules.json
  - ledger.json
human_gate: false
uses_search: false
uses_randomizer: false
---

## Purpose

Freeze the book's rules before a single chapter is drafted: the world, the progression system
with real numbers, the cast as it stands, and the timeline. The bible is the document every
later stage is checked against, so the code writes the machine-readable half (`rules.json`)
and the initial `ledger.json`, and the model only adds prose.

## Inputs

- `concept.yaml`: genre, tone dial, audience, premise seed, must-include and must-avoid.
- `stages/08-character_creation/cast.json`: the approved cast, one entity per character.
- Earlier stage outputs when they exist: setting research, theme, tone ceiling. Missing
  stages are recorded as notes and treated as empty, never as a failure.

## Steps

1. Set `system_type` to one of `none`, `litrpg`, `magic`, `other`. A story with no stat
   system is valid and must use `none`: the ledger then skips XP, level and skill checks.
2. For any system other than `none`, write the XP curve and the level thresholds as real
   numbers in `rules.json`. Prose may explain the curve; it may not replace it.
3. For every skill, record its unlock condition (`unlocks_at_level`), its prerequisites
   (`requires`, `requires_items`) and what it lets the character do.
4. For every item, record where it can come from: a recipe id (`recipe:<id>`) or a recorded
   event. A recipe lists its ingredients and minutes and may require a skill. An item with
   neither an event source nor a recipe is an item from nowhere and must not exist.
5. Draw the location graph: one node per location with its exits and travel times in
   minutes, plus the start location.
6. Write the timeline from the protagonist's act beats: what has to be true at the end of
   each act, and where the story opens.
7. Seed `ledger.json` from the cast: one entity per character, at the start location, with an
   empty inventory and no applied deltas. Never discard a ledger that already has chapters or
   applied deltas; keep it and say so.
8. Ask the model only for prose about the world, the system and the timeline. The rules
   fixed by code win over anything the model says.

## Output format

`bible.md` (also written as the stage's `output.md`) has these sections:

```
# Series bible - <title>

## World rules
## System and progression
## Cast
## Locations and travel
## Timeline
## Notes
```

`rules.json` is the machine-readable half:

```json
{
  "system_type": "litrpg",
  "xp": {"curve": "triangular", "per_level": 100, "max_level": 5,
         "thresholds": {"1": 0, "2": 100, "3": 300}},
  "skills": {"ledger-sight": {"unlocks_at_level": 2, "requires": [],
                              "requires_items": []}},
  "items": {"ledger": {"sources": []},
            "sealed-ledger": {"sources": ["recipe:seal-the-ledger"]}},
  "recipes": [{"id": "seal-the-ledger", "produces": "sealed-ledger",
               "ingredients": {"ledger": 1, "wax-seal": 1},
               "requires_skill": null, "minutes": 30}],
  "locations": {"record-office": {"name": "The record office",
                                  "exits": {"market": {"minutes": 10}}}},
  "start_location": "record-office"
}
```

`ledger.json` starts as `{ "chapter": 0, "entities": {...}, "events": [],
"applied_deltas": [] }`.

## Do not

- Do not let the model invent stats, thresholds, skills, items or travel times that are not
  in `rules.json`; those numbers are code-owned.
- Do not write a stat system for a story that has none: use `system_type: none`.
- Do not give an item a source it cannot earn (a recorded event or a craftable recipe).
- Do not overwrite a ledger that already has chapters, events or applied deltas.
- Do not reproduce text from any comparable book.

## Self-check

- Every section of `bible.md` is present and names real cast ids and location ids.
- `system_type` is one of the four allowed values, and a non-`none` system has thresholds.
- Every skill's `requires` entries exist; every recipe's ingredients and product exist.
- Every exit points at a location in the graph, and the start location is in the graph.
- `ledger.json` has exactly one entity per character in `cast.json`, at the start location.
- Every missing upstream stage appears in `meta.json` notes.
