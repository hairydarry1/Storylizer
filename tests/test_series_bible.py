"""M5: stage 10 writes bible.md, rules.json and the initial ledger, plus `story ledger`."""

from __future__ import annotations

import json

import pytest
import yaml

from pipeline import cli, ledger, runner, schemas

STAGE8 = "08-character_creation"
STAGE10 = "10-series_bible"


def project_path(root):
    return root / "projects" / "demo"


def stage_dir(root, name):
    return project_path(root) / "stages" / name


def write_concept(root, **values):
    path = project_path(root) / "concept.yaml"
    concept = yaml.safe_load(path.read_text(encoding="utf-8"))
    concept.update(values)
    path.write_text(yaml.safe_dump(concept, sort_keys=False), encoding="utf-8")


def build_bible(root):
    runner.run_stage(root, "demo", "character_creation")
    return runner.run_stage(root, "demo", "series_bible")


def test_series_bible_is_stage_ten_without_a_gate():
    skill = runner.load_skill(runner.Path(".").resolve(), "series_bible")

    assert skill.stage == 10
    assert skill.human_gate is False
    assert skill.uses_search is False
    assert skill.uses_randomizer is False
    assert skill.model_tier in ("planner", "writer", "checker")


def test_series_bible_writes_the_bible_rules_and_ledger(workspace):
    result = build_bible(workspace)

    directory = stage_dir(workspace, STAGE10)
    assert result.status == runner.DONE
    assert (directory / "output.md").is_file()
    assert (directory / "bible.md").is_file()
    assert (directory / "rules.json").is_file()
    assert (directory / "bible.md").read_text(encoding="utf-8") == result.output_path.read_text(
        encoding="utf-8"
    )
    assert result.meta["files"] == ["output.md", "bible.md", "rules.json", "meta.json"]

    rules = ledger.load_rules(directory / "rules.json")
    assert rules["system_type"] in ledger.SYSTEM_TYPES
    assert rules["locations"]
    assert rules["items"]
    assert result.meta["system_type"] == rules["system_type"]


def test_series_bible_seeds_the_ledger_from_the_cast(workspace):
    build_bible(workspace)

    cast = schemas.load_cast(stage_dir(workspace, STAGE8) / "cast.json")
    story = ledger.load_ledger(project_path(workspace) / "ledger.json")

    assert set(story["entities"]) == {character.id for character in cast.characters}
    assert story["chapter"] == 0
    assert story["events"] == []


def test_series_bible_needs_the_cast(workspace):
    with pytest.raises(runner.StoryError, match="character_creation"):
        runner.run_stage(workspace, "demo", "series_bible")


def test_missing_upstream_outputs_are_notes_not_failures(workspace):
    result = build_bible(workspace)

    assert any("01-intake" in note for note in result.notes)
    assert not any(STAGE10 in note for note in result.notes)
    assert result.status == runner.DONE


def test_an_existing_ledger_is_not_clobbered(workspace):
    build_bible(workspace)
    ledger_path = project_path(workspace) / "ledger.json"
    story = ledger.load_ledger(ledger_path)
    story["chapter"] = 4
    story["applied_deltas"] = ["ch01-main"]
    ledger.save_ledger(story, ledger_path)

    again = runner.run_stage(workspace, "demo", "series_bible")

    kept = ledger.load_ledger(ledger_path)
    assert kept["chapter"] == 4
    assert kept["applied_deltas"] == ["ch01-main"]
    assert any("kept" in note.lower() for note in again.notes)


def test_a_litrpg_genre_builds_level_thresholds_and_skills(workspace):
    write_concept(workspace, genre="litrpg cultivation")
    result = build_bible(workspace)

    rules = ledger.load_rules(stage_dir(workspace, STAGE10) / "rules.json")
    bible = result.output_path.read_text(encoding="utf-8")

    assert rules["system_type"] == "litrpg"
    assert rules["xp"]["thresholds"]
    assert rules["skills"]
    assert "## System and progression" in bible
    assert "XP" in bible


def test_a_plain_genre_stays_valid_without_stats(workspace):
    write_concept(workspace, genre="cozy mystery")
    result = build_bible(workspace)

    rules = ledger.load_rules(stage_dir(workspace, STAGE10) / "rules.json")
    story = ledger.load_ledger(project_path(workspace) / "ledger.json")

    assert rules["system_type"] == "none"
    assert rules["xp"]["thresholds"] == {}
    assert story["entities"]["protagonist"]["level"] == 0
    assert "no stat system" in result.output_path.read_text(encoding="utf-8").lower()


def test_the_bible_lists_the_cast_the_rules_and_the_location_graph(workspace):
    result = build_bible(workspace)

    cast = schemas.load_cast(stage_dir(workspace, STAGE8) / "cast.json")
    rules = ledger.load_rules(stage_dir(workspace, STAGE10) / "rules.json")
    bible = result.output_path.read_text(encoding="utf-8")

    assert cast.get("protagonist").name in bible
    assert "## World rules" in bible
    assert "## Cast" in bible
    assert "## Locations and travel" in bible
    assert "## Timeline" in bible
    for node in rules["locations"].values():
        assert node["name"] in bible


def test_the_echo_adapter_is_a_note_not_a_failure(workspace):
    result = build_bible(workspace)

    assert result.status == runner.DONE
    assert any("no prose" in note.lower() for note in result.notes)


def test_cli_ledger_show_lists_entities_and_state(workspace, capsys):
    build_bible(workspace)

    assert cli.main(["--root", str(workspace), "ledger", "show"]) == 0

    out = capsys.readouterr().out
    assert "protagonist" in out
    assert "level" in out
    assert "location" in out


def test_cli_ledger_validate_accepts_a_recorded_delta(workspace, capsys, tmp_path):
    build_bible(workspace)
    delta_path = tmp_path / "ch01.json"
    delta_path.write_text(
        json.dumps(
            {
                "chapter": 1,
                "ops": [
                    {"op": "event", "id": "found-ledger", "summary": "Mara finds the ledger"},
                    {
                        "op": "add_item",
                        "entity": "protagonist",
                        "item": "ledger",
                        "source": "found-ledger",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    assert cli.main(["--root", str(workspace), "ledger", "validate", str(delta_path)]) == 0
    assert "ok" in capsys.readouterr().out.lower()


def test_cli_ledger_validate_rejects_an_item_from_nowhere(workspace, capsys, tmp_path):
    build_bible(workspace)
    delta_path = tmp_path / "bad.json"
    delta_path.write_text(
        json.dumps(
            {
                "chapter": 1,
                "ops": [{"op": "add_item", "entity": "protagonist", "item": "ledger"}],
            }
        ),
        encoding="utf-8",
    )

    assert cli.main(["--root", str(workspace), "ledger", "validate", str(delta_path)]) == 1
    assert "nowhere" in capsys.readouterr().err.lower()


def test_cli_ledger_without_a_bible_names_the_stage(workspace, capsys, tmp_path):
    delta_path = tmp_path / "ch01.json"
    delta_path.write_text(json.dumps({"chapter": 1, "ops": []}), encoding="utf-8")

    assert cli.main(["--root", str(workspace), "ledger", "show"]) == 1
    assert "series_bible" in capsys.readouterr().err

    assert cli.main(["--root", str(workspace), "ledger", "validate", str(delta_path)]) == 1
    assert "series_bible" in capsys.readouterr().err
