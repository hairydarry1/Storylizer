---
name: premise_inversion
stage: 5
model_tier: planner
inputs:
  - concept.yaml
  - stages/02-market_research/ output and meta when they exist
  - outputs of stages 1-4 when they exist
outputs:
  - output.md
human_gate: false
uses_search: false
uses_randomizer: false
---

## Purpose

Find the version of this story that is not already on the shelf. First write down what the
genre reliably delivers, then choose which expectations to flip, then check those flips
against the comparables from market research. A flip is only useful if it changes the plot,
not just the decoration.

## Inputs

- `concept.yaml`: genre, premise seed, audience, tone dial.
- `stages/02-market_research/output.md` and `meta.json`: the comparables and the gap sheet.
  If stage 2 has not run, say the comparison is pending and continue.
- Earlier stage outputs when they exist: intake constraints, reference set pieces and
  setting rules. Missing stages are notes, not blanks to fill with guesses.

## Steps

1. Name the genre's expectations as a short list of promises: the crime is solved, the
   lovers end together, the chosen one saves the world, the detective is sober by the end.
   Use the reference set-piece list when stage 3 exists.
2. For each expectation, propose a move: invert it, complicate it, delay it, or keep it.
   An inversion must be stated as a concrete change to who wants what or what it costs.
3. Choose two or three moves to flip. Do not flip everything; a genre with no promises
   left is a different genre and the audience cannot find it.
4. Write the one-line premise that results from the chosen flips. It must name a want, an
   obstacle and a cost.
5. Compare against market research. List the comparables and check each flip against them:
   is a comparable already built on this flip? The code can only show the recorded titles
   and gaps; say plainly that similarity judgment is human work until the originality gate.
6. Ask the model for alternative flips, then keep the deterministic table as the record.

## Output format

`output.md` contains:

```
# Premise inversion - <title or slug>

## What the genre expects
- <promise>

## What we flip
- **<expectation>** -> <flip: who wants what changes, and the cost>
- **<expectation>** - keep: <why keeping it is the braver choice>

## One-line premise
<want, obstacle, cost>

## Market comparison
- comparables: <titles from stage 2>
- check: <flip> - not one of the recorded comparables (human check still required)
- gaps from stage 2: <what's missing>

## Draft alternatives
<model prose or an unusable-reply note>
```

`meta.json` records `expectations`, the chosen flips and keeps, the one-line premise, and
`market_comparison` (`found`, source and comparables).

## Do not

- Do not flip a genre promise without saying what replaces it.
- Do not claim a flip is original because the search returned nothing.
- Do not invent comparables that stage 2 did not record.
- Do not write the whole plot here; this is a premise, not an outline.
- Do not let the model's alternatives overwrite the chosen flips.

## Self-check

- The expectation list is genre-level and precedes the flips.
- Every flip names a concrete change and a cost.
- Two or three flips are chosen, not all of them.
- The market comparison names every recorded comparable or says stage 2 is pending.
- The one-line premise could be rejected on its own merits.
