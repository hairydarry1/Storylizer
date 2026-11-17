---
name: scene_card
stage: 12
model_tier: planner
inputs:
  - stages/11-outline/outline.json
  - craft_targets.json when it exists
outputs:
  - cards.json
human_gate: false
uses_search: false
uses_randomizer: false
---

## Purpose

Break every approved chapter into scenes that can be drafted. The planner writes a goal, a
conflict and a turn for each scene, inside the chapter's code-owned shape, imagery, beats and
scene count. The writer never starts a scene without knowing what changes in it.

## Inputs

- `stages/11-outline/outline.json`: the approved chapter order, titles, beats, shapes and imagery.
- `craft_targets.json` when it exists: `chapters.scenes` sets the scene count inside a
  [min, max] range; the default is three scenes per chapter.

## Steps

1. Read the outline. If it does not exist, tell the user to run `story run outline` first.
2. Take the scene count for each chapter from `craft_targets.json` when present, clamped to
   2-4; otherwise use three.
3. For each chapter, call the planner with the chapter's title, shape, imagery, complication,
   beats and scene count.
4. Require one JSON object holding exactly that many scenes, each with a non-empty `goal`, a
   `conflict` and a `turn` that changes something.
5. Validate the schema, the scene count, non-empty text, a turn that does not restate the
   goal, no banned phrase, and no scene text that repeats an earlier scene.
6. Retry up to three times, feeding the validation errors back. A chapter that is still
   invalid fails the stage with the details; there is no fallback to derived cards.
7. `--skeleton` builds the deterministic cards instead, for tests and dry runs only.

## Output format

`cards.json`:

```json
{
  "chapters": [
    {
      "number": 1,
      "title": "...",
      "scenes": [
        {"number": 1, "goal": "...", "conflict": "...", "turn": "..."}
      ]
    }
  ]
}
```

`output.md` renders one `## Chapter N` section per chapter and one `### Scene N` per scene.
`meta.json` records `model.mode`, the call count and, on failure, `failed_chapter`.

## Do not

- Do not add a scene that is not in the outline's chapter.
- Do not leave a scene without a goal, a conflict or a turn.
- Do not restate the goal as the turn; the turn must change something.
- Do not accept the wrong number of scenes.
- Do not fall back to derived cards when the model fails; fail the stage and say why.

## Self-check

- One card per outline chapter, in order, with 2-4 scenes each.
- Every scene has non-empty goal, conflict and turn.
- Goal and turn differ in every scene.
- The scene count matches `craft_targets.json` when the file is present.
- A failed reply leaves no `cards.json` behind.
