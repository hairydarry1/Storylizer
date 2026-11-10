"""M1: `story status` reports done / needs approval / failed for every stage."""

from __future__ import annotations

import json

import pytest

from pipeline import runner


def make_project(root, slug="demo"):
    return runner.init_project(root, slug).project


def write_stage(project, stage, *, output=True, meta=None):
    directory = project / "stages" / stage.dir_name
    directory.mkdir(parents=True, exist_ok=True)
    if output:
        (directory / "output.md").write_text("stage output\n", encoding="utf-8")
    if meta is not None:
        (directory / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return directory


def stage_state(project, number):
    stage = next(s for s in runner.STAGES if s.number == number)
    return runner.stage_state(project, stage)


def test_stage_registry_matches_the_spec_order():
    assert [s.number for s in runner.STAGES] == list(range(1, 20))
    assert runner.STAGES[0].dir_name == "01-intake"
    assert runner.STAGES[8].dir_name == "09-ensemble_check"
    assert runner.STAGES[10].dir_name == "11-outline"
    assert runner.STAGES[-1].dir_name == "19-packaging"
    assert {s.number: s.human_gate for s in runner.STAGES if s.human_gate} == {9: 1, 11: 2, 17: 3}


def test_fresh_project_has_every_stage_pending(tmp_path):
    project = make_project(tmp_path)

    status = runner.project_status(tmp_path, "demo")

    assert len(status.stages) == len(runner.STAGES)
    assert {s.status for s in status.stages} == {"pending"}


def test_stage_with_output_and_ok_meta_is_done(tmp_path):
    project = make_project(tmp_path)
    write_stage(project, runner.STAGES[0], meta={"stage": "intake", "status": "ok"})

    assert stage_state(project, 1).status == "done"


def test_stage_with_output_but_no_meta_is_done(tmp_path):
    project = make_project(tmp_path)
    write_stage(project, runner.STAGES[0])

    assert stage_state(project, 1).status == "done"


def test_human_gate_stage_needs_approval_until_approved(tmp_path):
    project = make_project(tmp_path)
    ensemble = runner.STAGES[8]
    write_stage(project, ensemble, meta={"stage": ensemble.name, "status": "ok", "approved": False})

    assert stage_state(project, 9).status == "needs approval"

    write_stage(project, ensemble, meta={"stage": ensemble.name, "status": "ok", "approved": True})

    assert stage_state(project, 9).status == "done"
    assert stage_state(project, 9).approved is True


def test_failed_meta_marks_the_stage_failed(tmp_path):
    project = make_project(tmp_path)
    write_stage(project, runner.STAGES[0], meta={"stage": "intake", "status": "failed", "error": "model timed out"})

    state = stage_state(project, 1)

    assert state.status == "failed"
    assert state.error == "model timed out"


def test_meta_without_output_is_still_pending(tmp_path):
    project = make_project(tmp_path)
    write_stage(project, runner.STAGES[0], output=False, meta={"stage": "intake", "status": "ok"})

    assert stage_state(project, 1).status == "pending"


def test_status_reads_the_concept_title_and_target(tmp_path):
    project = make_project(tmp_path)
    concept_path = project / "concept.yaml"
    concept_path.write_text(
        'slug: demo\nworking_title: "The Lighthouse Listens"\ntarget_words: 75000\n', encoding="utf-8"
    )

    status = runner.project_status(tmp_path, "demo")

    assert status.title == "The Lighthouse Listens"
    assert status.target_words == 75000


def test_format_status_is_a_table_of_stages(tmp_path):
    make_project(tmp_path)

    text = runner.format_status(runner.project_status(tmp_path, "demo"))

    assert "Project: demo" in text
    assert "01-intake" in text
    assert "19-packaging" in text
    assert "needs approval" not in text
    assert text.count("pending") == len(runner.STAGES)


def test_format_status_marks_gates(tmp_path):
    make_project(tmp_path)

    lines = runner.format_status(runner.project_status(tmp_path, "demo")).splitlines()

    gate_line = next(line for line in lines if "11-outline" in line)
    assert " 2 " in gate_line or gate_line.split()[1] == "2"


def test_missing_project_is_a_story_error(tmp_path):
    with pytest.raises(runner.StoryError):
        runner.project_status(tmp_path, "nope")
