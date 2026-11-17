"""M6c: `--max-calls` and the per-day model call counter kept in the project."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline import budget, cli, runner
from pipeline.adapters.echo import EchoAdapter


def project_of(root):
    return root / "projects" / "demo"


def counter_file(project):
    return Path(project) / "calls.json"


def read_counter(project):
    return json.loads(counter_file(project).read_text(encoding="utf-8"))


def test_the_counter_persists_calls_across_instances(tmp_path):
    project = tmp_path / "project"
    first = budget.CallCounter(project, today="2026-11-17")
    first.spend()
    first.spend()

    second = budget.CallCounter(project, today="2026-11-17")
    second.spend()

    assert second.today_total == 3
    assert read_counter(project)["days"]["2026-11-17"] == 3


def test_calls_are_counted_per_day(tmp_path):
    project = tmp_path / "project"
    budget.CallCounter(project, today="2026-11-17").spend()
    budget.CallCounter(project, today="2026-11-18").spend()
    counter = budget.CallCounter(project, today="2026-11-18")

    assert counter.today_total == 1
    assert read_counter(project)["days"] == {"2026-11-17": 1, "2026-11-18": 1}


def test_the_run_limit_stops_before_the_call_is_counted(tmp_path):
    counter = budget.CallCounter(tmp_path / "project", limit=2, today="2026-11-17")
    counter.spend()
    counter.spend()

    with pytest.raises(budget.BudgetExceeded) as excinfo:
        counter.spend()

    assert "budget of 2" in str(excinfo.value)
    assert counter.today_total == 2
    assert counter.used == 2


def test_old_days_are_pruned(tmp_path):
    path = tmp_path / "project" / "calls.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"days": {"2000-01-01": 12, "2026-11-17": 1}}), encoding="utf-8"
    )

    counter = budget.CallCounter(tmp_path / "project", today="2026-11-17")
    counter.spend()

    assert "2000-01-01" not in read_counter(tmp_path / "project")["days"]


def test_the_budget_adapter_counts_every_call_and_delegates(tmp_path):
    child = EchoAdapter({"response": "hello"})
    counter = budget.CallCounter(tmp_path / "project", today="2026-11-17")
    adapter = budget.BudgetedLLMAdapter(child, counter)

    assert adapter.complete("hi", model_tier="writer") == "hello"

    assert counter.today_total == 1
    assert child.calls[0]["model_tier"] == "writer"
    assert adapter.describe()["calls_today"] == 1


def test_max_calls_is_required_to_be_positive(workspace):
    with pytest.raises(runner.StoryError):
        runner.run_stage(workspace, "demo", "character_creation", max_calls=0)


def test_cli_counts_a_calls_in_the_project(workspace, capsys):
    assert (
        cli.main(["--root", str(workspace), "run", "character_creation", "--max-calls", "1"])
        == 0
    )

    out = capsys.readouterr().out
    assert "model calls: 1" in out
    assert read_counter(project_of(workspace))["days"]  # saved in the project
    assert sum(read_counter(project_of(workspace))["days"].values()) == 1


def test_cli_fails_the_stage_when_the_run_budget_is_gone(workspace, capsys):
    assert cli.main(["--root", str(workspace), "run", "character_creation"]) == 0
    assert cli.main(["--root", str(workspace), "run", "series_bible"]) == 0
    capsys.readouterr()

    assert cli.main(["--root", str(workspace), "run", "outline", "--max-calls", "1"]) == 1

    err = capsys.readouterr().err
    assert "model call budget of 1" in err
    meta = json.loads(
        (project_of(workspace) / "stages" / "11-outline" / "meta.json").read_text(
            encoding="utf-8"
        )
    )
    assert meta["status"] == "failed"
    assert "model call budget of 1" in meta["error"]
    assert not (project_of(workspace) / "stages" / "11-outline" / "outline.json").exists()


def test_run_all_accepts_max_calls(workspace, capsys):
    assert (
        cli.main(["--root", str(workspace), "run", "all", "--max-calls", "50"]) == 0
    )

    assert "model calls:" in capsys.readouterr().out
