---
name: tone_ceiling
stage: 7
model_tier: planner
inputs:
  - concept.yaml (tone_dial)
  - outputs of stages 1-6 when they exist
outputs:
  - output.md
human_gate: false
uses_search: false
uses_randomizer: false
---

## Purpose

Turn `tone_dial` into a ceiling the whole book must respect: what can happen on the page,
what stays off it, and how much comfort the reader is promised. The ceiling is a limit, not
a target; a scene may be quieter than the ceiling but never louder.

## Inputs

- `concept.yaml`: `tone_dial` (0 cozy, 1 warm, 2 tense, 3 action-comedy), genre, audience,
  must-avoid.
- Earlier stage outputs when they exist: intake constraints, setting world rules, theme.
  Missing stages get a note.

## Steps

1. Read the tone dial. If it is missing, use 1 (warm) and record the assumption.
2. Set the ceiling from the dial:
   - 0 cozy: violence off-page, one social setback per chapter, the community can absorb
     the conflict, nothing irreversible happens to a likable character.
   - 1 warm: danger on-page but recoverable, one real loss allowed, the ending is earned
     rather than guaranteed.
   - 2 tense: on-page danger, a cost that does not heal, at least one irreversible choice,
     comfort is scarce but present.
   - 3 action-comedy: comic violence, high energy, no lingering trauma on the page, the
     stakes are real even when the tone is loud.
3. State the off-the-table list: what this book will never depict, drawn from the dial and
   the must-avoid list.
4. Set a per-chapter budget for setbacks and recoveries, so the middle cannot become one
   long emergency.
5. Check the theme and premise against the ceiling: if the story requires something the
   ceiling forbids, say so here instead of quietly breaking it later.
6. Ask the model for a tonal note only; the ceiling table is deterministic and wins.

## Output format

`output.md` contains a machine-readable section that stage 8 reads:

```
# Tone ceiling - <title or slug>

## Dial
- tone_dial: 2 (tense)

## Conflict ceiling
- conflict ceiling: <one sentence the whole book must obey>

## What can happen on the page
- ...

## Per chapter
- setbacks: ...
- recoveries: ...

## Off the table
- ...

## Notes
- <assumptions, conflicts with the theme, missing stages>
```

`meta.json` records `tone_dial`, the `ceiling` sentence, the label and the per-chapter
budget. The exact `- conflict ceiling:` line is what stage 8 extracts.

## Do not

- Do not raise the ceiling in an intense scene; cut away instead.
- Do not treat cozy as no conflict or action-comedy as no stakes.
- Do not depict anything on the must-avoid list.
- Do not let a model reply override the dial table.
- Do not leave the tone dial unstated when it was assumed.

## Self-check

- The dial number and label agree.
- The ceiling sentence names a limit and what happens at it.
- The off-the-table list is concrete enough to check a scene against.
- Per-chapter setbacks and recoveries are both present.
- The assumption is recorded when the dial was missing.
