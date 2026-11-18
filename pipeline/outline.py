"""Stage 11: the outline, authored by the model inside code-assigned constraints.

The randomizer and the code decide the skeleton: the chapter count, the act, the shape, the
imagery domain, the tension, the actor whose debut the chapter carries, the complication
card, the threat schedule and the illustration slot. The planner model writes each chapter's
`title`, `hook`, beats (`actor`, `action`, `obstacle`, `outcome`) and `ends_on` as strict
JSON: one call per chapter, seeing summaries of the chapters before it.

A chapter reply is checked for its schema, for real cast ids, one actor per beat, at least
three beats, non-empty text, no banned phrase and no repeated or near-repeated beat text.
Invalid replies are retried up to three times with the errors fed back; a chapter that is
still invalid fails the stage. There is no template fallback: the deterministic skeleton is
only built when `skeleton=True` (`story run outline --skeleton`), which tests use.

Validators (BUILD_SPEC.md section 5, stage 11):

* no more than two consecutive chapters share one shape
* every secondary character first appears in a different chapter (and appears at all)
* the background threat reaches at least 40% of chapters
* the protagonist acts in at least 70% of resolution beats
* the tension curve is not monotonic
"""

from __future__ import annotations

import json
import math
import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from . import craft_targets, ledger, model_json
from .early_stages import TONE_PRESSURE
from .randomizer import seed_int

STAGE_DIR = "11-outline"
STAGE11_NUMBER = 11
ACT_PROPORTIONS = (0.25, 0.5, 0.25)
MIN_CHAPTERS = 8
MAX_SHAPE_RUN = 2
THREAT_SHARE = 0.4
PROTAGONIST_SHARE = 0.7
MIN_BEATS = 3
DEFAULT_TARGET_WORDS = 60000
DEFAULT_WORDS_PER_CHAPTER = 2500
TENSION_WAVE = (0, 1, 0, -1)
ROLE_ORDER = ("foil", "mentor", "ally", "pressure", "comic", "wildcard")

CHAPTER_KEYS = frozenset({"title", "hook", "beats", "ends_on"})
BEAT_KEYS = frozenset({"actor", "action", "obstacle", "outcome"})

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


# --------------------------------------------------------------------------- outline skeleton


def _secondaries(cast: Any) -> list[Any]:
    def order(character: Any) -> tuple[int, str]:
        try:
            rank = ROLE_ORDER.index(character.role)
        except ValueError:
            rank = len(ROLE_ORDER)
        return rank, character.id

    return sorted((character for character in cast.characters if character.role != "protagonist"), key=order)


def _protagonist(cast: Any) -> Any:
    return next(
        (character for character in cast.characters if character.role == "protagonist"),
        cast.characters[0],
    )


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


def _assign_closing_actors(
    chapters: Sequence[dict[str, Any]],
    secondaries: Sequence[Any],
    protagonist: str,
    seed: int,
) -> dict[int, str]:
    """The seeded closing actor for every chapter.

    The protagonist closes at least 70% of chapters (so the resolution validator holds by
    construction); the rest close on a secondary who has already debuted. Chapter 1 always
    closes on the protagonist. The RNG is derived from the run seed and the stage name, so
    a resumed or repeated run assigns exactly the same actors.
    """
    count = len(chapters)
    assignment = {chapter["number"]: protagonist for chapter in chapters}
    if count < 2 or not secondaries:
        return assignment

    protagonist_minimum = math.ceil(count * PROTAGONIST_SHARE)
    max_others = min(count - 1, count - protagonist_minimum)
    if max_others < 1:
        return assignment

    rng = random.Random(seed_int(seed, STAGE_DIR, "closing_actors"))
    candidates = list(range(2, count + 1))
    chosen = sorted(rng.sample(candidates, k=rng.randint(1, max_others)))

    debut: dict[str, int] = {}
    for chapter in chapters:
        actor = str(chapter.get("actor"))
        if actor != protagonist:
            debut.setdefault(actor, chapter["number"])
    ordered = [actor for actor, _ in sorted(debut.items(), key=lambda item: (item[1], item[0]))]

    for number in chosen:
        chapter = chapters[number - 1]
        actor = str(chapter.get("actor"))
        if actor != protagonist:
            assignment[number] = actor
        else:
            debuted = [
                candidate
                for candidate in ordered
                if debut.get(candidate, 0) <= number
            ]
            if debuted:
                assignment[number] = debuted[number % len(debuted)]
    return assignment


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


# --------------------------------------------------------------------------- prompts


def _stage_excerpt(upstream: str, name: str, limit: int = 1200) -> str:
    marker = f"### {name}"
    start = upstream.find(marker)
    if start < 0:
        return ""
    body = upstream[start + len(marker) :]
    end = body.find("\n### ")
    if end >= 0:
        body = body[:end]
    return re.sub(r"\n{3,}", "\n\n", body).strip()[:limit]


def _theme_text(upstream: str) -> str:
    parts = [
        _stage_excerpt(upstream, "05-premise_inversion"),
        _stage_excerpt(upstream, "06-theme_premise"),
    ]
    return "\n\n".join(part for part in parts if part).strip()


def _cast_summary(cast: Any) -> str:
    lines: list[str] = []
    for character in cast.characters:
        data = character.to_dict()
        core = data.get("emotional_core") or {}
        want = str(core.get("want") or "").strip()
        line = f"- {character.id} ({character.role}): {character.name}"
        if want:
            line += f"; wants {want}"
        lines.append(line)
    return "\n".join(lines)


def _rules_summary(rules: Mapping[str, Any]) -> str:
    xp = rules.get("xp") or {}
    skills = sorted(rules.get("skills") or {})
    items = sorted(rules.get("items") or {})
    locations = sorted(rules.get("locations") or {})
    return "\n".join(
        [
            f"- system: {rules.get('system_type')}",
            f"- max level: {xp.get('max_level')}",
            f"- start location: {rules.get('start_location')}",
            f"- skills: {', '.join(skills) or '(none)'}",
            f"- items: {', '.join(items) or '(none)'}",
            f"- locations: {', '.join(locations) or '(none)'}",
        ]
    )


def _previous_summary(previous: Sequence[Mapping[str, Any]]) -> str:
    if not previous:
        return "- none; this is the first chapter"
    lines = []
    for chapter in previous:
        title = str(chapter.get("title") or f"chapter {chapter.get('number')}")[:120]
        hook = str(chapter.get("hook") or "")[:160]
        ends_on = str(chapter.get("ends_on") or "")[:160]
        lines.append(f"- ch{chapter.get('number')}: {title} | hook: {hook} | ends: {ends_on}")
    return "\n".join(lines)


def chapter_prompt(
    skill: Any,
    concept: Mapping[str, Any],
    cast: Any,
    rules: Mapping[str, Any],
    theme: str,
    chapter: Mapping[str, Any],
    previous: Sequence[Mapping[str, Any]],
    allowed: Sequence[str],
    protagonist: str,
    banned: Sequence[str],
    feedback: Sequence[str] = (),
) -> str:
    """One chapter's planner prompt: fixed constraints, then the strict reply shape."""
    constraint = {
        "number": chapter.get("number"),
        "shape": chapter.get("shape"),
        "tension": chapter.get("tension"),
        "actor": chapter.get("actor"),
        "protagonist": protagonist,
        "allowed_actors": list(allowed),
        "imagery": chapter.get("imagery"),
        "complication": chapter.get("complication"),
        "illustration": bool(chapter.get("illustration")),
        "threat": bool(chapter.get("threat")),
        "closing_actor": chapter.get("closing_actor"),
        "words": chapter.get("words"),
    }
    reply_shape = {
        "title": "the chapter's title",
        "hook": "what pulls the reader into the chapter",
        "beats": [
            {
                "actor": "one cast id",
                "action": "what the actor does",
                "obstacle": "what stands in the way",
                "outcome": "what the action changes",
            }
        ],
        "ends_on": "the image or decision the chapter closes on",
    }
    banned_text = ", ".join(f'"{phrase}"' for phrase in banned) or "(none)"
    sections = "\n\n".join(
        f"## {name}\n\n{skill.sections[name]}" for name in ("Purpose", "Steps", "Do not")
    )
    lines = [
        sections,
        "",
        "## This project",
        "",
        "```yaml",
        yaml.safe_dump(dict(concept), sort_keys=False).rstrip(),
        "```",
        "",
        "## Theme and premise",
        "",
        theme or "- not written yet; keep the concept's premise_seed in view",
        "",
        "## Cast",
        "",
        _cast_summary(cast),
        "",
        "## Rules summary",
        "",
        _rules_summary(rules),
        "",
        "## Chapter constraints",
        "",
        "These are fixed. Do not change the shape, the tension, the actor schedule or the",
        "imagery; write the chapter inside them.",
        "",
        "```json",
        json.dumps(constraint, indent=2),
        "```",
        "",
        "## Previous chapters",
        "",
        _previous_summary(previous),
        "",
        "## Your reply",
        "",
        "Reply with one JSON object and nothing else:",
        "",
        "```json",
        json.dumps(reply_shape, indent=2),
        "```",
        "",
        f"- at least {MIN_BEATS} beats; every beat names exactly one actor from `allowed_actors`",
        (
            "- the last beat is acted by the assigned closing actor "
            f"({chapter.get('closing_actor')})"
        ),
        "- `actor` is a cast id, never a name",
        "- no beat may repeat or nearly repeat a beat from an earlier chapter",
        f"- never use these phrases: {banned_text}",
    ]
    if feedback:
        lines += [
            "",
            "## Your previous reply was rejected",
            "",
            *[f"- {error}" for error in feedback],
            "",
            "Fix every error above and reply again with one JSON object.",
        ]
    return "\n".join(lines).rstrip() + "\n"


# --------------------------------------------------------------------------- chapter checks


def _chapter_checks(
    payload: Any,
    *,
    chapter: Mapping[str, Any],
    cast_ids: set[str],
    allowed: Sequence[str],
    protagonist: str,
    closing_actor: str,
    banned: Sequence[str],
    seen: Sequence[str],
) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, Mapping):
        return ["the reply must be a JSON object"]

    missing = CHAPTER_KEYS - set(payload)
    extra = set(payload) - CHAPTER_KEYS
    if missing:
        errors.append(f"missing keys: {', '.join(sorted(missing))}")
    if extra:
        errors.append(f"unexpected keys: {', '.join(sorted(extra))}")

    for key in ("title", "hook", "ends_on"):
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{key} must be a non-empty string")

    beats = payload.get("beats")
    if not isinstance(beats, list):
        errors.append(f"beats must be a list of at least {MIN_BEATS} beats")
        beats = []
    elif len(beats) < MIN_BEATS:
        errors.append(f"beats must have at least {MIN_BEATS} beats (got {len(beats)})")

    texts: list[str] = []
    chapter_texts: list[str] = []
    for index, beat in enumerate(beats, 1):
        if not isinstance(beat, Mapping):
            errors.append(f"beat {index} must be an object")
            continue
        missing_beat = BEAT_KEYS - set(beat)
        extra_beat = set(beat) - BEAT_KEYS
        if missing_beat:
            errors.append(f"beat {index} is missing: {', '.join(sorted(missing_beat))}")
        if extra_beat:
            errors.append(f"beat {index} has unexpected keys: {', '.join(sorted(extra_beat))}")

        actor = beat.get("actor")
        if not isinstance(actor, str) or not actor.strip():
            errors.append(f"beat {index} needs an actor")
        elif actor not in cast_ids:
            errors.append(f"beat {index} actor {actor!r} is not a cast id")
        elif actor not in allowed:
            errors.append(
                f"beat {index} actor {actor!r} has not appeared yet "
                f"(allowed: {', '.join(allowed)})"
            )

        parts: list[str] = []
        for key in ("action", "obstacle", "outcome"):
            value = beat.get(key)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"beat {index} {key} must be a non-empty string")
            else:
                parts.append(value.strip())
        combined = " ".join(parts).strip()
        if combined:
            earlier = list(seen) + chapter_texts
            if model_json.is_near_duplicate(combined, earlier):
                errors.append(f"beat {index} repeats an earlier beat (near-duplicate)")
            chapter_texts.append(combined)
            texts.append(combined)

    closing = beats[-1].get("actor") if beats and isinstance(beats[-1], Mapping) else None
    if closing != closing_actor:
        errors.append(
            f"the closing beat must be acted by the assigned closing actor ({closing_actor})"
        )

    for phrase in model_json.banned_hits(
        [str(payload.get(key) or "") for key in ("title", "hook", "ends_on")] + texts, banned
    ):
        errors.append(f"banned phrase: {phrase!r}")

    return errors


def _clean_fields(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Only the model-owned fields, stripped, in a stable order."""
    return {
        "title": str(payload["title"]).strip(),
        "hook": str(payload["hook"]).strip(),
        "ends_on": str(payload["ends_on"]).strip(),
        "beats": [
            {
                "actor": str(beat["actor"]).strip(),
                "action": str(beat["action"]).strip(),
                "obstacle": str(beat["obstacle"]).strip(),
                "outcome": str(beat["outcome"]).strip(),
            }
            for beat in payload["beats"]
        ],
    }


def author_chapter(
    chapter: Mapping[str, Any],
    *,
    cast: Any,
    concept: Mapping[str, Any],
    rules: Mapping[str, Any],
    skill: Any,
    llm: Any,
    theme: str,
    previous: Sequence[Mapping[str, Any]],
    allowed: Sequence[str],
    protagonist: str,
    closing_actor: str,
    banned: Sequence[str],
    seen: Sequence[str],
) -> tuple[dict[str, Any] | None, int, list[str]]:
    """Ask for one chapter until it validates, with the errors fed back each attempt."""
    cast_ids = {character.id for character in cast.characters}

    def prompt_for(feedback: Sequence[str]) -> str:
        return chapter_prompt(
            skill, concept, cast, rules, theme, chapter, previous, allowed, protagonist, banned, feedback
        )

    def validate(payload: Any) -> list[str]:
        return _chapter_checks(
            payload,
            chapter=chapter,
            cast_ids=cast_ids,
            allowed=allowed,
            protagonist=protagonist,
            closing_actor=closing_actor,
            banned=banned,
            seen=seen,
        )

    payload, attempts, errors = model_json.request_json(
        llm,
        prompt_for,
        validate,
        system=skill.sections["Purpose"],
        model_tier=skill.model_tier,
        max_tokens=1500,
    )
    if payload is None:
        return None, attempts, errors
    return _clean_fields(payload), attempts, []


def _annotate_beats(chapter: dict[str, Any]) -> None:
    """Beat ids and kinds are structure, not model text: setup, middles, resolution."""
    beats = chapter.get("beats") or []
    number = chapter.get("number")
    for index, beat in enumerate(beats, 1):
        beat["id"] = f"ch{number:02d}-b{index}"
        if index == 1:
            beat["kind"] = "setup"
        elif index == len(beats):
            beat["kind"] = "resolution"
        else:
            beat["kind"] = "complication"


def _fill_skeleton(
    chapter: dict[str, Any],
    *,
    protagonist: Any,
    cast_by_id: Mapping[str, Any],
    threat: str,
) -> None:
    """The deterministic chapter used by tests: template beats, never a fallback in a run."""
    number = chapter["number"]
    actor = cast_by_id.get(str(chapter.get("actor")), protagonist)
    closing = cast_by_id.get(str(chapter.get("closing_actor") or ""), protagonist)
    imagery = str(chapter.get("imagery") or "").split(":", 1)[0].strip() or "the setting"
    shape = str(chapter.get("shape") or "the chapter shape")
    complication = chapter.get("complication")

    chapter["title"] = _title(imagery, shape, complication)
    chapter["hook"] = f"{actor.name} starts the day on {imagery}, and the count is already wrong."
    beats = [
        {
            "id": f"ch{number:02d}-b1",
            "kind": "setup",
            "actor": actor.id,
            "action": f"{actor.name} opens inside {imagery}",
            "obstacle": "the ordinary task of the day does not go to plan",
            "outcome": "the plan is already behind",
        },
        {
            "id": f"ch{number:02d}-b2",
            "kind": "complication",
            "actor": actor.id,
            "action": (
                f"{actor.name} draws a card she did not choose: {complication}"
                if complication
                else f"{actor.name} is asked for something she does not have"
            ),
            "obstacle": complication or "the ask is not hers to meet",
            "outcome": "she owes an answer she cannot price",
        },
        {
            "id": f"ch{number:02d}-b3",
            "kind": "reversal",
            "actor": protagonist.id,
            "action": f"{protagonist.name} learns the price was quoted wrong",
            "obstacle": "the fix is not hers to make",
            "outcome": "the debt moves to someone else",
        },
        {
            "id": f"ch{number:02d}-b4",
            "kind": "resolution",
            "actor": closing.id,
            "action": f"{closing.name} chooses in public",
            "obstacle": "the choice costs what she cannot spare",
            "outcome": "she pays it and keeps the record",
        },
    ]
    if chapter.get("threat"):
        beats.append(
            {
                "id": f"ch{number:02d}-b5",
                "kind": "threat",
                "actor": actor.id,
                "action": f"{threat} reaches {imagery}",
                "obstacle": f"{actor.name} feels it first",
                "outcome": "the threat is no longer background",
            }
        )
    chapter["beats"] = beats
    chapter["ends_on"] = (
        f"{closing.name} ends chapter {number} with {shape.split(',')[0].strip()} "
        "settled only in public."
    )


# --------------------------------------------------------------------------- build


@dataclass
class OutlineReport:
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    checks: dict[str, bool] = field(default_factory=dict)
    model: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def merge(self, other: "OutlineReport") -> None:
        self.errors.extend(other.errors)
        self.notes.extend(other.notes)
        self.checks.update(other.checks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checks": dict(self.checks),
            "errors": list(self.errors),
            "notes": list(self.notes),
        }


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
    skeleton: bool = False,
    llm: Any = None,
    skill: Any = None,
    upstream: str = "",
    banned: Sequence[str] = (),
    partial_path: str | Path | None = None,
) -> tuple[dict[str, Any], OutlineReport]:
    """Build the code constraints, let the model write each chapter, then run the validators.

    Each validated chapter is saved to `partial_path`; a rerun reuses those chapters and
    continues from the first missing one. The partial file is deleted only when the stage
    completes (all chapters authored and every validator passing).
    """
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

    protagonist = _protagonist(cast)
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
                "title": "",
                "hook": "",
                "ends_on": "",
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
                "threat": number % 2 == 0,
                "actor": secondary.id if secondary is not None else protagonist.id,
                "beats": [],
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

    # Closing actors are a code constraint like the shape or the tension: the protagonist
    # closes at least 70% of chapters, the seeded randomizer picks the rest.
    closing_actors = _assign_closing_actors(chapters, secondaries, protagonist.id, seed)
    for chapter in chapters:
        chapter["closing_actor"] = closing_actors[chapter["number"]]

    report = OutlineReport()
    report.model = {
        "mode": "skeleton" if skeleton else "model",
        "calls": 0,
        "attempts": 0,
        "resumed": 0,
    }

    if skeleton:
        notes.append("skeleton used: the outline is deterministic and the model was not called")
        cast_by_id = {character.id: character for character in cast.characters}
        for chapter in chapters:
            _fill_skeleton(chapter, protagonist=protagonist, cast_by_id=cast_by_id, threat=threat)
        report.merge(validate_outline(outline, cast))
        if report.ok and partial_path is not None:
            Path(partial_path).unlink(missing_ok=True)
        return outline, report

    if llm is None or skill is None:
        report.errors.append("stage 11 is model-authored, but no planner adapter was supplied")
        report.checks = {name: False for name in CHECK_NAMES}
        return outline, report

    theme = _theme_text(upstream)
    if not theme:
        notes.append("no theme/premise output yet; the prompt kept the concept's premise_seed in view")

    # A secondary may carry several chapters; its debut is the first one. Chapters are in
    # order, so setdefault keeps that first appearance.
    debut: dict[str, int] = {}
    for chapter in chapters:
        actor = str(chapter.get("actor"))
        if actor != protagonist.id:
            debut.setdefault(actor, chapter["number"])
    stored = model_json.load_partial(partial_path, notes)
    authored: dict[int, dict[str, Any]] = {}
    cast_ids = {character.id for character in cast.characters}
    seen: list[str] = []
    previous: list[dict[str, Any]] = []
    authoring_failed = False
    for chapter in chapters:
        allowed = [protagonist.id] + sorted(
            (actor for actor, number in debut.items() if number <= chapter["number"]),
            key=lambda actor: (debut[actor], actor),
        )
        number = chapter["number"]

        fields: dict[str, Any] | None = None
        saved = stored.get(number)
        if saved is not None:
            candidate = {key: saved[key] for key in CHAPTER_KEYS if key in saved}
            errors = _chapter_checks(
                candidate,
                chapter=chapter,
                cast_ids=cast_ids,
                allowed=allowed,
                protagonist=protagonist.id,
                closing_actor=str(chapter["closing_actor"]),
                banned=banned,
                seen=seen,
            )
            if errors:
                notes.append(
                    f"partial chapter {number} no longer fits its constraints; authoring it again"
                )
            else:
                fields = _clean_fields(candidate)
                report.model["resumed"] = int(report.model["resumed"]) + 1

        if fields is None:
            fields, attempts, errors = author_chapter(
                chapter,
                cast=cast,
                concept=concept,
                rules=rules,
                skill=skill,
                llm=llm,
                theme=theme,
                previous=previous,
                allowed=allowed,
                protagonist=protagonist.id,
                closing_actor=str(chapter["closing_actor"]),
                banned=banned,
                seen=seen,
            )
            report.model["calls"] = int(report.model["calls"]) + attempts
            report.model["attempts"] = max(int(report.model.get("attempts") or 0), attempts)
            if fields is None:
                report.model["failed_chapter"] = number
                report.errors.append(f"chapter {number}: " + "; ".join(errors[:5]))
                authoring_failed = True
                break

        chapter.update(fields)
        # A copy, because _annotate_beats decorates chapter["beats"] in place.
        authored[number] = _clean_fields(fields)
        model_json.save_partial(partial_path, authored)
        _annotate_beats(chapter)
        seen.extend(
            " ".join((beat["action"], beat["obstacle"], beat["outcome"]))
            for beat in chapter["beats"]
        )
        previous.append(chapter)

    report.model["resumed"] = int(report.model.get("resumed") or 0)
    if authoring_failed:
        report.checks = {name: False for name in CHECK_NAMES}
        return outline, report

    report.model["chapters"] = len(chapters)
    report.merge(validate_outline(outline, cast))
    if report.ok and partial_path is not None:
        Path(partial_path).unlink(missing_ok=True)
    return outline, report


# --------------------------------------------------------------------------- validators


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


def _beat_actor(beat: Mapping[str, Any]) -> Any:
    return beat.get("actor") if "actor" in beat else beat.get("who_acts")


def _check_debuts(chapters: Sequence[Mapping[str, Any]], cast: Any, report: OutlineReport) -> None:
    errors: list[str] = []
    firsts: dict[str, int] = {}
    for chapter in chapters:
        number = chapter.get("number")
        if not isinstance(number, int):
            continue
        for beat in chapter.get("beats") or []:
            actor = _beat_actor(beat) if isinstance(beat, Mapping) else None
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
        if chapter.get("threat") is True
        or any(
            isinstance(beat, Mapping) and beat.get("kind") == "threat"
            for beat in chapter.get("beats") or []
        )
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


def _resolution_beats(chapter: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Beats marked resolution; for model-authored chapters, the closing beat."""
    beats = [beat for beat in chapter.get("beats") or [] if isinstance(beat, Mapping)]
    marked = [beat for beat in beats if beat.get("kind") == "resolution"]
    if marked:
        return marked
    return beats[-1:]


def _check_protagonist(
    chapters: Sequence[Mapping[str, Any]], cast: Any, report: OutlineReport
) -> None:
    protagonist = next(
        (character.id for character in cast.characters if character.role == "protagonist"), None
    )
    resolutions = [
        beat for chapter in chapters for beat in _resolution_beats(chapter)
    ]
    errors: list[str] = []
    if protagonist is None:
        errors.append("the cast has no protagonist")
    elif not resolutions:
        errors.append("the outline has no resolution beats")
    else:
        share = sum(1 for beat in resolutions if _beat_actor(beat) == protagonist) / len(resolutions)
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


def _render_beat(beat: Mapping[str, Any]) -> str:
    actor = _beat_actor(beat) or "?"
    return (
        f"  - {beat.get('id')} ({beat.get('kind')}, {actor}): "
        f"{beat.get('action')} | obstacle: {beat.get('obstacle')} | outcome: {beat.get('outcome')}"
    )


def render_outline(
    outline: Mapping[str, Any],
    report: OutlineReport,
    notes: Sequence[str] = (),
) -> str:
    chapters = outline.get("chapters") or []
    model = report.model or {}
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
        f"- chapters authored by: {model.get('mode') or 'unknown'} "
        f"({model.get('calls', 0)} model call(s), up to {model.get('attempts', 0)} attempt(s) each)",
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
            f"### {chapter.get('number')}. {chapter.get('title') or '(untitled)'} - tension "
            f"{chapter.get('tension')}, act {chapter.get('act')}"
        )
        lines.append(f"- shape: {chapter.get('shape')}")
        lines.append(f"- imagery: {chapter.get('imagery')}")
        lines.append(f"- words: {chapter.get('words')}")
        lines.append(f"- complication: {chapter.get('complication') or 'none this chapter'}")
        lines.append(f"- background threat: {'surfaces' if chapter.get('threat') else 'hums'}")
        illustration = chapter.get("illustration")
        lines.append(
            f"- illustration: {illustration['slot']} (optional)"
            if illustration
            else "- illustration: none"
        )
        lines.append(f"- hook: {chapter.get('hook') or '(not written)'}")
        lines.append("- beats:")
        beats = [beat for beat in chapter.get("beats") or [] if isinstance(beat, Mapping)]
        if beats:
            lines.extend(_render_beat(beat) for beat in beats)
        else:
            lines.append("  - (none: the chapter was not authored)")
        lines.append(f"- ends on: {chapter.get('ends_on') or '(not written)'}")
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
    return "\n".join(lines).rstrip() + "\n"
