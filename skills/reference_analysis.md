---
name: reference_analysis
stage: 3
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

Learn craft from comparable books without copying them. Use public descriptions,
interviews and reviews to identify structure, pacing and set pieces worth studying; never
store or reproduce book text.

## Inputs

- `concept.yaml`: genre, audience, premise seed, target length.
- `stages/01-intake/` and `stages/02-market_research/` when they exist. The comparables
  from market research are the starting list; missing stages get a note.
- Search results from `adapters.search`. Titles, URLs and snippets only.

## Steps

1. Take up to five comparables from market research, then search each one for structure
   and pacing discussion: chapter counts, point of view, time span, act breaks.
2. Search the genre for what readers say about pacing, endings and the scenes they
   remember. Prefer reviews and craft articles over plot summaries.
3. For each comparable, record only verifiable metadata and the claim its snippet supports.
   If a snippet does not support a claim, leave the claim out.
4. Describe the chapter shape: how many chapters, average length, how many viewpoints,
   where the midpoint turn sits, how the ending pays off the opening. Mark anything inferred
   as inferred.
5. List three to five set pieces the genre expects and what each is for (reveal, reversal,
   intimacy, chase, reckoning). This list feeds `premise_inversion`; do not decide the flips
   here.
6. Ask the model for the craft analysis, with the snippets as the only evidence. A model
   reply that cites a book's text is rejected and replaced with a note.

## Output format

`output.md` contains:

```
# Reference analysis - <title or slug>

## Comparables
- **Title** - [source](https://...) - what the source supports

## Chapter shape
- chapters: ~N (inferred from ...)
- viewpoint: ...
- midpoint: ...

## What readers notice
- <pacing, ending or set-piece observation with source>

## Set pieces the genre expects
- <set piece> - purpose

## Draft craft notes
<model prose or an unusable-reply note>
```

`meta.json` records the comparables, queries, result count and a `source_policy` note that
only snippets were used.

## Do not

- Do not reproduce book text, chapter text or long review excerpts.
- Do not scrape a book page or a retailer; use the search API results only.
- Do not present an inference as a measured fact.
- Do not copy a comparable's plot, characters or opening.
- Do not add a comparable that market research did not record and search did not return.

## Self-check

- Every claim has a source link or is marked inferred.
- No quoted passage is longer than a short snippet.
- The set-piece list is genre-level, not a copy of one book's scenes.
- Missing upstream stages are named in the notes, not silently invented.
- The output contains no Amazon URL.
