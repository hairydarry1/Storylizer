"""Stage 11: the outline.

The randomizer supplies chapter shapes, imagery domains and complication cards; this module
assigns them so the five outline validators hold by construction, and writes the machine
readable `outline.json` plus the additive `rules_additions.json`. The model only adds prose.

Validators (BUILD_SPEC.md section 5, stage 11):

* no more than two consecutive chapters share one shape
* every secondary character first appears in a different chapter (and appears at all)
* the background threat reaches at least 40% of chapters
* the protagonist acts in at least 70% of resolution beats
* the tension curve is not monotonic
"""

from __future__ import annotations

import copy
import math
import random
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import yaml

from . import craft_targets, ledger
from .early_stages import TONE_PRESSURE
from .randomizer import seed_int

STAGE_DIR = "11-outline"
STAGE11_NUMBER = 11
ACT_PROPORTIONS = (0.25, 0.5, 0.25)
MIN_CHAPTERS = 8
MAX_SHAPE_RUN = 2
THREAT_SHARE = 0.4
PROTAGONIST_SHARE = 0.7
DEFAULT_TARGET_WORDS = 60000
DEFAULT_WORDS_PER_CHAPTER = 2500
TENSION_WAVE = (0, 1, 0, -1)
ROLE_ORDER = ("foil", "mentor", "ally", "pressure", "comic", "wildcard")

CHECK_NAMES = (
    "shape_run",
    "secondary_debut",
    "background_threat",
    "protagonist_resolution",
    "tension_curve",
)


def _clamp(value: int, low: int = 1, high: int = 5) -> int:
    return max(low, min(high, value))


def _slug(text: str, limit: int = 30) -> str:
    """A lowercase id, trimmed at a word boundary so it does not end mid-word."""
    slug = re.sub(r"[^a-z0-9]+", "-", str(text).casefold()).strip("-")
    if len(slug) <= limit:
        return slug
    cut = slug[:limit]
    if "-" in cut:
        cut = cut.rsplit("-", 1)[0]
    return cut.strip("-") or slug[:limit].strip("-")


# --------------------------------------------------------------------------- table picks


def _table_values(tables: Any, name: str, *, seed: int, key: str) -> list[str]:
    values = [entry.value for entry in tables.table(name).entries]
    rng = random.Random(seed_int(seed, STAGE_DIR, key))
    rng.shuffle(values)
    return values


def _with_first(values: Sequence[str], first: str | None) -> list[str]:
    """Keep the stage's rolled value as the first entry; later picks stay shuffled."""
    ordered = list(values)
    if first and first in ordered:
        ordered = [first] + [value for value in ordered if value != first]
    return ordered or [str(first or "chapter")]


# --------------------------------------------------------------------------- outline


def _secondaries(cast: Any) -> list[Any]:
    def order(character: Any) -> tuple[int, str]:
        try:
            rank = ROLE_ORDER.index(character.role)
        except ValueError:
            rank = len(ROLE_ORDER)
        return rank, character.id

    return sorted((character for character in cast.characters if character.role != "protagonist"), key=order)


def _target_words(concept: Mapping[str, Any], notes: list[str]) -> int:
    raw = concept.get("target_words", DEFAULT_TARGET_WORDS)
    if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
        notes.append(f"target_words {raw!r} is not a positive integer; used {DEFAULT_TARGET_WORDS}")
        return DEFAULT_TARGET_WORDS
    return raw


def _monotonic(values: Sequence[int]) -> str | None:
    if len(values) < 2:
        return None
    if all(left <= right for left, right in zip(values, values[1:])):
        return "up"
    if all(left >= right for left, right in zip(values, values[1:])):
        return "down"
    return None


def _tensions(count: int, seed: int) -> list[int]:
    """A rising-then-falling curve with a wave, forced to have both a rise and a fall."""
    rng = random.Random(seed_int(seed, STAGE_DIR, "tension_curve"))
    values: list[int] = []
    for index in range(count):
        position = index / max(1, count - 1)
        if position < ACT_PROPORTIONS[0]:
            base = 2
        elif position < ACT_PROPORTIONS[0] + ACT_PROPORTIONS[1]:
            base = 3
        else:
            base = 4
        jitter = rng.choice((-1, 0, 0, 1))
        values.append(_clamp(base + TENSION_WAVE[index % len(TENSION_WAVE)] + jitter))

    direction = _monotonic(values)
    if direction is not None:
        values[-1] = 1 if direction == "up" else 5
    if _monotonic(values) is not None:
        middle = len(values) // 2
        values[middle] = 1 if values[middle] > 1 else 5
    return values


def _title(imagery_head: str, shape: str, complication: str | None) -> str:
    tail = complication or shape.split(",")[0]
    text = f"{imagery_head[:1].upper()}{imagery_head[1:]}, {tail.strip()}"
    return re.sub(r"\s+", " ", text).strip()[:90]


def _beats(
    number: int,
    protagonist: Any,
    secondary: Any | None,
    threat: str,
    imagery_head: str,
    complication: str | None,
) -> list[dict[str, Any]]:
    actor = secondary if secondary is not None else protagonist
    beats = [
        {
            "id": f"ch{number:02d}-b1",
            "kind": "setup",
            "who_acts": actor.id,
            "text": (
                f"{actor.name} opens inside {imagery_head}, and the ordinary task of the day "
                "does not go to plan"
            ),
        },
        {
            "id": f"ch{number:02d}-b2",
            "kind": "complication",
            "who_acts": actor.id,
            "text": (
                f"{actor.name} draws a card she did not choose: {complication}"
                if complication
                else f"{actor.name} is asked for something she does not have"
            ),
        },
        {
            "id": f"ch{number:02d}-b3",
            "kind": "reversal",
            "who_acts": protagonist.id,
            "text": (
                f"{protagonist.name} learns the price was quoted wrong, and the fix is not hers to make"
            ),
        },
        {
            "id": f"ch{number:02d}-b4",
            "kind": "resolution",
            "who_acts": protagonist.id,
            "text": f"{protagonist.name} chooses in public and pays what the choice costs",
        },
    ]
    if number % 2 == 0:
        beats.append(
            {
                "id": f"ch{number:02d}-b5",
                "kind": "threat",
                "who_acts": actor.id,
                "text": f"{threat} reaches {imagery_head}, and {actor.name} feels it first",
            }
        )
    return beats


def build_outline(
    concept: Mapping[str, Any],
    cast: Any,
    rules: Mapping[str, Any],
    rolls: Sequence[Any],
    tables: Any,
    *,
    seed: int,
    targets: craft_targets.Targets | None = None,
    notes: list[str] | None = None,
) -> tuple[dict[str, Any], "OutlineReport"]:
    """Build the deterministic outline and run the five validators over it."""
    notes = notes if notes is not None else []
    rolled = {getattr(roll, "key", ""): getattr(roll, "value", "") for roll in rolls}

    title = str(concept.get("working_title") or "").strip() or "Untitled"
    target_words = _target_words(concept, notes)
    words_per_chapter, sampled = craft_targets.sample(
        targets,
        "chapters.words",
        seed=seed,
        stage=STAGE_DIR,
        key="words_per_chapter",
        default=DEFAULT_WORDS_PER_CHAPTER,
    )
    words_per_chapter = max(1, int(words_per_chapter))
    if not sampled:
        notes.append(
            "craft_targets.json has no chapters.words range; used "
            f"{DEFAULT_WORDS_PER_CHAPTER} words per chapter"
        )

    secondaries = _secondaries(cast)
    count = max(
        MIN_CHAPTERS,
        math.ceil(target_words / words_per_chapter),
        len(secondaries) + 2,
    )

    shapes = _with_first(
        _table_values(tables, "chapter_shapes", seed=seed, key="shape_order"),
        rolled.get("chapter_shape"),
    )
    imagery = _with_first(
        _table_values(tables, "imagery_domains", seed=seed, key="imagery_order"),
        rolled.get("imagery_domain"),
    )
    complications = _with_first(
        _table_values(tables, "complications", seed=seed, key="complication_order"),
        rolled.get("complication"),
    )

    tone = concept.get("tone_dial", 1)
    try:
        tone = int(tone)
    except (TypeError, ValueError):
        tone = 1
    pressure = TONE_PRESSURE.get(tone, TONE_PRESSURE[1])
    threat = f"the pressure of {pressure}"

    protagonist = next(
        (character for character in cast.characters if character.role == "protagonist"),
        cast.characters[0],
    )
    tensions = _tensions(count, seed)

    chapters: list[dict[str, Any]] = []
    complication_index = 0
    for index in range(count):
        number = index + 1
        position = index / max(1, count - 1)
        if position < ACT_PROPORTIONS[0]:
            act = 1
        elif position < ACT_PROPORTIONS[0] + ACT_PROPORTIONS[1]:
            act = 2
        else:
            act = 3

        secondary = secondaries[(number - 2) % len(secondaries)] if secondaries and number >= 2 else None
        complication = None
        if number % 3 == 0:
            complication = complications[complication_index % len(complications)]
            complication_index += 1

        imagery_value = imagery[index % len(imagery)]
        imagery_head = imagery_value.split(":", 1)[0].strip()
        tension = tensions[index]
        chapters.append(
            {
                "number": number,
                "title": _title(imagery_head, shapes[index % len(shapes)], complication),
                "act": act,
                "shape": shapes[index % len(shapes)],
                "imagery": imagery_value,
                "tension": tension,
                "words": words_per_chapter,
                "complication": complication,
                "illustration": (
                    {
                        "slot": f"ch{number:02d}-scene-1",
                        "status": "optional",
                        "focus": imagery_head,
                    }
                    if tension >= 4
                    else None
                ),
                "beats": _beats(number, protagonist, secondary, threat, imagery_head, complication),
            }
        )

    outline = {
        "title": title,
        "target_words": target_words,
        "words_per_chapter": words_per_chapter,
        "background_threat": threat,
        "act_proportions": list(ACT_PROPORTIONS),
        "craft_targets": {
            "path": str(targets.path) if targets is not None else None,
            "words_per_chapter": words_per_chapter,
            "sampled": sampled,
        },
        "chapters": chapters,
    }
    return outline, validate_outline(outline, cast)


# --------------------------------------------------------------------------- validators


@dataclass
class OutlineReport:
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    checks: dict[str, bool] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checks": dict(self.checks),
            "errors": list(self.errors),
            "notes": list(self.notes),
        }


def validate_outline(outline: Mapping[str, Any], cast: Any) -> OutlineReport:
    report = OutlineReport()
    chapters = [chapter for chapter in (outline.get("chapters") or []) if isinstance(chapter, Mapping)]
    if not chapters:
        report.errors.append("the outline has no chapters")
        report.checks = {name: False for name in CHECK_NAMES}
        return report

    _check_shapes(chapters, report)
    _check_debuts(chapters, cast, report)
    _check_threat(chapters, report)
    _check_protagonist(chapters, cast, report)
    _check_tension(chapters, report)
    return report


def _check_shapes(chapters: Sequence[Mapping[str, Any]], report: OutlineReport) -> None:
    errors: list[str] = []
    run_start = 0
    for index in range(1, len(chapters) + 1):
        if index < len(chapters) and chapters[index].get("shape") == chapters[run_start].get("shape"):
            continue
        length = index - run_start
        if length > MAX_SHAPE_RUN:
            first = chapters[run_start].get("number")
            last = chapters[index - 1].get("number")
            errors.append(
                f"chapters {first}-{last} all use the shape {chapters[run_start].get('shape')!r} "
                f"(max {MAX_SHAPE_RUN} in a row)"
            )
        run_start = index
    report.checks["shape_run"] = not errors
    report.errors.extend(errors)


def _check_debuts(chapters: Sequence[Mapping[str, Any]], cast: Any, report: OutlineReport) -> None:
    errors: list[str] = []
    firsts: dict[str, int] = {}
    for chapter in chapters:
        number = chapter.get("number")
        if not isinstance(number, int):
            continue
        for beat in chapter.get("beats") or []:
            actor = beat.get("who_acts")
            if actor and (actor not in firsts or number < firsts[actor]):
                firsts[actor] = number

    secondaries = [character.id for character in cast.characters if character.role != "protagonist"]
    missing = [entity for entity in secondaries if entity not in firsts]
    if missing:
        errors.append(f"secondary characters never appear: {', '.join(missing)}")

    by_chapter: dict[int, list[str]] = {}
    for entity in secondaries:
        chapter_number = firsts.get(entity)
        if chapter_number is not None:
            by_chapter.setdefault(chapter_number, []).append(entity)
    for chapter_number, ids in sorted(by_chapter.items()):
        if len(ids) > 1:
            errors.append(
                f"secondary characters debut in the same chapter "
                f"(chapter {chapter_number}: {', '.join(ids)})"
            )

    report.checks["secondary_debut"] = not errors
    report.errors.extend(errors)


def _check_threat(chapters: Sequence[Mapping[str, Any]], report: OutlineReport) -> None:
    present = [
        chapter
        for chapter in chapters
        if any(beat.get("kind") == "threat" for beat in chapter.get("beats") or [])
    ]
    share = len(present) / len(chapters)
    errors: list[str] = []
    if share + 1e-9 < THREAT_SHARE:
        errors.append(
            f"the background threat appears in {len(present)} of {len(chapters)} chapters "
            f"({share:.0%} < 40%)"
        )
    report.checks["background_threat"] = not errors
    report.errors.extend(errors)


def _check_protagonist(
    chapters: Sequence[Mapping[str, Any]], cast: Any, report: OutlineReport
) -> None:
    protagonist = next(
        (character.id for character in cast.characters if character.role == "protagonist"), None
    )
    resolutions = [
        beat
        for chapter in chapters
        for beat in chapter.get("beats") or []
        if beat.get("kind") == "resolution"
    ]
    errors: list[str] = []
    if protagonist is None:
        errors.append("the cast has no protagonist")
    elif not resolutions:
        errors.append("the outline has no resolution beats")
    else:
        share = sum(1 for beat in resolutions if beat.get("who_acts") == protagonist) / len(resolutions)
        if share + 1e-9 < PROTAGONIST_SHARE:
            errors.append(
                f"the protagonist acts in {share:.0%} of resolution beats (< 70%)"
            )
    report.checks["protagonist_resolution"] = not errors
    report.errors.extend(errors)


def _check_tension(chapters: Sequence[Mapping[str, Any]], report: OutlineReport) -> None:
    values = [chapter.get("tension") for chapter in chapters]
    errors: list[str] = []
    if any(isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5 for value in values):
        errors.append("every chapter needs a tension from 1 to 5")
    else:
        direction = _monotonic(values)
        if direction is not None:
            errors.append(
                f"the tension curve only goes {'up' if direction == 'up' else 'down'} "
                "(monotonic); vary it"
            )
    report.checks["tension_curve"] = not errors
    report.errors.extend(errors)


# --------------------------------------------------------------------------- rules additions


def build_rules_additions(outline: Mapping[str, Any], rules: Mapping[str, Any]) -> dict[str, Any]:
    """Additive rules proposed by the outline; `story rules merge` validates and merges them."""
    base_items = rules.get("items") or {}
    base_locations = rules.get("locations") or {}
    start = str(rules.get("start_location") or next(iter(base_locations), ""))

    ingredients: dict[str, int] = {"witness-statement": 1}
    for candidate in ("sealed-ledger", "ledger"):
        if candidate in base_items:
            ingredients[candidate] = 1
            break

    additions: dict[str, Any] = {
        "items": {
            "witness-statement": {"name": "a witness statement", "sources": []},
            "chapter-dossier": {"name": "the chapter dossier", "sources": ["recipe:bind-the-dossier"]},
        },
        "recipes": [
            {
                "id": "bind-the-dossier",
                "produces": "chapter-dossier",
                "ingredients": ingredients,
                "requires_skill": None,
                "minutes": 45,
            }
        ],
        "skills": {},
        "locations": {},
    }

    known_skills = sorted(rules.get("skills") or {})
    if known_skills:
        base_skill = known_skills[0]
        additions["skills"][f"{_slug(base_skill, 26)}-under-pressure"] = {
            "name": f"{base_skill}, under pressure",
            "unlocks_at_level": 3,
            "requires": [base_skill],
            "requires_items": [],
        }
    else:
        additions["skills"]["pressure-reading"] = {
            "name": "pressure reading",
            "unlocks_at_level": 2,
            "requires": [],
            "requires_items": [],
        }

    seen = set(base_locations)
    for chapter in outline.get("chapters") or []:
        imagery = str(chapter.get("imagery") or "")
        head = imagery.split(":", 1)[0].strip()
        location_id = f"the-{_slug(head, 26)}" if head else ""
        if not location_id or location_id in seen:
            continue
        exits = {start: {"minutes": 20}} if start and start in base_locations else {}
        additions["locations"][location_id] = {"name": f"The {head}", "exits": exits}
        seen.add(location_id)
        if len(additions["locations"]) >= 2:
            break

    return additions


# --------------------------------------------------------------------------- rendering


def render_outline(
    outline: Mapping[str, Any],
    report: OutlineReport,
    notes: Sequence[str] = (),
    model_text: str = "",
) -> str:
    chapters = outline.get("chapters") or []
    lines = [
        f"# Outline - {outline.get('title') or 'Untitled'}",
        "",
        "## Summary",
        "",
        f"- chapters: {len(chapters)}",
        f"- target: {outline.get('target_words')} words at {outline.get('words_per_chapter')} per chapter",
        f"- act proportions: {', '.join(f'{share:.0%}' for share in outline.get('act_proportions') or [])}",
        f"- background threat: {outline.get('background_threat')}",
        f"- craft targets: {outline.get('craft_targets', {}).get('path') or 'none (defaults used)'}",
        "",
        "## Validators",
        "",
        f"- status: {'passed' if report.ok else 'failed'}",
    ]
    for name, passed in report.checks.items():
        lines.append(f"- {name}: {'pass' if passed else 'FAIL'}")
    for error in report.errors:
        lines.append(f"- error: {error}")

    lines += ["", "## Chapters", ""]
    for chapter in chapters:
        lines.append(
            f"### {chapter.get('number')}. {chapter.get('title')} - tension "
            f"{chapter.get('tension')}, act {chapter.get('act')}"
        )
        lines.append(f"- shape: {chapter.get('shape')}")
        lines.append(f"- imagery: {chapter.get('imagery')}")
        lines.append(f"- words: {chapter.get('words')}")
        lines.append(f"- complication: {chapter.get('complication') or 'none this chapter'}")
        illustration = chapter.get("illustration")
        lines.append(
            f"- illustration: {illustration['slot']} (optional)"
            if illustration
            else "- illustration: none"
        )
        lines.append("- beats:")
        for beat in chapter.get("beats") or []:
            lines.append(
                f"  - {beat.get('id')} ({beat.get('kind')}, {beat.get('who_acts')}): {beat.get('text')}"
            )
        lines.append("")

    lines += [
        "## Rules additions",
        "",
        "- `rules_additions.json` proposes new items, one recipe, a skill and locations.",
        "- review and merge them with `story rules merge` (additive, never overwrites an entry).",
    ]

    if notes:
        lines += ["", "## Notes", ""]
        lines.extend(f"- {note}" for note in notes)
    if model_text.strip():
        lines += ["", "## Planner notes", "", model_text.strip()]
    return "\n".join(lines).rstrip() + "\n"


def outline_prompt(
    skill: Any,
    concept: Mapping[str, Any],
    outline: Mapping[str, Any],
    report: OutlineReport,
    upstream: str,
    notes: Sequence[str],
) -> str:
    sections = "\n\n".join(f"## {name}\n\n{text}" for name, text in skill.sections.items())
    chapter_lines = "\n".join(
        f"- {chapter.get('number')}: {chapter.get('title')} | tension {chapter.get('tension')} | "
        f"shape {chapter.get('shape')}"
        for chapter in (outline.get("chapters") or [])[:12]
    )
    note_text = "\n".join(f"- {note}" for note in notes) or "- none"
    return (
        f"{sections}\n\n"
        "## This project\n\n"
        f"```yaml\n{yaml.safe_dump(dict(concept), sort_keys=False)}```\n\n"
        "## The outline fixed by code\n"
        f"- chapters: {len(outline.get('chapters') or [])}\n"
        f"- background threat: {outline.get('background_threat')}\n"
        f"- validator status: {'passed' if report.ok else 'failed'}\n"
        f"- first chapters:\n{chapter_lines or '(none)'}\n\n"
        "Earlier stage outputs:\n"
        f"{upstream.strip() or '(none yet)'}\n\n"
        "Notes:\n"
        f"{note_text}\n\n"
        "Reply with prose notes about the shape of the book and what each act has to deliver. "
        "Do not propose different numbers, shapes or actors; the outline above is fixed.\n"
    )
