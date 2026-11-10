---
name: ensemble_check
stage: 9
model_tier: checker
inputs:
  - cast.json from stage 8
  - concept.yaml
  - outputs of stages 1-8 when they exist
outputs:
  - output.md
human_gate: true
uses_search: false
uses_randomizer: false
---

## Purpose

Decide whether the cast can carry a novel, or whether it needs another pass before the
concept and cast are approved. This is human gate 1: the run stops here until a person
approves it.

## Inputs

- `cast.json` from `stages/08-character_creation/`. A missing or invalid cast stops the
  check; run character creation first.
- `concept.yaml`: genre, tone, audience, premise seed.
- Earlier stage outputs when they exist. Missing stages are treated as empty with a note.

## Steps

1. Run the deterministic checks in code first:
   - more than one character shares an age, a gender or a voice rhythm;
   - two characters use the same voice tic;
   - more than a third of the cast is tagged "quirky and clever".
2. Send the judgment checks to the checker tier, with the cast's wants, stakes, flaws, false
   beliefs and coping habits:
   - do two characters have wants that cannot both be satisfied?
   - does any character's flaw exist only so the protagonist can fix it?
   - is any portrayal stereotyped rather than specific?
3. Treat a checker reply that is not usable JSON as a skipped judgment check with a note,
   never as a silent pass. Code findings still stand.
4. Rank findings: a conflicting want or a stereotype blocks the gate; a shared tic is a
   rewrite. Name the character ids involved.
5. Write the report and stop at the human gate. A human approves the concept and cast, or
   sends the cast back for regeneration.

## Output format

`output.md` contains:

```
## Ensemble check
status: passed | flagged
### Code checks
- <code>: <detail> (characters: ...)
### Judgment checks
- <code>: <detail> (characters: ...)
### Notes
- <skipped checks or missing upstream stages>
```

The stage's `meta.json` records `status: failed` when anything is flagged, with the codes in
`error`; otherwise `status: done` and the stage waits for approval (`approved: false`).

## Do not

- Do not edit the cast here; report and stop.
- Do not pass a cast with a conflicting want or a stereotype.
- Do not count variety findings twice: the code checks own age, gender, temperament and tics.
- Do not approve the gate from this skill; only a person runs `story approve 1`.
- Do not invent character ids that are not in the cast.

## Self-check

- Every finding names at least one character id from the cast.
- Judgment findings use the checker tier and carry a one-line reason.
- An unusable checker reply appears in the report as a note.
- A flagged cast leaves the stage failed, not silently done.
- A human gate is never passed automatically.
