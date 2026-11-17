"""Deterministic scaffolding for stages 1-7.

Each stage has a real job even when the configured model returns nothing useful: the
concept brief, the market gap sheet, the reference evidence, the setting sheet, the genre
expectations/flip table and the tone ceiling are all computed here. The model adds prose on
top; it never owns the structure the later stages depend on.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from .adapters import AdapterError, LLMAdapter, SearchAdapter, SearchResult

# --------------------------------------------------------------------------- shared


TONE_LABELS = {0: "cozy", 1: "warm", 2: "tense", 3: "action-comedy"}

TONE_QUESTIONS = {
    0: "Can you stay safe without disappearing?",
    1: "Can you belong without being owned?",
    2: "What does it cost to tell the truth in time?",
    3: "Who gets to set the terms of the joke?",
}

TONE_PRESSURE = {
    0: "the town's need for the story to stay tidy",
    1: "the family that benefits from the old arrangement",
    2: "the institution that owns the record",
    3: "the audience that is already laughing",
}

TONE_UNDER_COMFORT = {
    0: "What if safety is the thing keeping her from being known?",
    1: "What if the person who makes you comfortable is the one you have to leave?",
    2: "What if the truth arrives too late to be clean?",
    3: "What if the joke is the only way to say the true thing?",
}

TONE_ARCS = {
    0: (
        "guarded comfort, keeping the peace",
        "the peace costs someone else, and she notices",
        "chooses a risk the community has to absorb",
    ),
    1: (
        "belonging by obeying the rules",
        "the rules require a betrayal she cannot make",
        "chooses a belonging she has to build",
    ),
    2: (
        "certainty that the record can be corrected",
        "the correction implicates the people she needs",
        "tells the truth and pays for it without being healed",
    ),
    3: (
        "being the joke and pretending to enjoy it",
        "the joke becomes the only honest language in the room",
        "sets the terms and lets the laughter land where it lands",
    ),
}

TONE_CEILINGS: dict[int, dict[str, Any]] = {
    0: {
        "label": "cozy",
        "ceiling": (
            "No on-page violence and nothing irreversible happens to a likable character; "
            "conflict is social and can be repaired."
        ),
        "on_page": [
            "social embarrassment, money trouble, weather, a door that will not lock",
            "one argument per chapter, resolved or softened before the next",
        ],
        "per_chapter": "one social setback and one small recovery; no cliffhanger emergencies",
        "off_table": [
            "graphic violence or its aftermath",
            "the death of a likable character on the page",
            "sexual violence, on or off the page",
        ],
    },
    1: {
        "label": "warm",
        "ceiling": (
            "Danger can be on the page, but the story allows one real loss and no lingering "
            "graphic injury; comfort is earned, not guaranteed."
        ),
        "on_page": [
            "danger with a way out, a loss that changes the plan",
            "one relationship that cannot be repaired to its old shape",
        ],
        "per_chapter": "one serious setback and one recovery; the middle cannot be all emergency",
        "off_table": [
            "graphic torture",
            "violence against children on the page",
            "a hopeless ending with no one left to choose",
        ],
    },
    2: {
        "label": "tense",
        "ceiling": (
            "On-page danger with consequences that do not heal; at least one irreversible "
            "choice, and comfort is scarce but never absent."
        ),
        "on_page": [
            "violence with weight, a cost that stays in the body",
            "a betrayal that changes who can be trusted",
        ],
        "per_chapter": "one hard turn; at most one chapter in three may end on pure dread",
        "off_table": [
            "torture as spectacle",
            "violence whose only purpose is to prove the villain is bad",
            "a twist that erases a character's earlier choices",
        ],
    },
    3: {
        "label": "action-comedy",
        "ceiling": (
            "Comic violence and high energy are allowed, but the stakes stay real and no "
            "character carries lingering trauma on the page."
        ),
        "on_page": [
            "chases, fights with improbable props, public humiliation that is survivable",
            "a plan that fails loudly and a friendship that survives it",
        ],
        "per_chapter": "one set piece and one quiet beat to let the joke land",
        "off_table": [
            "graphic injury played for laughs",
            "cruelty aimed at a character's identity",
            "a joke that requires the reader to share a stereotype",
        ],
    },
}

GENRE_EXPECTATIONS: dict[str, list[str]] = {
    "mystery": [
        "a crime is discovered and the reader is given the clues to follow",
        "a detective or amateur investigator moves from confusion to explanation",
        "the culprit is revealed and the world is made legible again",
        "a false solution misleads before the true one",
    ],
    "cozy": [
        "the community is the real subject, and the victim is an outsider or a nuisance",
        "the amateur sleuth has a trade that gives access to secrets",
        "violence stays off the page and order is restored",
        "food, weather and small-town routine carry the comfort",
    ],
    "thriller": [
        "a clock limits the protagonist's choices",
        "the antagonist is close enough to touch",
        "a reversal reveals that the institution is compromised",
        "the protagonist must act before being certain",
    ],
    "romance": [
        "the two leads meet and cannot be together for a reason the reader accepts",
        "proximity forces them to see each other clearly",
        "a secret or obligation pulls them apart at the worst moment",
        "they choose each other and the ending is emotionally earned",
    ],
    "fantasy": [
        "a secondary world with rules the reader can learn",
        "a chosen or unlikely figure gains access to power",
        "a journey or contest tests what the power costs",
        "the world is saved or changed by a sacrifice",
    ],
    "science fiction": [
        "a technological or social change is taken to its consequences",
        "the protagonist is positioned between the old order and the new",
        "a discovery reframes what the reader thought the premise was",
        "the ending asks what the change costs, not only what it wins",
    ],
    "sci-fi": [
        "a technological or social change is taken to its consequences",
        "a discovery reframes what the reader thought the premise was",
        "the ending weighs the cost of the change",
    ],
    "horror": [
        "a threat violates the rules of ordinary space",
        "isolation makes help unreliable",
        "the protagonist learns the threat's logic too late",
        "survival costs something the protagonist cannot get back",
    ],
    "literary": [
        "the prose is a pleasure on its own, not only a vehicle for plot",
        "a private wound and a public world press on each other",
        "the ending refuses an easy moral",
        "the central question survives the last page",
    ],
    "historical": [
        "the period shapes what the characters can want and say",
        "ordinary labour, money and power are concrete",
        "a public event enters through a private life",
        "the ending acknowledges what the period would not allow",
    ],
    "young adult": [
        "the protagonist is discovering who they are while the stakes are immediate",
        "adults are present but cannot be relied on to solve the problem",
        "friendship and first love carry as much weight as the plot",
        "the protagonist chooses a self, not just a outcome",
    ],
    "comedy": [
        "a straight figure and a chaotic figure cannot avoid each other",
        "the plan escalates until it cannot be explained",
        "social embarrassment is the engine, not the decoration",
        "the ending lets the fool and the straight figure meet halfway",
    ],
}

DEFAULT_EXPECTATIONS = [
    "a protagonist wants something concrete and is denied it",
    "an obstacle forces a choice the protagonist cannot undo",
    "the middle reveals that the obstacle is not what it seemed",
    "the ending answers the opening question at a cost",
]

FLIP_TEMPLATES = [
    "Give the power to the wrong person: the one who should deliver this is the one who cannot.",
    "Make the expected outcome the failure state: getting it is what ruins the plan.",
    "Set the convention somewhere it is illegal or unfashionable; the plot is the cost of doing it anyway.",
    "Delay the beat until it can only make things worse, then let the character choose it knowingly.",
    "Let the absence do the work: remove the beat entirely and make the hole the story.",
]

MARKET_NOTES_MAX_ROWS = 20


def _stage_dir(project: Path, number: int) -> Path | None:
    stages = project / "stages"
    if not stages.is_dir():
        return None
    matches = sorted(stages.glob(f"{number:02d}-*"))
    return matches[0] if matches else None


def _read_meta(project: Path, number: int) -> dict[str, Any]:
    directory = _stage_dir(project, number)
    if directory is None:
        return {}
    path = directory / "meta.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_output(project: Path, number: int) -> str:
    directory = _stage_dir(project, number)
    path = directory / "output.md" if directory else None
    return path.read_text(encoding="utf-8") if path and path.is_file() else ""


def _title(concept: Mapping[str, Any], slug: str) -> str:
    return str(concept.get("working_title") or "").strip() or slug


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _tone_dial(concept: Mapping[str, Any], notes: list[str]) -> int:
    raw = concept.get("tone_dial", 1)
    try:
        tone = int(raw)
    except (TypeError, ValueError):
        tone = 1
    if isinstance(raw, bool) or tone not in TONE_LABELS:
        notes.append(f"tone_dial {raw!r} is not 0-3; used 1 (warm)")
        return 1
    return tone


def _prompt(
    skill,
    concept: Mapping[str, Any],
    upstream: str,
    extra_sections: str,
    notes: Sequence[str],
) -> str:
    sections = "\n\n".join(f"## {name}\n\n{text}" for name, text in skill.sections.items())
    note_text = "\n".join(f"- {note}" for note in notes) or "- none"
    return (
        f"{sections}\n\n"
        "## This project\n\n"
        f"```yaml\n{yaml.safe_dump(dict(concept), sort_keys=False)}```\n\n"
        f"{extra_sections.strip()}\n\n"
        "Earlier stage outputs:\n"
        f"{upstream.strip() or '(none yet)'}\n\n"
        "Notes:\n"
        f"{note_text}\n"
    )


def _model_text(
    llm: LLMAdapter,
    skill,
    prompt: str,
    extra_notes: list[str],
    *,
    empty: str = "_No model prose: the deterministic sections above stand._",
) -> str:
    try:
        reply = llm.complete(
            prompt,
            system=skill.sections["Purpose"],
            model_tier=skill.model_tier,
            max_tokens=2500,
        )
    except Exception as exc:  # the stage's deterministic work still stands
        extra_notes.append(f"model call failed: {exc}")
        return empty
    text = (reply or "").strip()
    if not text or text.lower() == "echo":
        extra_notes.append("model returned no prose (echo adapter); deterministic sections stand")
        return empty
    return text


def _run_searches(
    search: SearchAdapter | None,
    queries: Sequence[str],
    notes: list[str],
    *,
    per_query: int = 4,
    limit: int = 12,
) -> list[SearchResult]:
    if search is None:
        notes.append(
            "no search adapter configured (adapters.search); ran with no web results"
        )
        return []
    found: list[SearchResult] = []
    seen: set[str] = set()
    for query in queries:
        try:
            results = search.search(query, max_results=per_query)
        except AdapterError as exc:
            notes.append(f"search failed for {query!r}: {exc}")
            continue
        for result in results:
            if result.url in seen:
                continue
            seen.add(result.url)
            found.append(result)
            if len(found) >= limit:
                return found
    return found


def _search_meta(
    search: SearchAdapter | None,
    queries: Sequence[str],
    results: Sequence[SearchResult],
) -> dict[str, Any]:
    details = search.describe() if search is not None else None
    return {
        "adapter": getattr(search, "name", None) if search is not None else None,
        "details": details,
        "queries": list(queries),
        "results": [result.to_dict() for result in results],
        "count": len(results),
    }


def _search_queries(concept: Mapping[str, Any]) -> list[str]:
    genre = _clean(concept.get("genre")) or "fiction"
    premise = _clean(concept.get("premise_seed"))
    queries = [
        f"{genre} bestsellers comparable titles",
        f"{genre} reader reviews common complaints",
        f"{genre} tropes readers expect",
    ]
    if premise:
        queries.insert(1, f"{premise} {genre} comparable books")
    return queries


def _genre_expectations(genre: str) -> list[str]:
    lowered = genre.lower()
    expectations: list[str] = []
    for key, values in GENRE_EXPECTATIONS.items():
        if key == "ya":
            matched = re.search(r"\bya\b", lowered) is not None
        else:
            matched = key in lowered
        if matched:
            expectations.extend(value for value in values if value not in expectations)
    return expectations or list(DEFAULT_EXPECTATIONS)


def _market_comparables(project: Path) -> tuple[list[str], str | None]:
    """Comparable titles recorded by stage 2, with the path they came from."""
    meta = _read_meta(project, 2)
    titles: list[str] = []
    for item in meta.get("comparables") or []:
        if isinstance(item, Mapping):
            title = _clean(item.get("title"))
        else:
            title = _clean(item)
        if title and title not in titles:
            titles.append(title)
    if not titles:
        for entry in (meta.get("market_notes") or {}).get("entries") or []:
            title = _clean((entry or {}).get("title")) if isinstance(entry, Mapping) else ""
            if title and title not in titles:
                titles.append(title)

    if not titles:
        section = ""
        output = _read_output(project, 2)
        if "## Comparables" in output:
            section = output.split("## Comparables", 1)[1].split("\n## ", 1)[0]
        for line in section.splitlines():
            text = line.strip()
            if not text or text.startswith("|") or text.lower().startswith("##"):
                continue
            if text.startswith("|") or not text.startswith(("-", "*")):
                continue
            text = text.lstrip("-* ").strip()
            text = text.replace("**", "")
            title = re.split(r"\s+[—–]\s+|\s+-\s+", text, maxsplit=1)[0].strip()
            if title and title not in titles:
                titles.append(title)

    directory = _stage_dir(project, 2)
    source = None
    if directory is not None:
        source = str((directory / "output.md").relative_to(project)).replace("\\", "/")
    return titles, source


# --------------------------------------------------------------------------- market notes

RANK_RE = re.compile(r"#\s*(\d{1,4})\b|\brank(?:ed)?\s*[:#]?\s*(\d{1,4})\b", re.IGNORECASE)
REVIEWS_RE = re.compile(r"([\d][\d,]{0,11})\s*(?:reviews?|ratings?)\b", re.IGNORECASE)
REVIEWS_BEFORE_RE = re.compile(r"\b(?:reviews?|ratings?)\s*[:#]?\s*([\d][\d,]*)", re.IGNORECASE)
PRICE_RE = re.compile(r"\$\s*(\d+(?:\.\d{1,2})?)")
LIST_PREFIX_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*")
SEPARATOR_RE = re.compile(r"^:?-{2,}:?$")


def _number(text: str) -> int | None:
    match = RANK_RE.search(text)
    if match:
        return int(match.group(1) or match.group(2))
    return None


def _reviews(text: str) -> int | None:
    match = REVIEWS_RE.search(text)
    if match:
        return int(match.group(1).replace(",", ""))
    match = REVIEWS_BEFORE_RE.search(text)
    if match:
        return int(match.group(1).replace(",", ""))
    return None


def _price(text: str) -> float | None:
    match = PRICE_RE.search(text)
    return float(match.group(1)) if match else None


def _looks_numeric(cell: str) -> bool:
    return bool(
        not cell
        or cell.isdigit()
        or PRICE_RE.fullmatch(cell.strip())
        or re.fullmatch(r"#?\d+", cell.strip())
        or re.fullmatch(r"[\d,]+", cell.strip())
        or cell.strip().lower() in {"hardcover", "paperback", "ebook", "audiobook"}
    )


def parse_market_notes(text: str) -> list[dict[str, Any]]:
    """Parse one comparable per line, from a table or from bullet notes.

    Every field is optional except the title; a line with no rank, review count or price is
    treated as prose and skipped.
    """
    entries: dict[str, dict[str, Any]] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("|"):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if not cells or all(not cell or SEPARATOR_RE.fullmatch(cell) for cell in cells):
                continue
            body = " ".join(cells)
            title = next((cell for cell in cells if cell and not _looks_numeric(cell)), "")
            rank = int(cells[0]) if cells[0].isdigit() else None
            rank = rank if rank is not None else _number(body)
        else:
            body = LIST_PREFIX_RE.sub("", line).strip()
            head = re.split(r"\s+[—–]\s+|\s+-\s+", body, maxsplit=1)[0].strip()
            title = head.replace("**", "").strip("` ")
            rank = _number(body)

        reviews = _reviews(body)
        price = _price(body)
        if not title or (rank is None and reviews is None and price is None):
            continue

        key = title.casefold()
        existing = entries.get(key)
        if existing is None:
            entries[key] = {
                "title": title,
                "rank": rank,
                "reviews": reviews,
                "price": price,
            }
        else:
            for field, value in (("rank", rank), ("reviews", reviews), ("price", price)):
                if existing[field] is None and value is not None:
                    existing[field] = value
        if len(entries) >= MARKET_NOTES_MAX_ROWS:
            break
    return list(entries.values())


def _fmt_int(value: int | None) -> str:
    return f"{value:,}" if value is not None else "-"


def _fmt_price(value: float | None) -> str:
    return f"${value:,.2f}" if value is not None else "-"


def _whats_missing(
    entries: Sequence[Mapping[str, Any]],
    results: Sequence[SearchResult],
    notes_found: bool,
) -> list[str]:
    gaps: list[str] = []
    if not notes_found:
        gaps.append(
            "No `inputs/market_notes.md`: paste the top ranks, review counts and prices "
            "so the comparables can be compared."
        )
    elif not entries:
        gaps.append(
            "`inputs/market_notes.md` has no parsable comparables: use "
            "`Title - #rank - N reviews - $price`, one per line."
        )
    else:
        if any(entry.get("rank") is None for entry in entries):
            gaps.append("Some comparables have no bestseller rank; the category's top is unknown.")
        if any(entry.get("reviews") is None for entry in entries):
            gaps.append("Some comparables have no review count; demand is unmeasured.")
        if any(entry.get("price") is None for entry in entries):
            gaps.append("Some comparables have no price; the price band is incomplete.")
        prices = [float(entry["price"]) for entry in entries if entry.get("price") is not None]
        if len(prices) >= 2 and max(prices) - min(prices) < 1.5:
            gaps.append(
                f"Every priced comparable sits in a ${min(prices):.2f}-${max(prices):.2f} "
                "band; a different format, length or price point is unclaimed."
            )
        reviews = [int(entry["reviews"]) for entry in entries if entry.get("reviews") is not None]
        if reviews and max(reviews) < 1000:
            gaps.append(
                "Every comparable is under 1,000 reviews; the top of the category is not represented."
            )

    if not results:
        gaps.append(
            "No search results: check `adapters.search` in config.yaml or widen the queries."
        )
    gaps.append(
        "No reader-complaint notes yet: add what negative reviews complain about to "
        "`inputs/market_notes.md`."
    )
    return gaps


# --------------------------------------------------------------------------- stage 1


def _intake(stage, skill, project, concept, upstream, notes, llm, search):
    title = _title(concept, project.name)
    open_questions: list[str] = []
    for field, need in (
        ("genre", "the shelf the book belongs on"),
        ("audience", "who the book is for"),
        ("premise_seed", "one sentence: who wants what, and what it costs"),
        ("pen_name", "the name to publish under, or 'none'"),
    ):
        if not _clean(concept.get(field)):
            open_questions.append(f"`{field}` is empty: add {need}.")

    tone = _tone_dial(concept, notes)
    must_include = concept.get("must_include") or []
    must_avoid = concept.get("must_avoid") or []
    premise = _clean(concept.get("premise_seed")) or "Not filled in yet."

    extra = "## Intake facts\n\n" + "\n".join(
        [
            f"- genre: {_clean(concept.get('genre')) or '(not set)'}",
            f"- audience: {_clean(concept.get('audience')) or '(not set)'}",
            f"- tone dial: {tone} ({TONE_LABELS[tone]})",
            f"- target length: {concept.get('target_words', 60000)} words",
            f"- premise: {premise}",
            f"- must include: {', '.join(map(str, must_include)) or '(none)'}",
            f"- must avoid: {', '.join(map(str, must_avoid)) or '(none)'}",
        ]
    )
    prompt = _prompt(skill, concept, upstream, extra, notes)
    draft = _model_text(llm, skill, prompt, notes)

    lines = [
        f"# Intake brief — {title}",
        "",
        "## Concept",
        f"- genre: {_clean(concept.get('genre')) or '(not set)'}",
        f"- audience: {_clean(concept.get('audience')) or '(not set)'}",
        f"- tone dial: {tone} ({TONE_LABELS[tone]})",
        f"- target length: {concept.get('target_words', 60000)} words",
        f"- pen name: {_clean(concept.get('pen_name')) or '(not set)'}",
        "",
        "## Premise",
        premise,
        "",
        "## Constraints",
        f"- Must include: {', '.join(map(str, must_include)) or '(none)'}",
        f"- Must avoid: {', '.join(map(str, must_avoid)) or '(none)'}",
        "",
        "## Brief",
        draft,
        "",
        "## Open questions",
        "\n".join(f"- {question}" for question in open_questions) or "- None: the concept is complete.",
        "",
        "## Notes",
        "\n".join(f"- {note}" for note in notes) or "- none",
    ]
    meta = {
        "files": ["output.md", "meta.json"],
        "open_questions": open_questions,
        "tone_dial": tone,
    }
    return "\n".join(lines), meta, []


# --------------------------------------------------------------------------- stage 2


def _market_research(stage, skill, project, concept, upstream, notes, llm, search):
    title = _title(concept, project.name)
    notes_path = project / "inputs" / "market_notes.md"
    notes_found = notes_path.is_file()
    raw_notes = notes_path.read_text(encoding="utf-8") if notes_found else ""
    entries = parse_market_notes(raw_notes) if notes_found else []
    if notes_found and not entries:
        notes.append("inputs/market_notes.md has no parsable rank/review/price lines")
    elif not notes_found:
        notes.append("no inputs/market_notes.md yet; the gap sheet says what to paste")

    queries = _search_queries(concept)
    results = _run_searches(search, queries, notes)
    gaps = _whats_missing(entries, results, notes_found)

    table = ["| Rank | Title | Reviews | Price |", "| --- | --- | --- | --- |"]
    table.extend(
        f"| {entry.get('rank') if entry.get('rank') is not None else '-'} "
        f"| {entry.get('title')} | {_fmt_int(entry.get('reviews'))} "
        f"| {_fmt_price(entry.get('price'))} |"
        for entry in entries
    )
    if not entries:
        table.append("| - | No comparables parsed yet | - | - |")

    result_lines = (
        "\n".join(
            f"- [{result.title}]({result.url}) — {result.snippet or '(no snippet)'}"
            for result in results
        )
        or "- No search results. Add an adapter under `adapters.search` or paste notes instead."
    )

    extra = (
        f"## Comparables from inputs/market_notes.md\n\n{raw_notes.strip() or '(no notes yet)'}\n\n"
        f"## Search results\n\n{result_lines}\n\n"
        f"## Gap sheet\n\n" + "\n".join(f"- {gap}" for gap in gaps)
    )
    prompt = _prompt(skill, concept, upstream, extra, notes)
    draft = _model_text(llm, skill, prompt, notes)

    lines = [
        f"# Market research — {title}",
        "",
        "## Comparables",
        *table,
        "",
        "## Search results",
        result_lines,
        "",
        "## What's missing",
        "\n".join(f"- {gap}" for gap in gaps),
        "",
        "## Draft synthesis",
        draft,
        "",
        "## Notes",
        "\n".join(f"- {note}" for note in notes) or "- none",
        "",
        "_Only metadata from the pasted notes and the search API was used; no page was fetched "
        "and Amazon results are dropped._",
    ]
    meta = {
        "files": ["output.md", "meta.json"],
        "market_notes": {
            "path": "inputs/market_notes.md",
            "found": notes_found,
            "entries": entries,
        },
        "search": _search_meta(search, queries, results),
        "comparables": [{"title": entry["title"]} for entry in entries],
        "whats_missing": gaps,
    }
    return "\n".join(lines), meta, []


# --------------------------------------------------------------------------- stage 3


def _reference_analysis(stage, skill, project, concept, upstream, notes, llm, search):
    title = _title(concept, project.name)
    genre = _clean(concept.get("genre")) or "fiction"
    comparables, source = _market_comparables(project)
    if not comparables:
        notes.append("stage 02-market_research has no comparables; reference list is genre-only")

    queries = [f'"{name}" chapter structure pacing review' for name in comparables[:3]]
    queries.extend(
        [
            f"{genre} reader reviews pacing ending",
            f"{genre} set pieces structure",
        ]
    )
    results = _run_searches(search, queries, notes)
    set_pieces = _genre_expectations(genre)[:4]

    evidence = "\n".join(
        f"- **{item.title}** — [{item.url}]({item.url}) — {item.snippet or '(no snippet)'}"
        for item in results
    ) or "- No sources yet; add an adapter under `adapters.search`."
    comparable_lines = "\n".join(f"- {name}" for name in comparables) or "- none recorded"

    extra = (
        f"## Comparables\n\n{comparable_lines}\n\n"
        f"## Evidence snippets\n\n{evidence}\n\n"
        "Only snippets and metadata are available; do not reproduce book text."
    )
    prompt = _prompt(skill, concept, upstream, extra, notes)
    draft = _model_text(llm, skill, prompt, notes)

    lines = [
        f"# Reference analysis — {title}",
        "",
        "## Comparables",
        comparable_lines,
        "",
        "## Chapter shape",
        "- Counts, viewpoints and act breaks must be supported by the sources below; this "
        "stage does not measure or copy a book.",
        "- Record the chapter count and midpoint only when a source states them.",
        "",
        "## What readers notice",
        evidence,
        "",
        "## Set pieces the genre expects",
        "\n".join(f"- {piece}" for piece in set_pieces),
        "",
        "## Draft craft notes",
        draft,
        "",
        "## Notes",
        "\n".join(f"- {note}" for note in notes) or "- none",
        "",
        "_Snippets only: no page was fetched, no book text is stored, and Amazon is excluded._",
    ]
    meta = {
        "files": ["output.md", "meta.json"],
        "comparables": comparables,
        "market_source": source,
        "search": _search_meta(search, queries, results),
        "source_policy": "snippets only; no page fetch; no book text stored",
        "set_pieces": set_pieces,
    }
    return "\n".join(lines), meta, []


# --------------------------------------------------------------------------- stage 4


def _setting_research(stage, skill, project, concept, upstream, notes, llm, search):
    title = _title(concept, project.name)
    genre = _clean(concept.get("genre")) or "fiction"
    premise = _clean(concept.get("premise_seed"))
    lowered = genre.lower()
    if any(
        marker in lowered
        for marker in ("fantasy", "science fiction", "sci-fi", "space", "secondary world")
    ):
        kind = "secondary world (invented places and rules)"
    else:
        kind = "real place and period (exact place and period not stated in the concept)"
    if not _clean(concept.get("setting")):
        notes.append("concept.yaml has no setting field; the place and period are still open")

    queries = [
        f"{premise} {genre} daily life details".strip(),
        f"{genre} vocabulary period words",
        f"{genre} setting common mistakes",
    ]
    results = _run_searches(search, queries, notes)
    sources = "\n".join(
        f"- [{result.title}]({result.url}) — {result.snippet or '(no snippet)'}"
        for result in results
    ) or "- No sources yet; add an adapter under `adapters.search`."

    extra = f"## Setting kind\n\n{kind}\n\n## Sources\n\n{sources}"
    prompt = _prompt(skill, concept, upstream, extra, notes)
    draft = _model_text(llm, skill, prompt, notes)

    lines = [
        f"# Setting research — {title}",
        "",
        "## Setting kind",
        f"- {kind}",
        "",
        "## Daily life",
        "- Work and money: who employs whom, what a day costs.",
        "- Food and transport: what is ordinary here, and what is a treat.",
        "- Housing and weather: what the body notices on the way to a scene.",
        "- Power: who can make a decision and who has to ask.",
        "",
        "## Vocabulary",
        "- Use the words the period or trade would use; list anachronisms before drafting.",
        "- A local detail named correctly buys more trust than a paragraph of description.",
        "",
        "## Sensory palette",
        "- Sight: the first thing a local notices.",
        "- Sound: the background that stops when something is wrong.",
        "- Smell and texture: the detail that makes a room specific.",
        "",
        "## Locations for scenes",
        "- A public place with a social rule.",
        "- A private place where the rule can be broken.",
        "- A threshold that costs something to cross.",
        "",
        "## Common mistakes",
        "- Anachronistic technology, money or vocabulary.",
        "- A stereotype used as local colour.",
        "- Geography or labour that only exists in films.",
        "",
        "## Sources",
        sources,
        "",
        "## Draft notes",
        draft,
        "",
        "## Notes",
        "\n".join(f"- {note}" for note in notes) or "- none",
    ]
    meta = {
        "files": ["output.md", "meta.json"],
        "setting_kind": kind,
        "search": _search_meta(search, queries, results),
        "invented_details": "model proposals are drafts until checked against the world rules",
    }
    return "\n".join(lines), meta, []


# --------------------------------------------------------------------------- stage 5


def _premise_inversion(stage, skill, project, concept, upstream, notes, llm, search):
    title = _title(concept, project.name)
    genre = _clean(concept.get("genre")) or "fiction"
    premise = (
        _clean(_read_meta(project, 5).get("premise"))
        or _clean(concept.get("premise_seed"))
        or "a protagonist wants something the world will not give"
    )
    expectations = _genre_expectations(genre)
    comparables, source = _market_comparables(project)
    gaps = list(_read_meta(project, 2).get("whats_missing") or [])

    chosen = expectations[:2]
    flips = [
        (expectation, FLIP_TEMPLATES[index % len(FLIP_TEMPLATES)])
        for index, expectation in enumerate(chosen)
    ]
    keeps = expectations[len(chosen) :]

    extra = (
        f"## Genre\n\n{genre}\n\n"
        f"## Expectations\n\n" + "\n".join(f"- {item}" for item in expectations) + "\n\n"
        f"## Comparables\n\n" + ("\n".join(f"- {name}" for name in comparables) or "- none")
    )
    prompt = _prompt(skill, concept, upstream, extra, notes)
    draft = _model_text(llm, skill, prompt, notes)

    comparison: list[str] = []
    if source:
        comparison.append(f"- comparables: {', '.join(comparables)}")
        for name in comparables:
            comparison.append(
                f"- {name}: check whether this book already uses the flip; "
                "similarity judgment is human work until the originality gate."
            )
        if gaps:
            comparison.extend(f"- stage 2 gap: {gap}" for gap in gaps[:3])
    else:
        comparison.append("- 02-market_research has not run: comparison pending.")

    lines = [
        f"# Premise inversion — {title}",
        "",
        "## What the genre expects",
        "\n".join(f"- {item}" for item in expectations),
        "",
        "## What we flip",
        "\n".join(
            f"- **{expectation}** → {flip}" for expectation, flip in flips
        )
        or "- No expectation selected; keep the genre promise and change the cost.",
        "",
        "### Kept on purpose",
        "\n".join(f"- **{item}** — keep: the promise is why the reader picked the book." for item in keeps)
        or "- Nothing kept; the genre promises are all changed.",
        "",
        f"- Story-specific inversion: {premise}",
        "",
        "## One-line premise",
        premise,
        "",
        "## Market comparison",
        "\n".join(comparison),
        "",
        "## Draft alternatives",
        draft,
        "",
        "## Notes",
        "\n".join(f"- {note}" for note in notes) or "- none",
    ]
    meta = {
        "files": ["output.md", "meta.json"],
        "genre": genre,
        "expectations": expectations,
        "flips": [{"expectation": item, "flip": flip} for item, flip in flips],
        "keeps": keeps,
        "premise": premise,
        "market_comparison": {
            "found": source is not None and bool(comparables),
            "source": source,
            "comparables": comparables,
        },
    }
    return "\n".join(lines), meta, []


# --------------------------------------------------------------------------- stage 6


def _theme_premise(stage, skill, project, concept, upstream, notes, llm, search):
    title = _title(concept, project.name)
    tone = _tone_dial(concept, notes)
    premise = (
        _clean(_read_meta(project, 5).get("premise"))
        or _clean(concept.get("premise_seed"))
        or "Not filled in yet"
    )
    question = TONE_QUESTIONS[tone]
    pressure = TONE_PRESSURE[tone]
    act_one, act_two, act_three = TONE_ARCS[tone]

    extra = (
        f"## Premise\n\n{premise}\n\n"
        f"## Tone\n\n{tone} ({TONE_LABELS[tone]})\n\n"
        "*The central question is deterministic; the model may explore it but does not replace it.*"
    )
    prompt = _prompt(skill, concept, upstream, extra, notes)
    draft = _model_text(llm, skill, prompt, notes)

    lines = [
        f"# Theme and premise — {title}",
        "",
        "## Premise",
        premise,
        "",
        "## Central question",
        question,
        "",
        "## Pressure",
        pressure,
        "",
        "## Emotional arc",
        f"- Act 1: {act_one}",
        f"- Act 2: {act_two}",
        f"- Act 3: {act_three}",
        "",
        "## The question under the comfort",
        TONE_UNDER_COMFORT[tone],
        "",
        "## Draft exploration",
        draft,
        "",
        "## Notes",
        "\n".join(f"- {note}" for note in notes) or "- none",
    ]
    meta = {
        "files": ["output.md", "meta.json"],
        "central_question": question,
        "premise": premise,
        "pressure": pressure,
        "tone_dial": tone,
    }
    return "\n".join(lines), meta, []


# --------------------------------------------------------------------------- stage 7


def _tone_ceiling(stage, skill, project, concept, upstream, notes, llm, search):
    title = _title(concept, project.name)
    tone = _tone_dial(concept, notes)
    ceiling = TONE_CEILINGS[tone]

    extra = (
        f"## Dial\n\n{tone} ({TONE_LABELS[tone]})\n\n"
        "*The ceiling table is deterministic; the model may add a tonal note only.*"
    )
    prompt = _prompt(skill, concept, upstream, extra, notes)
    draft = _model_text(llm, skill, prompt, notes)

    lines = [
        f"# Tone ceiling — {title}",
        "",
        "## Dial",
        f"- tone_dial: {tone} ({ceiling['label']})",
        "",
        "## Conflict ceiling",
        f"- conflict ceiling: {ceiling['ceiling']}",
        "",
        "## What can happen on the page",
        "\n".join(f"- {item}" for item in ceiling["on_page"]),
        "",
        "## Per chapter",
        f"- {ceiling['per_chapter']}",
        "",
        "## Off the table",
        "\n".join(f"- {item}" for item in ceiling["off_table"]),
        "",
        "## Model notes",
        draft,
        "",
        "## Notes",
        "\n".join(f"- {note}" for note in notes) or "- none",
    ]
    meta = {
        "files": ["output.md", "meta.json"],
        "tone_dial": tone,
        "label": ceiling["label"],
        "ceiling": ceiling["ceiling"],
        "per_chapter": ceiling["per_chapter"],
    }
    return "\n".join(lines), meta, []


# --------------------------------------------------------------------------- dispatch


_BUILDERS = {
    "intake": _intake,
    "market_research": _market_research,
    "reference_analysis": _reference_analysis,
    "setting_research": _setting_research,
    "premise_inversion": _premise_inversion,
    "theme_premise": _theme_premise,
    "tone_ceiling": _tone_ceiling,
}


def run(
    stage,
    skill,
    project: Path,
    concept: Mapping[str, Any],
    upstream: str,
    notes: Sequence[str],
    llm: LLMAdapter,
    search: SearchAdapter | None,
) -> tuple[str, dict[str, Any], list[str]]:
    """Run one stage 1-7 builder. Returns (output, extra meta, extra notes)."""
    try:
        builder = _BUILDERS[stage.name]
    except KeyError:
        raise ValueError(f"early_stages has no builder for {stage.name}") from None
    working_notes = list(notes)
    output, meta, extra_notes = builder(
        stage, skill, Path(project), dict(concept), upstream, working_notes, llm, search
    )
    # The builder appends its own notes to the list it was given; return only the new ones.
    return output, meta, working_notes[len(notes) :] + extra_notes
