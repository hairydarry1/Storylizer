"""M2: `story roll`, `story lock` and `story reroll` through the CLI."""

from __future__ import annotations

import json

import pytest

from pipeline import cli, runner


def run(root, *argv):
    return cli.main(["--root", str(root), *argv])


def rolls(root, slug="demo"):
    return json.loads((root / "projects" / slug / "rolls.json").read_text(encoding="utf-8"))["rolls"]


def test_roll_prints_the_rolls_and_logs_them(workspace, capsys):
    assert run(workspace, "roll", "8") == 0

    out = capsys.readouterr().out
    assert "08-character_creation" in out
    assert "protagonist_given_name" in out
    assert "flaw" in out
    assert len(rolls(workspace)) == 5 + runner.load_config(workspace).chaos_dial


def test_roll_accepts_a_stage_name(workspace, capsys):
    assert run(workspace, "roll", "outline") == 0

    assert "11-outline" in capsys.readouterr().out
    assert {record["stage"] for record in rolls(workspace)} == {"11-outline"}


def test_roll_requires_a_project_when_several_exist(workspace, capsys):
    runner.init_project(workspace, "second")

    assert run(workspace, "roll", "8") == 1
    assert "--project" in capsys.readouterr().err


def test_roll_accepts_the_project_flag(workspace, capsys):
    runner.init_project(workspace, "second")

    assert run(workspace, "roll", "8", "-p", "second") == 0
    assert capsys.readouterr().out
    assert rolls(workspace, "second")


def test_roll_rejects_a_stage_without_the_randomizer(workspace, capsys):
    assert run(workspace, "roll", "1") == 1

    assert "randomizer" in capsys.readouterr().err


def test_roll_survives_a_checker_that_cannot_answer(workspace, capsys):
    """The default echo adapter replies 'echo', which is not a fit-check verdict."""
    assert run(workspace, "roll", "8") == 0

    err = capsys.readouterr().err
    assert "check" in err.lower()
    assert len(rolls(workspace)) == 5 + runner.load_config(workspace).chaos_dial


def test_lock_then_reroll_is_refused(workspace, capsys):
    run(workspace, "roll", "8")
    capsys.readouterr()

    assert run(workspace, "lock", "flaw") == 0
    assert "locked" in capsys.readouterr().out
    assert any(record["locked"] for record in rolls(workspace) if record["key"] == "flaw")

    assert run(workspace, "reroll", "flaw") == 1
    assert "locked" in capsys.readouterr().err


def test_reroll_changes_the_value(workspace, capsys):
    run(workspace, "roll", "8")
    before = next(record["value"] for record in rolls(workspace) if record["key"] == "flaw")
    capsys.readouterr()

    assert run(workspace, "reroll", "flaw") == 0

    out = capsys.readouterr().out
    after = [record for record in rolls(workspace) if record["key"] == "flaw"]
    assert after[-1]["value"] != before
    assert "flaw" in out


def test_lock_and_reroll_reject_unknown_keys(workspace, capsys):
    run(workspace, "roll", "8")
    capsys.readouterr()

    assert run(workspace, "lock", "nope") == 1
    assert "no roll" in capsys.readouterr().err
    assert run(workspace, "reroll", "nope") == 1
    assert "no roll" in capsys.readouterr().err


def test_roll_on_a_missing_project_is_an_error(workspace, capsys):
    assert run(workspace, "lock", "flaw", "-p", "nope") == 1
    assert "init" in capsys.readouterr().err


def test_roll_statistics_are_stable_between_runs(workspace, capsys):
    run(workspace, "roll", "8")
    first = [(record["key"], record["value"]) for record in rolls(workspace)]
    capsys.readouterr()

    run(workspace, "roll", "8")

    assert [(record["key"], record["value"]) for record in rolls(workspace)] == first
