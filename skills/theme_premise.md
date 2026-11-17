---
name: theme_premise
stage: 6
model_tier: planner
inputs:
  - concept.yaml
  - stages/01-intake/ and stages/05-premise_inversion/ when they exist
outputs:
  - output.md
human_gate: false
uses_search: false
uses_randomizer: false
---

## Purpose

State what the book is actually about, in words a reader could argue with. The theme is a
question the story tests, not a lesson it announces. This stage turns the concept and the
inverted premise into a central question, a pressure, and an emotional arc.

## Inputs

- `concept.yaml`: genre, premise seed, tone dial, audience.
- The intake brief and the premise inversion when they exist. Prefer the inverted premise
  over the raw premise seed. Missing stages get a note.
- No search and no randomizer.

## Steps

1. Take the one-line premise from stage 5, or the premise seed when stage 5 is missing.
   Name the want, the obstacle and the cost in one sentence.
2. Write the central question as a question the protagonist cannot answer without changing.
   It must be answerable in more than one defensible way.
3. Name the pressure: the person, institution or belief that makes the question expensive
   to answer. "Society" is too vague; name who would be hurt.
4. Map the emotional arc by act, from the starting state to the final state. The tone dial
   sets the register, not the answer: cozy does not mean low stakes.
5. Write the question under the comfort: the thing the genre's readers are really buying.
   Keep it specific to this premise.
6. Reject a theme that is a slogan ("love conquers all") or a topic ("grief"). Rewrite it
   until it has a counter-argument inside it.
7. Ask the model for a draft exploration; keep the deterministic question and arc even when
   the model reply is unusable.

## Output format

`output.md` contains:

```
# Theme and premise - <title or slug>

## Premise
<one sentence: want, obstacle, cost>

## Central question
<the question>

## Pressure
<who or what makes it expensive>

## Emotional arc
- Act 1: ...
- Act 2: ...
- Act 3: ...

## The question under the comfort
<why this genre's reader keeps reading>

## Draft exploration
<model prose or an unusable-reply note>
```

`meta.json` records the `central_question`, `premise`, `pressure` and tone dial. Stage 8
reads the central question from here.

## Do not

- Do not state a moral the book will prove.
- Do not use a topic as the theme.
- Do not contradict the tone ceiling or the must-avoid list.
- Do not replace the deterministic central question with model prose.
- Do not assume the premise inversion exists; note when it does not.

## Self-check

- The central question has at least two defensible answers.
- The pressure names someone specific who pays.
- The emotional arc changes the protagonist, not just the situation.
- The premise names a want, an obstacle and a cost.
- The central question is one sentence.
