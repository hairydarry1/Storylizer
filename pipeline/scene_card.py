"""Stage 12: scene cards.

One card per outline chapter, each scene with a goal, a conflict and a turn. The cards are
derived from the chapter's beats, so a scene cannot drift away from the approved outline.
"""

from __future__ import annotations

import yaml

from . import craft_targets

STAGE_DIR = "12-scene_card"
DEFAULT_SCENES = 3
MIN_SCENES = 2
MAX_SCENES = 4


def _split(imagery: str) -> str:
    return imagery.split(":", 1)[0].strip() or "the setting"


def _scenes(chapter: dict, count: int) -> list[dict]:
    beats = list(chapter.get("beats") or [])
    texts = [str(beat.get("text") or "").strip() for beat in beats if str(beat.get("text") or "").strip()]
    if not texts:
        texts = [f"chapter {chapter.get('number')} opens on the ordinary work of the day"]

    shape = str(chapter.get("shape") or "the chapter shape").split(",")[0].strip()
    imagery = _split(str(chapter.get("imagery") or ""))
    complication = chapter.get("complication")

    scenes: list[dict] = []
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


def build_cards(outline: dict, *, targets: craft_targets.Targets | None = None, seed: int = 0) -> dict:
    """Cards for every chapter; the scene count comes from craft_targets when it is present."""
    chapters: list[dict] = []
    for chapter in outline.get("chapters") or []:
        number = chapter.get("number")
        count, _ = craft_targets.sample(
            targets,
            "chapters.scenes",
            seed=seed,
            stage=STAGE_DIR,
            key=f"scenes-{number}",
            default=DEFAULT_SCENES,
        )
        count = max(MIN_SCENES, min(MAX_SCENES, int(count)))
        chapters.append(
            {
                "number": number,
                "title": chapter.get("title") or f"Chapter {number}",
                "scenes": _scenes(chapter, count),
            }
        )
    return {"chapters": chapters}


def render_cards(cards: dict, notes: list[str] | tuple[str, ...] = (), model_text: str = "") -> str:
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
    if model_text.strip():
        lines += ["## Planner notes", "", model_text.strip(), ""]
    return "\n".join(lines).rstrip() + "\n"


def cards_prompt(
    skill,
    outline: dict,
    cards: dict,
    upstream: str,
    notes: list[str] | tuple[str, ...],
) -> str:
    sections = "\n\n".join(f"## {name}\n\n{text}" for name, text in skill.sections.items())
    chapter = (cards.get("chapters") or [{}])[0]
    note_text = "\n".join(f"- {note}" for note in notes) or "- none"
    return (
        f"{sections}\n\n"
        "## This project\n\n"
        f"- outline: {len(outline.get('chapters') or [])} chapters, "
        f"threat: {outline.get('background_threat')}\n"
        f"- sample card:\n{yaml.safe_dump(chapter, sort_keys=False)}\n\n"
        "Earlier stage outputs:\n"
        f"{upstream.strip() or '(none yet)'}\n\n"
        "Notes:\n"
        f"{note_text}\n\n"
        "Reply with prose notes on how to stage these scenes. Do not change a goal, a conflict "
        "or a turn; the cards above are fixed.\n"
    )
