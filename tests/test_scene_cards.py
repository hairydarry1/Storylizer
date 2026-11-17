"""M6: stage 12 scene cards - goal, conflict and turn for every scene."""

from __future__ import annotations

import json

import pytest

from pipeline import runner

STAGE11 = "11-outline"
STAGE12 = "12-scene_card"


def stage_dir(root, name):
    return root / "projects" / "demo" / "stages" / name


def read_meta(root, name=STAGE12):
    return json.loads((stage_dir(root, name) / "meta.json").read_text(encoding="utf-8"))


def build(root):
    runner.run_stage(root, "demo", "character_creation")
    runner.run_stage(root, "demo", "series_bible")
    runner.run_stage(root, "demo", "outline")
    return runner.run_stage(root, "demo", "scene_card")


def cards_data(root):
    return json.loads((stage_dir(root, STAGE12) / "cards.json").read_text(encoding="utf-8"))


def test_scene_card_is_stage_twelve_without_a_gate():
    skill = runner.load_skill(runner.Path(".").resolve(), "scene_card")

    assert skill.stage == 12
    assert skill.human_gate is False
    assert skill.uses_randomizer is False
    assert skill.uses_search is False


def test_scene_cards_write_one_card_per_chapter(workspace):
    result = build(workspace)

    directory = stage_dir(workspace, STAGE12)
    assert result.status == runner.DONE
    assert (directory / "output.md").is_file()
    assert (directory / "cards.json").is_file()
    assert (directory / "meta.json").is_file()
    assert result.meta["files"] == ["output.md", "cards.json", "meta.json"]

    outline = json.loads((stage_dir(workspace, STAGE11) / "outline.json").read_text(encoding="utf-8"))
    cards = cards_data(workspace)["chapters"]
    assert len(cards) == len(outline["chapters"])
    assert [card["number"] for card in cards] == [chapter["number"] for chapter in outline["chapters"]]
    assert result.meta["cards"]["chapters"] == len(cards)


def test_every_scene_has_a_goal_a_conflict_and_a_turn(workspace):
    build(workspace)

    for card in cards_data(workspace)["chapters"]:
        assert 2 <= len(card["scenes"]) <= 4
        for scene in card["scenes"]:
            assert scene["goal"].strip()
            assert scene["conflict"].strip()
            assert scene["turn"].strip()
            assert scene["goal"] != scene["turn"]


def test_scene_count_follows_the_craft_targets(workspace):
    (workspace / "projects" / "demo" / "craft_targets.json").write_text(
        json.dumps({"chapters": {"scenes": [2, 2]}}), encoding="utf-8"
    )

    build(workspace)

    for card in cards_data(workspace)["chapters"]:
        assert len(card["scenes"]) == 2
    assert read_meta(workspace)["craft_targets"]["path"].endswith("craft_targets.json")


def test_scene_cards_need_the_outline(workspace):
    with pytest.raises(runner.StoryError, match="outline"):
        runner.run_stage(workspace, "demo", "scene_card")


def test_the_echo_adapter_is_a_note_not_a_failure(workspace):
    result = build(workspace)

    assert result.status == runner.DONE
    assert any("no prose" in note.lower() for note in result.notes)


def test_cards_render_the_turn_into_the_markdown(workspace):
    result = build(workspace)

    text = result.output_path.read_text(encoding="utf-8")
    first = cards_data(workspace)["chapters"][0]["scenes"][0]
    assert "## Chapter 1" in text
    assert first["goal"] in text
    assert first["turn"] in text
