---
name: intake
stage: 1
model_tier: planner
inputs:
  - concept.yaml
outputs:
  - output.md
human_gate: false
uses_search: false
uses_randomizer: false
---

## Purpose

Turn `concept.yaml` into a brief a writer can start from. This stage fills the gaps a
one-line premise leaves open and says plainly what is still missing; it does not invent a
plot or a cast.

## Inputs

- `concept.yaml`: title, genre, audience, tone dial, target length, pen name, premise seed,
  must-include and must-avoid.
- Nothing upstream: this is the first stage.

## Steps

1. Read `concept.yaml` and list every empty field. An empty field is a question for the
   writer, not permission to guess. Put it under `## Open questions` and in `meta.json`.
2. Restate the premise in one sentence: who wants what, what stands in the way, and what it
   costs to fail. Keep the user's premise seed as the source; do not add a twist here.
3. Fix the terms for later stages: genre (the shelf, not a mood), audience, target length,
   tone dial with its label (0 cozy, 1 warm, 2 tense, 3 action-comedy).
4. Turn must-include and must-avoid into concrete constraints a scene can be checked
   against. "No graphic violence" is usable; "dark but not too dark" is not.
5. Ask the model for a short brief only after the deterministic sections exist. If the
   model reply is empty or unusable, keep the deterministic sections and add a note.
6. Keep the output stable: rerunning on the same concept should produce the same file apart
   from a model rewrite of the brief.

## Output format

`output.md` contains:

```
# Intake brief - <title or slug>

## Concept
- genre: ...
- audience: ...
- tone dial: 1 (warm)
- target length: 60,000 words
- pen name: ...

## Premise
<one sentence, or "Not filled in yet">

## Constraints
- Must include: ...
- Must avoid: ...

## Brief
<model prose, or a note that the model reply was unusable>

## Open questions
- <empty field and what it needs>
```

`meta.json` records `open_questions`, the concept fields that were present, and the model
note when there was one.

## Do not

- Do not invent genre, audience, tone or length when `concept.yaml` is silent.
- Do not add characters, chapters or a plot outline; those belong to later stages.
- Do not treat a missing premise seed as a premise.
- Do not hide an empty field by filling it with a plausible default.
- Do not change the user's must-include or must-avoid wording into a softer version.

## Self-check

- Every empty concept field appears in `## Open questions`.
- The premise is one sentence and matches `premise_seed`.
- The tone dial has both a number and its label.
- A model failure leaves a note, not a failed stage.
- Rerunning does not change the deterministic sections.
