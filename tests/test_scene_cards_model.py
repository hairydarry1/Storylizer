"""M6b: stage 12 scene cards are model-written, per chapter, with retries.

The outline's constraints stay code-owned; the planner writes goal, conflict and turn for
each scene as strict JSON. Invalid replies fail the stage after three attempts.
"""

from __future__ import annotations

import json

from pipeline import runner
from pipeline.adapters.echo import EchoAdapter

from model_fakes import SceneWriter

STAGE11 = "11-outline"
STAGE12 = "12-scene_card"


def stage_dir(root, name=STAGE12):
    return root / "projects" / "demo" / "stages" / name


def read_meta(root):
    return json.loads((stage_dir(root) / "meta.json").read_text(encoding="utf-8"))


def cards_data(root):
    return json.loads((stage_dir(root) / "cards.json").read_text(encoding="utf-8"))


def prepare(root):
    runner.run_stage(root, "demo", "character_creation")
    runner.run_stage(root, "demo", "series_bible")
    runner.run_stage(root, "demo", "outline", skeleton=True)


def run_cards(root, llm, *, skeleton=False):
    return runner.run_stage(root, "demo", "scene_card", llm=llm, skeleton=skeleton)


def test_each_chapter_gets_model_written_goal_conflict_and_turn(workspace):
    prepare(workspace)
    writer = SceneWriter()

    result = run_cards(workspace, writer)

    assert result.status == runner.DONE
    assert len(writer.calls) == 24
    assert result.meta["model"]["mode"] == "model"
    assert result.meta["model"]["calls"] == 24
    assert result.meta["files"] == ["output.md", "cards.json", "meta.json"]

    cards = cards_data(workspace)
    outline = json.loads(
        (stage_dir(workspace, STAGE11) / "outline.json").read_text(encoding="utf-8")
    )
    assert len(cards["chapters"]) == len(outline["chapters"])
    first = cards["chapters"][0]
    assert first["title"] == outline["chapters"][0]["title"]
    assert first["scenes"][0]["number"] == 1
    assert first["scenes"][0]["goal"].startswith("ch1 scene 1: get the ledger")
    assert first["scenes"][0]["conflict"].startswith("ch1 scene 1: the clerk stalls")
    assert first["scenes"][0]["turn"].startswith("ch1 scene 1: the price rises")
    for card in cards["chapters"]:
        assert 2 <= len(card["scenes"]) <= 4
        for scene in card["scenes"]:
            assert scene["goal"].strip() and scene["conflict"].strip() and scene["turn"].strip()
    assert "## Scene constraints" in writer.calls[0]["prompt"]
    assert writer.calls[0]["model_tier"] == "planner"


def test_invalid_json_retries_three_times_then_fails_without_cards(workspace):
    prepare(workspace)
    writer = EchoAdapter({"response": "no scenes today"})

    result = run_cards(workspace, writer)

    assert result.status == runner.FAILED
    assert len(writer.calls) == 3
    assert result.meta["model"]["failed_chapter"] == 1
    assert "chapter 1" in result.meta["error"]
    assert result.meta["files"] == ["output.md", "meta.json"]
    assert not (stage_dir(workspace) / "cards.json").exists()
    text = result.output_path.read_text(encoding="utf-8")
    assert "### Scene" not in text
    assert "## Your previous reply was rejected" in writer.calls[1]["prompt"]


def test_a_wrong_scene_count_is_rejected(workspace):
    prepare(workspace)
    writer = SceneWriter(short=True)

    result = run_cards(workspace, writer)

    assert result.status == runner.FAILED
    assert len(writer.calls) == 3
    assert "exactly 3 scenes" in result.meta["error"]


def test_a_banned_phrase_is_rejected(workspace):
    prepare(workspace)
    writer = SceneWriter(phrase=", a testament to the clerk")

    result = run_cards(workspace, writer)

    assert result.status == runner.FAILED
    assert len(writer.calls) == 3
    assert "banned phrase" in result.meta["error"]


def test_scene_text_repeated_across_chapters_is_rejected(workspace):
    prepare(workspace)
    writer = SceneWriter(repeat=True)

    result = run_cards(workspace, writer)

    assert result.status == runner.FAILED
    assert result.meta["model"]["failed_chapter"] == 2
    assert "near-duplicate" in result.meta["error"]
    assert len(writer.calls) == 4


def test_the_skeleton_does_not_call_the_model(workspace):
    prepare(workspace)
    writer = EchoAdapter()

    result = run_cards(workspace, writer, skeleton=True)

    assert result.status == runner.DONE
    assert writer.calls == []
    assert result.meta["model"]["mode"] == "skeleton"
    assert any("skeleton" in note.lower() for note in result.notes)
    assert cards_data(workspace)["chapters"]
