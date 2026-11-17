---
name: narrator_voice
stage: 13
model_tier: planner
inputs:
  - concept.yaml
  - craft_targets.json when it exists (sentence and paragraph targets)
  - outputs of earlier stages when they exist
outputs:
  - voice.md
  - tables/banned_phrases.json (starter table when missing)
human_gate: false
uses_search: false
uses_randomizer: false
---

## Purpose

Fix how the book sounds before a chapter is drafted: POV and tense, sentence and paragraph
targets, a dialogue subtext guide, and the banned-phrase list the writer and linter obey.

## Inputs

- `concept.yaml`: genre, audience and tone, which colour the prose notes.
- `craft_targets.json` when it exists: `sentences.words`, `paragraphs.sentences`,
  `dialogue_ratio`, `pov` and `tense` are sampled inside their ranges.
- `tables/banned_phrases.json`: the phrases this book never uses.

## Steps

1. Set POV and tense from `craft_targets.json` when present; otherwise use third person
   limited and past tense and say so.
2. Set the mean sentence length and the sentences per paragraph from the targets, or 14
   words and 3 sentences from the defaults.
3. Write the dialogue subtext guide: every line has an unspoken goal, emotion arrives as
   sensation rather than a named feeling, and characters answer the question they wish they
   had been asked.
4. Read `tables/banned_phrases.json`. When it is missing, write the starter table (overused
   AI phrases such as "a testament to", "tapestry of", "couldn't help but" and "little did
   she know") and record that you created it. Never overwrite an existing table.
5. Ask the model for prose about the narrator's sound only. POV, tense and the targets are
   fixed by the numbers above.

## Output format

`voice.md` (also written as the stage's `output.md`):

```
# Narrator voice - <title>

## POV and tense
- pov: ...
- tense: ...

## Sentence targets
- mean sentence: 14 words

## Paragraph targets
- sentences per paragraph: 3

## Dialogue
- dialogue share of the page: 30%

## Dialogue subtext guide
- ...

## Banned phrases
- "a testament to"
```

`meta.json` records `pov`, `tense`, `sentence_words`, `paragraph_sentences`,
`dialogue_ratio`, the number of banned phrases and the craft-target path.

## Do not

- Do not overwrite an existing `tables/banned_phrases.json`.
- Do not name a feeling in a dialogue tag when a sensation or an action will do.
- Do not change the POV or tense from the targets without recording the assumption.
- Do not set targets outside the craft-target ranges.
- Do not invent banned phrases the table does not contain.

## Self-check

- POV, tense, sentence and paragraph targets are present and recorded in `meta.json`.
- The dialogue subtext guide is concrete enough to check a page against.
- The banned list is read from the table, and a missing table is created and noted.
- Sentence and paragraph targets trace to `craft_targets.json` when it exists.
