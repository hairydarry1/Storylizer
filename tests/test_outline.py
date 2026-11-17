"""M6: stage 11 (outline), its five validators, human gate 2 and the rules additions."""

from __future__ import annotations

import json

import pytest
import yaml

from pipeline import outline, runner, schemas

STAGE8 = "08-character_creation"
STAGE10 = "10-series_bible"
STAGE11 = "11-outline"


def project_path(root):
    return root / "projects" / "demo"


def stage_dir(root, name):
    return project_path(root) / "stages" / name


def read_meta(root, name=STAGE11):
    return json.loads((stage_dir(root, name) / "meta.json").read_text(encoding="utf-8"))


def write_concept(root, **values):
    path = project_path(root) / "concept.yaml"
    concept = yaml.safe_load(path.read_text(encoding="utf-8"))
    concept.update(values)
    path.write_text(yaml.safe_dump(concept, sort_keys=False), encoding="utf-8")


def build_outline_project(root):
    runner.run_stage(root, "demo", "character_creation")
    runner.run_stage(root, "demo", "series_bible")
    return runner.run_stage(root, "demo", "outline")


def outline_data(root):
    return json.loads((stage_dir(root, STAGE11) / "outline.json").read_text(encoding="utf-8"))


def table_values(root, name):
    raw = json.loads((root / "tables" / f"{name}.json").read_text(encoding="utf-8"))
    return {entry["value"] for entry in raw["entries"]}


def cast_of(root):
    return schemas.load_cast(stage_dir(root, STAGE8) / "cast.json")


# --------------------------------------------------------------------------- skill + stage


def test_outline_is_stage_eleven_behind_gate_two():
    skill = runner.load_skill(runner.Path(".").resolve(), "outline")

    assert skill.stage == 11
    assert skill.human_gate is True
    assert skill.uses_randomizer is True
    assert skill.uses_search is False
    assert skill.model_tier in ("planner", "writer", "checker")


def test_outline_writes_markdown_json_and_rules_additions(workspace):
    result = build_outline_project(workspace)

    directory = stage_dir(workspace, STAGE11)
    assert result.status == runner.NEEDS_APPROVAL
    assert result.meta["status"] == "done"
    for name in ("output.md", "outline.json", "rules_additions.json", "meta.json"):
        assert (directory / name).is_file(), name
    assert result.meta["files"] == ["output.md", "outline.json", "rules_additions.json", "meta.json"]
    assert result.meta["validators"]["ok"] is True
    assert all(result.meta["validators"]["checks"].values())
    assert result.meta["outline"]["chapters"] == len(outline_data(workspace)["chapters"])


def test_chapter_count_derives_from_target_words(workspace):
    build_outline_project(workspace)

    data = outline_data(workspace)
    chapters = data["chapters"]
    assert data["target_words"] == 60000
    assert data["words_per_chapter"] == 2500
    assert len(chapters) == 24  # ceil(60000 / 2500)
    assert [chapter["number"] for chapter in chapters] == list(range(1, 25))


def test_a_craft_targets_file_sets_the_words_per_chapter(workspace):
    (project_path(workspace) / "craft_targets.json").write_text(
        json.dumps({"chapters": {"words": [4000, 4000]}}), encoding="utf-8"
    )

    build_outline_project(workspace)

    data = outline_data(workspace)
    assert data["words_per_chapter"] == 4000
    assert len(data["chapters"]) == 15  # ceil(60000 / 4000)
    assert read_meta(workspace)["craft_targets"]["path"].endswith("craft_targets.json")


def test_every_chapter_carries_its_shape_imagery_tension_and_actors(workspace):
    build_outline_project(workspace)

    data = outline_data(workspace)
    shapes = table_values(workspace, "chapter_shapes")
    imagery = table_values(workspace, "imagery_domains")
    cast_ids = {character.id for character in cast_of(workspace).characters}

    for chapter in data["chapters"]:
        assert chapter["shape"] in shapes
        assert chapter["imagery"] in imagery
        assert 1 <= chapter["tension"] <= 5
        assert chapter["words"] >= 1
        assert chapter["beats"], "every chapter needs beats"
        for beat in chapter["beats"]:
            assert beat["who_acts"] in cast_ids
            assert beat["text"].strip()
            assert beat["kind"] in {"setup", "complication", "reversal", "resolution", "threat"}


def test_the_first_chapter_uses_the_rolled_shape_and_imagery(workspace):
    build_outline_project(workspace)

    rolls = {roll["key"]: roll["value"] for roll in read_meta(workspace)["rolls"]}
    chapter = outline_data(workspace)["chapters"][0]

    assert chapter["shape"] == rolls["chapter_shape"]
    assert chapter["imagery"] == rolls["imagery_domain"]


def test_complications_arrive_every_few_chapters_and_illustrations_are_optional(workspace):
    build_outline_project(workspace)

    chapters = outline_data(workspace)["chapters"]
    with_complication = [chapter["number"] for chapter in chapters if chapter["complication"]]
    assert 3 in with_complication
    assert all(number % 3 == 0 for number in with_complication)

    illustrated = [chapter for chapter in chapters if chapter["illustration"]]
    assert illustrated
    assert all(chapter["tension"] >= 4 for chapter in illustrated)


def test_outline_needs_the_cast_and_the_bible(workspace):
    with pytest.raises(runner.StoryError, match="character_creation"):
        runner.run_stage(workspace, "demo", "outline")

    runner.run_stage(workspace, "demo", "character_creation")
    with pytest.raises(runner.StoryError, match="series_bible"):
        runner.run_stage(workspace, "demo", "outline")


def test_missing_upstream_outputs_are_notes_not_failures(workspace):
    result = build_outline_project(workspace)

    assert any("01-intake" in note for note in result.notes)
    assert result.status == runner.NEEDS_APPROVAL


def test_the_echo_adapter_is_a_note_not_a_failure(workspace):
    result = build_outline_project(workspace)

    assert any("no prose" in note.lower() for note in result.notes)
    assert result.status == runner.NEEDS_APPROVAL


def test_the_outline_is_deterministic(workspace):
    build_outline_project(workspace)
    first = (stage_dir(workspace, STAGE11) / "outline.json").read_text(encoding="utf-8")

    runner.run_stage(workspace, "demo", "outline")
    second = (stage_dir(workspace, STAGE11) / "outline.json").read_text(encoding="utf-8")

    assert first == second


# --------------------------------------------------------------------------- validators


def make_cast(sheet):
    return schemas.cast_from_dict(
        {
            "characters": [
                sheet(id="protagonist", name="Mara", role="protagonist"),
                sheet(id="a", name="Ann", role="ally"),
                sheet(id="b", name="Bo", role="mentor"),
            ]
        }
    )


def make_outline(chapters=8, *, threat_every=2, resolution_actor="protagonist", tension=None):
    secondaries = ("a", "b")
    data = {
        "title": "Test",
        "background_threat": "the debt",
        "chapters": [],
    }
    for number in range(1, chapters + 1):
        actor = secondaries[(number - 2) % len(secondaries)] if number >= 2 else "protagonist"
        beats = [
            {"id": f"ch{number:02d}-b1", "kind": "setup", "who_acts": actor, "text": "setup"},
            {"id": f"ch{number:02d}-b2", "kind": "reversal", "who_acts": "protagonist", "text": "turn"},
            {
                "id": f"ch{number:02d}-b3",
                "kind": "resolution",
                "who_acts": resolution_actor,
                "text": "resolution",
            },
        ]
        if threat_every and number % threat_every == 0:
            beats.append({"id": f"ch{number:02d}-b4", "kind": "threat", "who_acts": actor, "text": "threat"})
        data["chapters"].append(
            {
                "number": number,
                "title": f"Chapter {number}",
                "shape": f"shape-{number % 3}",
                "imagery": "river",
                "tension": (tension or [1, 2, 3, 4, 5, 4, 3, 2])[(number - 1) % 8],
                "words": 2500,
                "complication": None,
                "illustration": None,
                "beats": beats,
            }
        )
    return data


def test_a_clean_minimal_outline_passes(sheet):
    report = outline.validate_outline(make_outline(), make_cast(sheet))

    assert report.ok, report.errors


def test_three_chapters_in_a_row_with_one_shape_fail(sheet):
    data = make_outline()
    for chapter in data["chapters"][:3]:
        chapter["shape"] = "the-same-shape"

    report = outline.validate_outline(data, make_cast(sheet))

    assert not report.ok
    assert report.checks["shape_run"] is False
    assert any("shape" in error for error in report.errors)


def test_two_secondaries_debuting_in_one_chapter_fail(sheet):
    data = make_outline()
    for chapter in data["chapters"]:
        for beat in chapter["beats"]:
            if beat["who_acts"] == "b":
                beat["who_acts"] = "a"
    data["chapters"][1]["beats"].append(
        {"id": "ch02-bx", "kind": "threat", "who_acts": "b", "text": "debut"}
    )

    report = outline.validate_outline(data, make_cast(sheet))

    assert not report.ok
    assert report.checks["secondary_debut"] is False
    assert any("debut" in error.lower() for error in report.errors)


def test_a_secondary_that_never_appears_fails(sheet):
    data = make_outline()
    for chapter in data["chapters"]:
        for beat in chapter["beats"]:
            if beat["who_acts"] == "b":
                beat["who_acts"] = "a"

    report = outline.validate_outline(data, make_cast(sheet))

    assert not report.ok
    assert report.checks["secondary_debut"] is False
    assert any("never appear" in error for error in report.errors)


def test_a_threat_in_under_forty_percent_of_chapters_fails(sheet):
    report = outline.validate_outline(make_outline(threat_every=100), make_cast(sheet))

    assert not report.ok
    assert report.checks["background_threat"] is False
    assert any("40%" in error for error in report.errors)


def test_a_protagonist_who_resolves_under_seventy_percent_fails(sheet):
    data = make_outline(resolution_actor="a")

    report = outline.validate_outline(data, make_cast(sheet))

    assert not report.ok
    assert report.checks["protagonist_resolution"] is False
    assert any("70%" in error for error in report.errors)


def test_a_monotonic_tension_curve_fails(sheet):
    data = make_outline()
    for chapter in data["chapters"]:
        chapter["tension"] = min(5, chapter["number"])

    report = outline.validate_outline(data, make_cast(sheet))

    assert not report.ok
    assert report.checks["tension_curve"] is False
    assert any("tension" in error.lower() for error in report.errors)


# --------------------------------------------------------------------------- gate 2


def test_gate_two_approves_a_clean_outline(workspace):
    build_outline_project(workspace)

    result = runner.approve_gate(workspace, "demo", "2")

    assert result.status == runner.DONE
    assert result.stage.number == 11
    assert read_meta(workspace)["approved"] is True


def test_gate_two_refuses_a_failed_outline_without_force(workspace):
    build_outline_project(workspace)
    meta = read_meta(workspace)
    meta["status"] = "failed"
    meta["error"] = "shape_run: chapters 4-6 share one shape"
    (stage_dir(workspace, STAGE11) / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

    with pytest.raises(runner.StoryError, match="failed"):
        runner.approve_gate(workspace, "demo", "2")

    forced = runner.approve_gate(workspace, "demo", "2", force=True)
    assert forced.status == runner.DONE
    assert forced.warnings


def test_gate_three_still_names_m8(workspace):
    with pytest.raises(runner.StoryError, match="M8"):
        runner.approve_gate(workspace, "demo", "3")


# --------------------------------------------------------------------------- rules additions


def test_rules_additions_add_items_recipes_locations_and_skills(workspace):
    build_outline_project(workspace)

    additions = json.loads(
        (stage_dir(workspace, STAGE11) / "rules_additions.json").read_text(encoding="utf-8")
    )
    rules = json.loads((stage_dir(workspace, STAGE10) / "rules.json").read_text(encoding="utf-8"))

    assert additions["items"]
    assert additions["recipes"]
    assert additions["locations"]
    assert all("sources" in node for node in additions["items"].values())

    for recipe in additions["recipes"]:
        assert recipe["produces"] in additions["items"] or recipe["produces"] in rules["items"]
        for ingredient in recipe["ingredients"]:
            assert ingredient in additions["items"] or ingredient in rules["items"]

    for node in additions["locations"].values():
        for target in node["exits"]:
            assert target in rules["locations"], f"unknown exit target {target}"

    known_skills = set(rules["skills"]) | set(additions["skills"])
    for skill_id, node in additions["skills"].items():
        for requirement in node.get("requires") or []:
            assert requirement in known_skills
        assert node["unlocks_at_level"] >= 1
