---
name: market_research
stage: 2
model_tier: planner
inputs:
  - concept.yaml
  - inputs/market_notes.md (pasted ranks, review counts and prices)
  - search results from the configured search adapter
outputs:
  - output.md
human_gate: false
uses_search: true
uses_randomizer: false
---

## Purpose

Find out what the shelf already offers, from evidence the user can verify: pasted market
notes plus metadata from search APIs. The useful product of this stage is the gap sheet:
what the comparables do not cover, and what is still unknown.

## Inputs

- `inputs/market_notes.md`: notes the user pasted from a storefront or a bestseller list.
  Ranks, review counts and prices are the numbers that matter. If the file is missing, say
  so and continue; never fetch the numbers yourself.
- `concept.yaml`: genre, audience, premise seed, target length.
- Search results from `adapters.search` in `config.yaml`. Results are titles, URLs and
  snippets only. No page is fetched and Amazon links are discarded.

## Steps

1. Read `inputs/market_notes.md`. Parse one comparable per line: rank, title, review count
   and price where present. A markdown table and `- Title - #3 - 4,120 reviews - $4.99`
   are both valid. Merge duplicate titles.
2. Build three to five search queries from the genre and premise: bestsellers and
   comparables, reader complaints, current tropes, and the setting if it is unusual. Run
   each through the configured search adapter and keep title, URL and snippet.
3. Discard Amazon results and anything that is a storefront listing rather than a review,
   a library entry or an article. Do not open the links.
4. Compare the notes with the search results. Note where only one source exists.
5. Write the gap sheet from the evidence:
   - no notes file, or no ranks / reviews / prices in it;
   - every price in a narrow band, which leaves another format or length unclaimed;
   - every comparable below a review threshold, so the top of the category is unrepresented;
   - no reader-complaint notes, so the promise of the genre is unverified;
   - no search results, so the query set needs widening.
6. Ask the model to synthesise only what the evidence supports. Label it as a draft and
   keep the deterministic sections even if the reply is unusable.

## Output format

`output.md` contains:

```
# Market research - <title or slug>

## Comparables
| Rank | Title | Reviews | Price |
| --- | --- | --- | --- |
| 2 | The Lantern Keeper | 12,480 | $4.99 |

## Search results
- [Title](https://...) - snippet

## What's missing
- <specific gap>

## Draft synthesis
<model prose or an unusable-reply note>

## Notes
- <market_notes.md missing, search adapter unavailable, Amazon results ignored>
```

`meta.json` records `market_notes` (path, `found`, parsed entries), `search` (adapter,
queries, result count and results), and `whats_missing`.

## Do not

- Do not scrape a storefront, a search engine result page or Amazon. Use only the pasted
  notes and the configured JSON search API.
- Do not invent ranks, review counts or prices.
- Do not treat a snippet as a full review or quote it as one.
- Do not claim the market is empty because the search returned nothing.
- Do not hide a missing notes file; it is the first line of the gap sheet.

## Self-check

- Every number in the comparables table came from `market_notes.md`.
- No Amazon URL appears in the output or meta.
- The gap sheet has at least one item even when the evidence is thin.
- Search queries are recorded in meta and results are capped.
- The draft synthesis does not introduce a comparable that is absent from the evidence.
