---
name: character_creation
stage: 8
model_tier: planner
inputs:
  - concept.yaml
  - stage 8 randomizer rolls (names, quirk, flaw, talent, extras)
  - outputs of stages 1-7 when they exist
outputs:
  - cast.json
  - output.md
human_gate: false
uses_search: false
uses_randomizer: true
---

## Purpose

Build the cast that carries the book: one protagonist and enough secondary characters that
every scene has someone with a competing want. The randomizer supplies names and constraints
first; this skill turns them into people, not a list of quirks.

## Inputs

- `concept.yaml`: genre, tone, audience, premise seed, must-include and must-avoid.
- The stage 8 rolls: protagonist given and family name, quirk, flaw, talent, plus whatever
  extras `chaos_dial` added (blind spot, physical mark, emotional start, speech tic,
  complication, setting custom). These are constraints, not suggestions.
- Any upstream stage output that exists. Missing stages are passed in as empty with a note;
  work from the concept instead of inventing research.

## Steps

1. Assign roles first: `protagonist`, and secondary roles from `foil`, `mentor`, `ally`,
   `pressure`, `comic`, `wildcard`. Do not give two characters the same role.
2. Build the protagonist around the rolled quirk, flaw and talent. The flaw has to cost
   something in the plot; it is not a decorative weakness.
3. Give every secondary character its own `want` and its own `stakes` in `emotional_core`.
   A secondary character who exists only to help or obstruct the protagonist is not finished.
4. Vary age, gender and temperament across the cast. Two characters may share a temperament
   only if their voices differ in rhythm and vocabulary.
5. Make every voice distinct: rhythm, vocabulary, at least one tic that no other character
   has, and things this character would never say.
6. Connect the cast with `relationships` that name an existing character `id`. Each
   relationship needs a bond and a friction; "friendly" alone is not a relationship.
7. Respect `locked`: a field named in a character's `locked` list may not change when a
   character is regenerated. Keep the character `id` stable across regenerations.
8. Never write a numeric IQ, an IQ score, or a numeric intelligence field. Intelligence is
   described only in `intelligence_profile.sharp_at`, `.blind_at` and `.overconfident_about`.
9. Produce the machine-readable cast as JSON in a fenced ```json block. The pipeline
   validates it; an invalid cast is rejected rather than silently patched.

## Output format

`cast.json` holds `{"characters": [...]}`. Each character follows section 4 of
`BUILD_SPEC.md`:

```
id, name, role, gender, age, occupation, background
look: {build, hair, skin, signature_clothing, marks: [{what, meaning, placement}]}
physical_differences: [{what, how_it_shapes_behavior}]
intelligence_profile: {sharp_at: [], blind_at: [], overconfident_about: []}
emotional_core: {want, need, wound, false_belief, fear, coping_habit, start_state,
                 arc_by_act: [], laughs_at, cries_at, stakes}
voice: {rhythm, vocabulary, tics: [], never_says: []}
relationships: [{to, bond, friction}]
locked: []
flaw, quirk, talent, tags: []
```

`stakes` is required for every character whose role is not `protagonist`. `output.md`
summarises the cast in prose for a human reader.

## Do not

- Do not use a banned name or a default AI plot beat.
- Do not give the cast one age, one gender or one voice rhythm.
- Do not tag more than a third of the cast "quirky and clever".
- Do not store an IQ number anywhere, including inside `look` or a free-text field.
- Do not reference a character id that is not in the cast.
- Do not change a locked field or a character id during regeneration.

## Self-check

- Every secondary character has a `want` and a `stakes` that could conflict with someone.
- Every `relationships[].to` matches an id in the cast; ids are unique.
- No two characters share a voice tic; rhythms and vocabularies differ.
- Ages, genders and temperaments vary.
- No IQ field exists at any depth.
- The JSON parses and the pipeline's schema validation passes.
