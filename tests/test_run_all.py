"""M4: `story run all` runs built stages in order and stops at the next human gate."""

from __future__ import annotations

import pytest

from pipeline import cli, runner


def stage_dir(root, name):
    return root / "projects" / "demo" / "stages" / name


def test_run_all_runs_through_stage_nine_and_stops_at_gate_one(workspace):
    result = runner.run_all(workspace, "demo", skeleton=True)

    assert [run.stage.number for run in result.results] == list(range(1, 10))
    assert result.stopped_at == runner.resolve_stage("ensemble_check")
    assert "gate" in result.reason.lower()
    for number in range(1, 10):
        stage = runner.STAGES[number - 1]
        assert (stage_dir(workspace, stage.dir_name) / "output.md").is_file()
        assert (stage_dir(workspace, stage.dir_name) / "meta.json").is_file()
    assert not stage_dir(workspace, "10-series_bible").exists()


def test_run_all_is_idempotent_and_does_not_rerun_finished_stages(workspace):
    runner.run_all(workspace, "demo", skeleton=True)

    second = runner.run_all(workspace, "demo", skeleton=True)

    assert second.results == []
    assert second.stopped_at == runner.resolve_stage("ensemble_check")
    assert "gate" in second.reason.lower()


def test_run_all_after_gate_one_builds_the_bible_and_outline_and_stops_at_gate_two(workspace):
    runner.run_all(workspace, "demo", skeleton=True)
    runner.approve_gate(workspace, "demo", "1")

    second = runner.run_all(workspace, "demo", skeleton=True)

    assert [run.stage.number for run in second.results] == [10, 11]
    assert second.stopped_at == runner.resolve_stage("outline")
    assert "gate 2" in second.reason
    assert (stage_dir(workspace, "10-series_bible") / "bible.md").is_file()
    assert (stage_dir(workspace, "11-outline") / "outline.json").is_file()


def test_run_all_after_gate_two_reaches_the_chapter_writer(workspace):
    runner.run_all(workspace, "demo", skeleton=True)
    runner.approve_gate(workspace, "demo", "1")
    runner.run_all(workspace, "demo", skeleton=True)
    runner.approve_gate(workspace, "demo", "2")

    result = runner.run_all(workspace, "demo", skeleton=True)

    assert [run.stage.number for run in result.results] == [12, 13, 14]
    assert result.stopped_at == runner.resolve_stage("chapter_writer")
    assert result.results[-1].status == runner.FAILED
    for name in ("12-scene_card", "13-narrator_voice", "14-chapter_writer"):
        assert (stage_dir(workspace, name) / "output.md").is_file()


def test_run_all_names_the_next_unbuilt_stage(workspace):
    with pytest.raises(runner.StoryError, match="M7c"):
        runner.run_stage(workspace, "demo", "quality_gates")


def test_run_all_skips_completed_early_stages_but_finishes_the_rest(workspace):
    for name in ("intake", "market_research", "reference_analysis"):
        runner.run_stage(workspace, "demo", name)

    result = runner.run_all(workspace, "demo", skeleton=True)

    assert [run.stage.number for run in result.results] == list(range(4, 10))


def test_cli_run_all_reports_each_stage_and_the_gate(workspace, capsys):
    assert cli.main(["--root", str(workspace), "run", "all", "--skeleton"]) == 0

    out = capsys.readouterr().out
    assert "01-intake" in out
    assert "09-ensemble_check" in out
    assert "gate 1" in out
    assert "story approve 1" in out
    assert (stage_dir(workspace, "09-ensemble_check") / "output.md").is_file()


def test_cli_run_all_twice_still_stops_at_the_gate(workspace, capsys):
    assert cli.main(["--root", str(workspace), "run", "all", "--skeleton"]) == 0
    capsys.readouterr()

    assert cli.main(["--root", str(workspace), "run", "all", "--skeleton"]) == 0
    out = capsys.readouterr().out
    assert "gate 1" in out
    assert "nothing to run" in out.lower()
