"""M6c: the closing actor is a code-assigned constraint, not always the protagonist.

At least 70% of chapters still close on the protagonist; the rest close on another actor who
has already debuted. The seeded randomizer picks the chapters, so a rerun with the same seed
assigns the same closing actors.
"""

from __future__ import annotations

import json
import math

from pipeline import runner

from model_fakes import ChapterWriter, IgnoringClosingActorWriter

STAGE8 = "08-character_creation"
STAGE10 = "10-series_bible"
STAGE11 = "11-outline"


def stage_dir(root, name=STAGE11):
    return root / "projects" / "demo" / "stages" / name


def prepare(root):
    runner.run_stage(root, "demo", "character_creation")
    runner.run_stage(root, "demo", "series_bible")
    cast = json.loads((stage_dir(root, STAGE8) / "cast.json").read_text(encoding="utf-8"))
    return {character["id"] for character in cast["characters"]}


def outline_data(root):
    return json.loads((stage_dir(root) / "outline.json").read_text(encoding="utf-8"))


def run_outline(root, llm):
    return runner.run_stage(root, "demo", "outline", llm=llm)


def test_closing_actors_are_assigned_and_mostly_the_protagonist(workspace):
    cast_ids = prepare(workspace)
    writer = ChapterWriter()

    result = run_outline(workspace, writer)

    assert result.status == runner.NEEDS_APPROVAL
    chapters = outline_data(workspace)["chapters"]
    closings = [chapter["closing_actor"] for chapter in chapters]

    assert all(closing in cast_ids for closing in closings)
    assert all(chapter["beats"][-1]["actor"] == chapter["closing_actor"] for chapter in chapters)
    assert closings[0] == "protagonist"
    assert closings.count("protagonist") >= math.ceil(len(chapters) * 0.7)
    assert len(set(closings) - {"protagonist"}) >= 1
    assert result.meta["validators"]["checks"]["protagonist_resolution"] is True
    assert len(writer.calls) == len(chapters)


def test_the_chapter_prompt_states_the_assigned_closing_actor(workspace):
    prepare(workspace)
    writer = ChapterWriter()

    run_outline(workspace, writer)

    prompt = writer.calls[0]["prompt"]
    assert '"closing_actor"' in prompt
    constraint = json.loads(prompt.split("## Chapter constraints", 1)[1].split("```json", 1)[1].split("```", 1)[0])
    assert constraint["closing_actor"] == "protagonist"
    assert "the last beat is acted by" in prompt


def test_same_seed_assigns_the_same_closing_actors(workspace):
    prepare(workspace)
    run_outline(workspace, ChapterWriter())
    first = [chapter["closing_actor"] for chapter in outline_data(workspace)["chapters"]]

    run_outline(workspace, ChapterWriter())
    second = [chapter["closing_actor"] for chapter in outline_data(workspace)["chapters"]]

    assert first == second


def test_a_chapter_that_ignores_its_closing_actor_is_rejected(workspace):
    prepare(workspace)
    writer = IgnoringClosingActorWriter()

    result = run_outline(workspace, writer)

    assert result.status == runner.FAILED
    failed_chapter = result.meta["model"]["failed_chapter"]
    assert failed_chapter > 1  # chapter 1 still closes on the protagonist
    assert "closing beat" in result.meta["error"]
    assert len(writer.calls) == (failed_chapter - 1) + 3
