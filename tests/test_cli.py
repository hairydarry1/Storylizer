"""M1: `story init` and `story status` through the CLI, plus honest stubs for later milestones."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from pipeline import cli

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_init_command_creates_a_project(tmp_path, capsys):
    assert cli.main(["--root", str(tmp_path), "init", "my-book"]) == 0

    out = capsys.readouterr().out
    assert str(tmp_path / "projects" / "my-book") in out
    assert (tmp_path / "projects" / "my-book" / "concept.yaml").is_file()


def test_init_command_rejects_a_bad_slug(tmp_path, capsys):
    assert cli.main(["--root", str(tmp_path), "init", "My Book"]) == 1

    err = capsys.readouterr().err
    assert "slug" in err.lower()


def test_status_command_uses_the_only_project(tmp_path, capsys):
    cli.main(["--root", str(tmp_path), "init", "my-book"])
    capsys.readouterr()

    assert cli.main(["--root", str(tmp_path), "status"]) == 0

    out = capsys.readouterr().out
    assert "Project: my-book" in out
    assert "01-intake" in out
    assert "pending" in out


def test_status_command_requires_a_project_when_several_exist(tmp_path, capsys):
    cli.main(["--root", str(tmp_path), "init", "one"])
    cli.main(["--root", str(tmp_path), "init", "two"])
    capsys.readouterr()

    assert cli.main(["--root", str(tmp_path), "status"]) == 1
    assert "--project" in capsys.readouterr().err


def test_status_command_without_projects(tmp_path, capsys):
    assert cli.main(["--root", str(tmp_path), "status"]) == 1
    assert "story init" in capsys.readouterr().err


def test_status_command_accepts_project_flag(tmp_path, capsys):
    cli.main(["--root", str(tmp_path), "init", "one"])
    cli.main(["--root", str(tmp_path), "init", "two"])
    capsys.readouterr()

    assert cli.main(["--root", str(tmp_path), "status", "--project", "two"]) == 0
    assert "Project: two" in capsys.readouterr().out


@pytest.mark.parametrize(
    "argv",
    [
        ["check", "ch01"],
        ["export"],
    ],
)
def test_later_milestone_commands_are_honest_stubs(tmp_path, capsys, argv):
    assert cli.main(["--root", str(tmp_path), *argv]) == 2

    err = capsys.readouterr().err
    assert "not implemented" in err
    assert "BUILD_SPEC.md" in err


def test_running_from_the_project_root_needs_no_root_flag(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["init", "my-book"]) == 0
    capsys.readouterr()

    assert cli.main(["status"]) == 0
    assert "Project: my-book" in capsys.readouterr().out


def test_module_entry_point_works(tmp_path):
    env = {**os.environ, "PYTHONPATH": str(PROJECT_ROOT)}
    result = subprocess.run(
        [sys.executable, "-m", "pipeline.cli", "--root", str(tmp_path), "init", "my-book"],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,  # pytest's captured stdin handle is not inheritable on Windows
        env=env,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "projects" / "my-book" / "concept.yaml").is_file()
