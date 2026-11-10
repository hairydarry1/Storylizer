"""M3: `story run` and `story approve` through the CLI."""

from __future__ import annotations

import json

from pipeline import cli


def stage_dir(root, name):
    return root / "projects" / "demo" / "stages" / name


def test_run_builds_the_character_creation_stage(workspace, capsys):
    assert cli.main(["--root", str(workspace), "run", "character_creation"]) == 0

    out = capsys.readouterr().out
    assert "08-character_creation" in out
    assert "done" in out
    assert (stage_dir(workspace, "08-character_creation") / "cast.json").is_file()


def test_run_then_approve_passes_the_cast_gate(workspace, capsys):
    assert cli.main(["--root", str(workspace), "run", "8"]) == 0
    capsys.readouterr()

    assert cli.main(["--root", str(workspace), "run", "ensemble_check"]) == 0
    out = capsys.readouterr().out
    assert "needs approval" in out

    assert cli.main(["--root", str(workspace), "approve", "1"]) == 0
    out = capsys.readouterr().out
    assert "approved" in out
    assert "gate 1" in out


def test_run_reports_a_stage_without_a_skill(workspace, capsys):
    assert cli.main(["--root", str(workspace), "run", "series_bible"]) == 1
    assert "not built" in capsys.readouterr().err


def test_run_reports_a_flagged_cast(workspace, bad_cast, capsys):
    assert cli.main(["--root", str(workspace), "run", "character_creation"]) == 0
    (stage_dir(workspace, "08-character_creation") / "cast.json").write_text(
        json.dumps(bad_cast()), encoding="utf-8"
    )
    capsys.readouterr()

    assert cli.main(["--root", str(workspace), "run", "ensemble_check"]) == 1

    err = capsys.readouterr().err
    assert "error:" in err
    assert "failed" in err


def test_approve_without_a_gate_stage_is_an_error(workspace, capsys):
    assert cli.main(["--root", str(workspace), "approve", "1"]) == 1
    assert "run" in capsys.readouterr().err


def test_run_accepts_the_project_flag(workspace, make_workspace, capsys):
    other = make_workspace("other", slot="other-book")

    assert cli.main(["--root", str(other), "run", "character_creation", "-p", "other-book"]) == 0
    assert "08-character_creation" in capsys.readouterr().out
