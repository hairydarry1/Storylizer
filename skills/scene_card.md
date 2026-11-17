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

Break every approved chapter into scenes that can be drafted. Each scene carries a goal, a
conflict and a turn, so the writer never starts a scene without knowing what changes in it.

## Inputs

- `stages/11-outline/outline.json`: the approved chapter order, beats, shapes and imagery.
- `craft_targets.json` when it exists: `chapters.scenes` sets the scene count inside a
  [min, max] range; the default is three scenes per chapter.

## Steps

1. Read the outline. If it does not exist, tell the user to run `story run outline` first.
2. Take the scene count for each chapter from `craft_targets.json` when present, clamped to
   2-4; otherwise use three.
3. Give the first scene the chapter's opening beat as its goal, and the chapter's
   complication card as its conflict when one exists.
4. Let each scene's turn be the next beat: something is learned, lost or paid for.
5. Keep the goal and the turn different; a scene whose turn restates its goal has no scene.
6. Ask the model for prose notes only; goals, conflicts and turns are fixed here.

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

## Do not

- Do not add a scene that is not in the outline's chapter.
- Do not leave a scene without a goal, a conflict or a turn.
- Do not make the protagonist a passenger in her own scene.
- Do not restate the outline beat as the turn; the turn must change something.

## Self-check

- One card per outline chapter, in order, with 2-4 scenes each.
- Every scene has non-empty goal, conflict and turn.
- Goal and turn differ in every scene.
- The scene count matches `craft_targets.json` when the file is present.
