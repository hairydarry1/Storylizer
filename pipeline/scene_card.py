"""Stage 12: scene cards, authored by the model inside the outline's constraints.

The outline fixes the chapter, its shape, its imagery, its beats and the number of scenes
(from `craft_targets.json` when present, clamped to 2-4). For each chapter the planner model
writes one JSON object holding that many scenes, each with a non-empty goal, conflict and
turn. Replies are checked for the schema, non-empty text, banned phrases, a goal that is not
just its turn, and scene text repeated elsewhere in the book; invalid replies are retried up
to three times with the errors fed back.

There is no fallback to derived cards in a run: a chapter that is still invalid fails the
stage. `skeleton=True` (`story run scene_card --skeleton`) builds the deterministic cards
instead, for tests and dry runs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import craft_targets, model_json

STAGE_DIR = "12-scene_card"
DEFAULT_SCENES = 3
MIN_SCENES = 2
MAX_SCENES = 4
SCENE_KEYS = frozenset({"goal", "conflict", "turn"})


# --------------------------------------------------------------------------- prompts


def _beat_line(beat: Mapping[str, Any], index: int) -> str:
    actor = beat.get("actor") or beat.get("who_acts") or "?"
    return (
        f"{index}. {actor}: {beat.get('action') or beat.get('text') or ''} "
        f"| obstacle: {beat.get('obstacle') or ''} | outcome: {beat.get('outcome') or ''}"
    )


def scene_prompt(
    skill: Any,
    chapter: Mapping[str, Any],
    count: int,
    banned: Sequence[str],
    feedback: Sequence[str] = (),
) -> str:
    constraint = {
        "number": chapter.get("number"),
        "title": chapter.get("title"),
        "shape": chapter.get("shape"),
        "imagery": chapter.get("imagery"),
        "complication": chapter.get("complication"),
        "threat": bool(chapter.get("threat")),
        "scenes": count,
        "beats": [
            {
                "actor": beat.get("actor") or beat.get("who_acts"),
                "action": beat.get("action") or beat.get("text"),
                "obstacle": beat.get("obstacle") or "",
                "outcome": beat.get("outcome") or "",
            }
            for beat in chapter.get("beats") or []
            if isinstance(beat, Mapping)
        ],
    }
    reply_shape = {
        "scenes": [
            {"goal": "what the scene wants", "conflict": "what stands in the way", "turn": "what changes"}
        ]
    }
    banned_text = ", ".join(f'"{phrase}"' for phrase in banned) or "(none)"
    sections = "\n\n".join(
        f"## {name}\n\n{skill.sections[name]}" for name in ("Purpose", "Steps", "Do not")
    )
    lines = [
        sections,
        "",
        "## Scene constraints",
        "",
        "These are fixed. Write exactly this many scenes; do not change the chapter.",
        "",
        "```json",
        json.dumps(constraint, indent=2),
        "```",
        "",
        "## Your reply",
        "",
        "Reply with one JSON object and nothing else:",
        "",
        "```json",
        json.dumps(reply_shape, indent=2),
        "```",
        "",
        f"- exactly {count} scenes",
        "- every scene needs a non-empty goal, conflict and turn",
        "- the turn must change something; it may not restate the goal",
        "- no scene may repeat or nearly repeat text from another scene",
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


# --------------------------------------------------------------------------- checks


def _scene_checks(
    payload: Any,
    *,
    count: int,
    banned: Sequence[str],
    seen: Sequence[str],
) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, Mapping):
        return ["the reply must be a JSON object"]

    extra = set(payload) - {"scenes"}
    if extra:
        errors.append(f"unexpected keys: {', '.join(sorted(extra))}")

    scenes = payload.get("scenes")
    if not isinstance(scenes, list):
        errors.append(f"scenes must be a list of exactly {count} scenes")
        return errors
    if len(scenes) != count:
        errors.append(f"scenes must have exactly {count} scenes (got {len(scenes)})")

    texts: list[str] = []
    chapter_texts: list[str] = []
    for index, scene in enumerate(scenes, 1):
        if not isinstance(scene, Mapping):
            errors.append(f"scene {index} must be an object")
            continue
        missing = SCENE_KEYS - set(scene)
        extra_scene = set(scene) - SCENE_KEYS
        if missing:
            errors.append(f"scene {index} is missing: {', '.join(sorted(missing))}")
        if extra_scene:
            errors.append(f"scene {index} has unexpected keys: {', '.join(sorted(extra_scene))}")

        goal = scene.get("goal")
        turn = scene.get("turn")
        parts: list[str] = []
        for key in ("goal", "conflict", "turn"):
            value = scene.get(key)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"scene {index} {key} must be a non-empty string")
            else:
                parts.append(value.strip())

        if isinstance(goal, str) and isinstance(turn, str) and goal.strip() and turn.strip():
            if model_json.normalize(goal) == model_json.normalize(turn):
                errors.append(f"scene {index} turn restates its goal")

        combined = " ".join(parts).strip()
        if combined:
            if model_json.is_near_duplicate(combined, list(seen) + chapter_texts):
                errors.append(f"scene {index} repeats an earlier scene (near-duplicate)")
            chapter_texts.append(combined)
            texts.append(combined)

    for phrase in model_json.banned_hits(texts, banned):
        errors.append(f"banned phrase: {phrase!r}")

    return errors


def author_scenes(
    chapter: Mapping[str, Any],
    *,
    count: int,
    skill: Any,
    llm: Any,
    banned: Sequence[str],
    seen: Sequence[str],
) -> tuple[list[dict[str, str]] | None, int, list[str]]:
    """Ask for one chapter's scenes until they validate, feeding errors back each attempt."""

    def prompt_for(feedback: Sequence[str]) -> str:
        return scene_prompt(skill, chapter, count, banned, feedback)

    def validate(payload: Any) -> list[str]:
        return _scene_checks(payload, count=count, banned=banned, seen=seen)

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
    scenes = [
        {
            "goal": str(scene["goal"]).strip(),
            "conflict": str(scene["conflict"]).strip(),
            "turn": str(scene["turn"]).strip(),
        }
        for scene in payload["scenes"]
    ]
    return scenes, attempts, []


# --------------------------------------------------------------------------- build


@dataclass
class CardsReport:
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    model: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors


def _split(imagery: str) -> str:
    return imagery.split(":", 1)[0].strip() or "the setting"


def _scene_count(
    targets: craft_targets.Targets | None, number: Any, seed: int
) -> int:
    count, _ = craft_targets.sample(
        targets,
        "chapters.scenes",
        seed=seed,
        stage=STAGE_DIR,
        key=f"scenes-{number}",
        default=DEFAULT_SCENES,
    )
    return max(MIN_SCENES, min(MAX_SCENES, int(count)))


def _skeleton_scenes(chapter: Mapping[str, Any], count: int) -> list[dict[str, Any]]:
    beats = list(chapter.get("beats") or [])
    texts = [
        str(beat.get("text") or "").strip()
        for beat in beats
        if str(beat.get("text") or "").strip()
    ]
    if not texts:
        texts = [
            " ".join(
                part
                for part in (
                    str(beat.get("action") or "").strip(),
                    str(beat.get("obstacle") or "").strip(),
                    str(beat.get("outcome") or "").strip(),
                )
                if part
            )
            for beat in beats
        ]
    texts = [text for text in texts if text]
    if not texts:
        texts = [f"chapter {chapter.get('number')} opens on the ordinary work of the day"]

    shape = str(chapter.get("shape") or "the chapter shape").split(",")[0].strip()
    imagery = _split(str(chapter.get("imagery") or ""))
    complication = chapter.get("complication")

    scenes: list[dict[str, Any]] = []
    for index in range(count):
        goal = texts[index % len(texts)]
        if index == 0 and complication:
            conflict = f"the complication lands: {complication}"
        else:
            conflict = f"{shape} works against the goal, and {imagery} sets the price"
        turn = texts[(index + 1) % len(texts)]
        if turn == goal:
            turn = f"the goal costs more than the scene bargained for ({imagery})"
        scenes.append(
            {"number": index + 1, "goal": goal, "conflict": conflict, "turn": turn}
        )
    return scenes


def build_cards(
    outline: Mapping[str, Any],
    *,
    targets: craft_targets.Targets | None = None,
    seed: int = 0,
    skeleton: bool = False,
    llm: Any = None,
    skill: Any = None,
    banned: Sequence[str] = (),
    notes: list[str] | None = None,
    partial_path: str | Path | None = None,
) -> tuple[dict[str, Any], CardsReport]:
    """Cards for every chapter: model-written by default, deterministic with `skeleton`.

    Each validated chapter is saved to `partial_path`, so a rerun continues from the first
    missing chapter. The partial file is deleted only when every chapter is done.
    """
    notes = notes if notes is not None else []
    chapters: list[dict[str, Any]] = []
    report = CardsReport()
    report.model = {
        "mode": "skeleton" if skeleton else "model",
        "calls": 0,
        "attempts": 0,
        "resumed": 0,
    }

    if not skeleton and (llm is None or skill is None):
        report.errors.append("stage 12 is model-authored, but no planner adapter was supplied")
        return {"chapters": []}, report
    if skeleton:
        notes.append("skeleton used: the scene cards are deterministic and the model was not called")

    stored = {} if skeleton else model_json.load_partial(partial_path, notes)
    saved_cards: dict[int, dict[str, Any]] = {}
    seen: list[str] = []
    failed = False
    for chapter in outline.get("chapters") or []:
        number = chapter.get("number")
        count = _scene_count(targets, number, seed)
        authored: list[dict[str, str]] | None = None
        if skeleton:
            scenes = _skeleton_scenes(chapter, count)
        else:
            saved = stored.get(number)
            if saved is not None:
                candidate = {
                    "scenes": [
                        {key: scene.get(key) for key in SCENE_KEYS}
                        for scene in saved.get("scenes") or []
                        if isinstance(scene, Mapping)
                    ]
                }
                errors = _scene_checks(candidate, count=count, banned=banned, seen=seen)
                if errors:
                    notes.append(
                        f"partial chapter {number} no longer fits its constraints; "
                        "authoring it again"
                    )
                else:
                    authored = [
                        {key: str(scene[key]).strip() for key in SCENE_KEYS}
                        for scene in candidate["scenes"]
                    ]
                    report.model["resumed"] = int(report.model["resumed"]) + 1

            if authored is None:
                authored, attempts, errors = author_scenes(
                    chapter, count=count, skill=skill, llm=llm, banned=banned, seen=seen
                )
                report.model["calls"] = int(report.model["calls"]) + attempts
                report.model["attempts"] = max(
                    int(report.model.get("attempts") or 0), attempts
                )
                if authored is None:
                    report.model["failed_chapter"] = number
                    report.errors.append(f"chapter {number}: " + "; ".join(errors[:5]))
                    failed = True
                    break

            scenes = [
                {"number": index + 1, **scene} for index, scene in enumerate(authored)
            ]
            seen.extend(
                " ".join((scene["goal"], scene["conflict"], scene["turn"])) for scene in scenes
            )
            saved_cards[number] = {"scenes": authored}
            model_json.save_partial(partial_path, saved_cards)

        chapters.append(
            {
                "number": number,
                "title": chapter.get("title") or f"Chapter {number}",
                "scenes": scenes,
            }
        )

    if not failed and partial_path is not None and not skeleton:
        Path(partial_path).unlink(missing_ok=True)
    return {"chapters": chapters}, report


# --------------------------------------------------------------------------- rendering


def render_cards(cards: dict, notes: list[str] | tuple[str, ...] = ()) -> str:
    lines = ["# Scene cards", ""]
    for chapter in cards.get("chapters") or []:
        lines += [f"## Chapter {chapter.get('number')} - {chapter.get('title')}", ""]
        for scene in chapter.get("scenes") or []:
            lines += [
                f"### Scene {scene.get('number')}",
                "",
                f"- goal: {scene.get('goal')}",
                f"- conflict: {scene.get('conflict')}",
                f"- turn: {scene.get('turn')}",
                "",
            ]
    if notes:
        lines += ["## Notes", ""]
        lines.extend(f"- {note}" for note in notes)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
