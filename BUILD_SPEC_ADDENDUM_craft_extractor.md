# Addendum A: Craft Extractor (build after M4)

Read together with `BUILD_SPEC.md`. Do NOT start this until milestones M1 to M4 pass their tests. It adds milestone **M4b**.

## 1. Purpose

Let the user feed the pipeline reference stories. The tool learns HOW they are built (flow, composition, how characters and settings are represented) and turns that into numeric and categorical targets for our own story. It must not carry over the references' plots, names, places, events, or distinctive phrasing.

Principle: learn the how, never the what.

This extends skill 3 (`reference_analysis`). The search-based version stays for when no files are available. This version reads files the user supplies.

## 2. Inputs

```
references/<id>/source.txt | source.md | source.epub
references/<id>/meta.yaml    # title, author, year, license (public_domain | owned | other), genre, notes
```
- `references/` is in `.gitignore`. Full texts never leave it: never copy them into `projects/`, reports, prompts saved to disk, or logs.
- Parsing is stdlib only: `zipfile` + `html.parser` for EPUB, `re` for chapter and scene splitting. PDF support is optional and needs `pypdf`; ask the user before adding it.
- The tool never downloads copyrighted text from the web.

## 3. Three passes

### Pass 1: metrics (code only, no model)
Split into chapters and scenes (heading patterns, `***`, blank-line runs). Compute, per chapter and for the whole book:
- words per chapter, scenes per chapter, scene length
- paragraph length and sentence length (mean, standard deviation, 10th/90th percentile)
- dialogue ratio (quoted text share), question and exclamation rates
- adverb rate (`-ly`), vocabulary richness over sliding windows
- POV and tense guess (pronoun and verb heuristics)
- sensory word rate by channel (sight, sound, smell, taste, touch) using `tables/sensory_*.json`
- setting-word density
- cast cadence: first-appearance position (percent of book) of the top N recurring named characters, and each one's share of dialogue

### Pass 2: chapter cards (model, chunked)
Feed ONE chapter at a time to the planner-tier model. Output strict JSON, schema-validated, containing only abstractions:
```
function            # setup | complication | reversal | payoff | breather | transition
opening_type        # in-scene | dialogue | description | letter | time-skip | other
ending_type         # cliffhanger | resolution | emotional beat | joke | quiet image | other
tension             # 1-5
emotional_valence   # -2..2
pov_role            # protagonist | mentor | rival | ally | other (ROLES, never names)
scene_types         # e.g. ["negotiation", "chase", "domestic", "training"]
trait_reveal_modes  # share of action / dialogue / narration / other characters' reactions
setting_modes       # share of embedded-in-action / dedicated description / dialogue / sensory focus
devices             # flashback, letter, list, running gag, etc.
humor_type          # none | banter | situational | dry | slapstick | other
```
The prompt MUST say: no names, no places, no plot events, no quotes, roles and categories only.

### Pass 3: aggregate (code)
Produce `craft_profile.json` and a readable `craft_profile.md`:
- act proportions and a tension curve sampled every 5 percent of the book
- cast cadence and cast size
- distribution of chapter opening and ending types, and the rhythm of high and low tension chapters
- character-representation profile (how traits get shown)
- setting-representation profile (how much, and how it is woven in)
- style targets (sentence and paragraph stats, dialogue ratio, sensory mix, humor mix)

## 4. Abstraction guard (mandatory gate)

`pipeline/gates/abstraction_guard.py` runs on every chapter card and on the final profile. It fails if any of these appear:
- a proper noun from the source's most frequent capitalized tokens
- any run of 6 or more words copied from the source
- any quoted string longer than 5 words
A second, model-based "leak check" prompt asks whether the card names a specific plot event. On failure, regenerate pass 2 for the offending chapter (max 3 tries), then stop and report.

## 5. Blending (no single-book imitation)

`story ref blend <id1> <id2> <id3> [--weights ...]` writes `craft_targets.json` with RANGES (min to max) for each metric, not single values. Rules:
- Warn if fewer than 3 references are blended; refuse a single-reference blend unless `--allow-single` is passed.
- A seeded randomizer picks a point inside each range per chapter, so the new book does not trace any one reference.

## 6. Integration with existing skills

- `outline`: act proportions, tension curve, chapter shapes, cast cadence
- `scene_card`: scene types and lengths
- `narrator_voice`: sentence and paragraph targets, dialogue ratio, figurative language rate
- `character_creation`: cast size and the trait-reveal profile
- `chapter_writer`: setting-representation profile and sensory mix
- `quality_gates`: compare each new chapter's Pass 1 metrics to the target ranges and flag drift; also run the originality n-gram check against the LOCAL reference texts, which are available offline, and fail above the threshold

## 7. CLI additions

```
story ref add <path> --license public_domain|owned|other
story ref list
story ref analyze <id>
story ref show <id>
story ref blend <id> <id> <id> [--weights ...] [--allow-single]
```

## 8. Milestone M4b and acceptance tests

Use a tiny synthetic 3-chapter fixture written for the tests (not copyrighted text).
- Pass 1 metrics are deterministic and match hand-computed values on the fixture.
- Pass 2 with the `echo` adapter returns schema-valid cards; invalid cards are rejected.
- The abstraction guard fails on a planted proper noun, a planted 6-word copied run, and a long quote, and passes on a clean card.
- Blending three profiles produces ranges; a single-reference blend is refused without `--allow-single`.
- The pipeline never writes any reference text outside `references/` (test by scanning outputs for planted sentinel strings).

## 9. Usage notes (for the human)

- Prefer public-domain references for certainty. Use in-copyright books only if you legally have a copy, and keep them local. I'm not a lawyer, so check if you plan to rely on this.
- Pick 3 to 5 references that match the genre and tone you want.
- Free models read long books lossily. Chunking by chapter helps, but expect rough edges, and verify the profile makes sense to you before approving it.
- This captures structure and measurable style. It will not capture what makes a particular author's prose special. That is a feature: the goal is a craft profile, not a clone.
