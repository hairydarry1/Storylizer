"""M6b: stage 11 is model-authored inside the code constraints.

Every chapter is one planner call returning strict JSON; invalid replies are retried with the
errors fed back, and a chapter that never validates fails the stage with no template fallback.
"""

from __future__ import annotations

import json

from pipeline import cli, runner
from pipeline.adapters.echo import EchoAdapter

from model_fakes import BadActorWriter, ChapterWriter, RepeatedChapterWriter, ShortChapterWriter

STAGE8 = "08-character_creation"
STAGE10 = "10-series_bible"
STAGE11 = "11-outline"


def stage_dir(root, name=STAGE11):
    return root / "projects" / "demo" / "stages" / name


def read_meta(root):
    return json.loads((stage_dir(root) / "meta.json").read_text(encoding="utf-8"))


def outline_data(root):
    return json.loads((stage_dir(root) / "outline.json").read_text(encoding="utf-8"))


def prepare(root):
    runner.run_stage(root, "demo", "character_creation")
    runner.run_stage(root, "demo", "series_bible")
    cast = json.loads((stage_dir(root, STAGE8) / "cast.json").read_text(encoding="utf-8"))
    return {character["id"] for character in cast["characters"]}


def run_outline(root, llm, *, skeleton=False):
    return runner.run_stage(root, "demo", "outline", llm=llm, skeleton=skeleton)


def test_each_chapter_is_a_planner_call_with_strict_json(workspace):
    cast_ids = prepare(workspace)
    writer = ChapterWriter()

    result = run_outline(workspace, writer)

    assert result.status == runner.NEEDS_APPROVAL
    data = outline_data(workspace)
    assert len(data["chapters"]) == 24
    assert len(writer.calls) == 24
    assert result.meta["model"] == {
        "mode": "model",
        "calls": 24,
        "attempts": 1,
        "chapters": 24,
    }
    assert result.meta["validators"]["ok"] is True
    assert all(writer_call["model_tier"] == "planner" for writer_call in writer.calls)

    first = data["chapters"][0]
    assert first["title"] == "Model chapter 1"
    assert first["hook"].startswith("Hook 1:")
    assert first["ends_on"].startswith("Ends 1:")
    assert len(first["beats"]) == 3
    assert first["beats"][-1]["kind"] == "resolution"
    for beat in first["beats"]:
        assert beat["actor"] in cast_ids
        assert beat["action"].strip() and beat["obstacle"].strip() and beat["outcome"].strip()

    chapters = data["chapters"]
    assert {chapter["shape"] for chapter in chapters}
    assert any(chapter["threat"] for chapter in chapters)
    assert all(
        chapter["beats"][-1]["actor"] == first["beats"][-1]["actor"] for chapter in chapters
    )


def test_the_prompt_carries_theme_cast_rules_and_previous_chapters(workspace):
    cast_ids = prepare(workspace)
    writer = ChapterWriter()

    run_outline(workspace, writer)

    prompt = writer.calls[1]["prompt"]
    assert "## Theme and premise" in prompt
    assert "## Cast" in prompt
    assert "## Rules summary" in prompt
    assert "## Chapter constraints" in prompt
    assert '"number": 2' in prompt
    assert any(cast_id in prompt for cast_id in cast_ids)
    assert "Model chapter 1" in prompt  # summary of the chapter before this one
    assert "Ends 1" in prompt
    assert "## Your reply" in prompt
    assert '"action"' in prompt


def test_invalid_json_retries_three_times_then_fails_without_a_fallback(workspace):
    prepare(workspace)
    writer = EchoAdapter({"response": "I cannot answer that."})

    result = run_outline(workspace, writer)

    assert result.status == runner.FAILED
    assert len(writer.calls) == 3
    assert result.meta["status"] == "failed"
    assert result.meta["model"]["attempts"] == 3
    assert result.meta["model"]["failed_chapter"] == 1
    assert "chapter 1" in result.meta["error"]
    assert result.meta["files"] == ["output.md", "meta.json"]

    assert not (stage_dir(workspace) / "outline.json").exists()
    assert not (stage_dir(workspace) / "rules_additions.json").exists()
    text = result.output_path.read_text(encoding="utf-8")
    assert "(none: the chapter was not authored)" in text
    assert "opens inside" not in text  # no template beats


def test_the_retry_feeds_the_validation_errors_back(workspace):
    prepare(workspace)
    writer = EchoAdapter({"response": "I cannot answer that."})

    run_outline(workspace, writer)

    assert "no JSON object" in writer.calls[0]["prompt"] or "## Your reply" in writer.calls[0]["prompt"]
    assert "## Your previous reply was rejected" in writer.calls[1]["prompt"]
    assert "no JSON object" in writer.calls[1]["prompt"]


def test_a_bad_actor_id_is_rejected(workspace):
    prepare(workspace)
    writer = BadActorWriter()

    result = run_outline(workspace, writer)

    assert result.status == runner.FAILED
    assert len(writer.calls) == 3
    assert "not a cast id" in result.meta["error"]


def test_too_few_beats_are_rejected(workspace):
    prepare(workspace)
    writer = ShortChapterWriter()

    result = run_outline(workspace, writer)

    assert result.status == runner.FAILED
    assert len(writer.calls) == 3
    assert "at least 3 beats" in result.meta["error"]


def test_a_banned_phrase_is_rejected(workspace):
    prepare(workspace)
    writer = ChapterWriter(phrase=", a testament to the town")

    result = run_outline(workspace, writer)

    assert result.status == runner.FAILED
    assert len(writer.calls) == 3
    assert "banned phrase" in result.meta["error"]


def test_beat_text_repeated_across_chapters_is_rejected(workspace):
    prepare(workspace)
    writer = RepeatedChapterWriter()

    result = run_outline(workspace, writer)

    assert result.status == runner.FAILED
    assert result.meta["model"]["failed_chapter"] == 2
    assert "near-duplicate" in result.meta["error"]
    assert len(writer.calls) == 4  # chapter 1 passes, chapter 2 uses all three attempts


def test_the_skeleton_never_calls_the_model_or_falls_back_silently(workspace):
    prepare(workspace)
    writer = EchoAdapter()

    result = run_outline(workspace, writer, skeleton=True)

    assert result.status == runner.NEEDS_APPROVAL
    assert writer.calls == []
    assert result.meta["model"]["mode"] == "skeleton"
    assert any("skeleton" in note.lower() for note in result.notes)
    assert result.meta["validators"]["ok"] is True


def test_cli_skeleton_flag_builds_the_outline(workspace, capsys):
    prepare(workspace)

    assert cli.main(["--root", str(workspace), "run", "outline", "--skeleton"]) == 0

    out = capsys.readouterr().out
    assert "needs approval" in out
    assert (stage_dir(workspace) / "outline.json").is_file()
