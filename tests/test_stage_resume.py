"""M6c: stages 11 and 12 resume from the first missing chapter.

Every validated chapter is appended to `partial.json` in the stage folder. A rerun reuses
those chapters (calling the model only for the rest) and the partial file is deleted only
when the stage completes.
"""

from __future__ import annotations

import json

from pipeline import runner

from model_fakes import ChapterWriter, FailAtChapterWriter, SceneWriter

STAGE8 = "08-character_creation"
STAGE11 = "11-outline"
STAGE12 = "12-scene_card"


def stage_dir(root, name):
    return root / "projects" / "demo" / "stages" / name


def prepare_outline_inputs(root):
    runner.run_stage(root, "demo", "character_creation")
    runner.run_stage(root, "demo", "series_bible")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_a_failed_outline_keeps_the_validated_chapters(workspace):
    prepare_outline_inputs(workspace)

    result = runner.run_stage(
        workspace, "demo", "outline", llm=FailAtChapterWriter(fail_at=5)
    )

    assert result.status == runner.FAILED
    partial = stage_dir(workspace, STAGE11) / "partial.json"
    assert partial.is_file()
    saved = read_json(partial)
    assert [chapter["number"] for chapter in saved["chapters"]] == [1, 2, 3, 4]
    assert "partial.json" not in result.meta["files"]
    assert not (stage_dir(workspace, STAGE11) / "outline.json").exists()


def test_a_rerun_continues_from_the_first_missing_chapter(workspace):
    prepare_outline_inputs(workspace)
    runner.run_stage(workspace, "demo", "outline", llm=FailAtChapterWriter(fail_at=5))

    writer = ChapterWriter()
    result = runner.run_stage(workspace, "demo", "outline", llm=writer)

    assert result.status == runner.NEEDS_APPROVAL
    assert len(writer.calls) == 20  # 24 chapters, 4 already on disk
    assert result.meta["model"]["resumed"] == 4
    assert result.meta["model"]["calls"] == 20
    assert result.meta["validators"]["ok"] is True

    data = read_json(stage_dir(workspace, STAGE11) / "outline.json")
    assert len(data["chapters"]) == 24
    assert not (stage_dir(workspace, STAGE11) / "partial.json").exists()


def test_a_second_failure_resumes_where_the_first_stopped(workspace):
    prepare_outline_inputs(workspace)
    runner.run_stage(workspace, "demo", "outline", llm=FailAtChapterWriter(fail_at=5))

    writer = FailAtChapterWriter(fail_at=5)
    result = runner.run_stage(workspace, "demo", "outline", llm=writer)

    assert result.status == runner.FAILED
    assert len(writer.calls) == 3  # the four saved chapters are not re-requested
    saved = read_json(stage_dir(workspace, STAGE11) / "partial.json")
    assert [chapter["number"] for chapter in saved["chapters"]] == [1, 2, 3, 4]


def test_an_unreadable_partial_is_ignored(workspace):
    prepare_outline_inputs(workspace)
    partial = stage_dir(workspace, STAGE11) / "partial.json"
    partial.parent.mkdir(parents=True, exist_ok=True)
    partial.write_text("{ not json", encoding="utf-8")

    writer = ChapterWriter()
    result = runner.run_stage(workspace, "demo", "outline", llm=writer)

    assert result.status == runner.NEEDS_APPROVAL
    assert len(writer.calls) == 24
    assert any("partial" in note.lower() for note in result.notes)
    assert not partial.exists()


def test_scene_cards_resume_from_their_partial(workspace):
    prepare_outline_inputs(workspace)
    runner.run_stage(workspace, "demo", "outline", llm=ChapterWriter())

    first = runner.run_stage(
        workspace, "demo", "scene_card", llm=SceneWriter(fail_at=3)
    )
    assert first.status == runner.FAILED
    partial = stage_dir(workspace, STAGE12) / "partial.json"
    saved = read_json(partial)
    assert [chapter["number"] for chapter in saved["chapters"]] == [1, 2]
    assert not (stage_dir(workspace, STAGE12) / "cards.json").exists()

    writer = SceneWriter()
    second = runner.run_stage(workspace, "demo", "scene_card", llm=writer)

    assert second.status == runner.DONE
    assert len(writer.calls) == 22
    assert second.meta["model"]["resumed"] == 2
    cards = read_json(stage_dir(workspace, STAGE12) / "cards.json")
    assert len(cards["chapters"]) == 24
    assert not partial.exists()
