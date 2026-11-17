---
name: setting_research
stage: 4
model_tier: writer
inputs:
  - concept.yaml
  - outputs of earlier stages when they exist
  - search results from the configured search adapter
outputs:
  - output.md
human_gate: false
uses_search: true
uses_randomizer: false
---

## Purpose

Make the setting specific enough to write scenes in: the details of ordinary life, the
words people use, what the place looks and smells like, and the mistakes an outsider would
make. Research depth is set by the concept's genre and must-avoid list.

## Inputs

- `concept.yaml`: genre, premise seed, setting details if present, must-include and
  must-avoid.
- Earlier stage outputs when they exist. A tone ceiling from stage 7 will not exist yet;
  use the tone dial from intake.
- Search results from `adapters.search` for place, period and occupation details.

## Steps

1. Decide the setting kind from the concept: real place and period, invented place in a
   real period, or secondary world. If the concept does not say, record the question and
   choose the least specific option.
2. Search for daily-life material: work, food, transport, money, weather, housing, and who
   holds power. Prefer museums, archives, encyclopedias and interviews.
3. For a real period, list the vocabulary that belongs and the words that would be
   anachronisms. For a secondary world, list the rules the world must keep and the costs
   those rules impose.
4. Build a sensory palette: five sights, five sounds, five smells or textures, and the one
   detail a local would notice first.
5. List common mistakes: the anachronism, the stereotype, the geography error, the job
   detail that only exists in films.
6. Name three locations that can carry scenes, each with a social rule and a physical
   constraint.
7. Ask the model to fill gaps and connect details. Mark invented details as invented and
   keep them consistent with the world rules.

## Output format

`output.md` contains:

```
# Setting research - <title or slug>

## Setting kind
- <real place/period | invented place | secondary world>

## Daily life
- work, money, food, transport, housing, power

## Vocabulary
- period words: ...
- anachronisms to avoid: ...

## Sensory palette
- sight, sound, smell, texture, the local detail

## Locations for scenes
- **Name** - social rule, physical constraint

## Common mistakes
- <mistake and the correction>

## Notes
- <missing concept fields, invented details, sources>
```

`meta.json` records the setting kind, queries, result count and which details are invented.

## Do not

- Do not turn the setting into a history lecture; every detail must be usable in a scene.
- Do not mix periods or technologies without saying so in the world rules.
- Do not use a stereotype as local colour.
- Do not scrape; use only the configured search API's snippets and links.
- Do not contradict the concept's must-avoid list.

## Self-check

- The setting kind is stated and every location follows its rules.
- At least one anachronism or stereotype is named and corrected.
- The sensory palette has all five senses plus a local detail.
- Invented details are labelled.
- No Amazon URL appears in the output.
