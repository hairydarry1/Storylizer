"""The quick-task .env loader: parsing, precedence, startup order and no leaked values."""

from __future__ import annotations

import os

from pipeline import cli, envfile, runner


def test_parses_comments_blank_lines_export_and_quotes(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "\n"
        "# a comment\n"
        "  # an indented comment\n"
        "\n"
        "PLAIN=plain-value\n"
        "WITH_SPACES=value with spaces\n"
        "EXPORTED=exported-value\n"
        "export EXPORT_WITH_SPACE=exported with spaces\n"
        "DOUBLE=\"double value\"\n"
        "SINGLE='single value'\n"
        "QUOTED_HASH=\"a value # not a comment\"\n"
        "SINGLE_QUOTED_HASH='another # kept'\n"
        "INLINE=inline-value # trailing comment\n"
        "EMPTY=\n"
        "NOT_A_SETTING\n",
        encoding="utf-8",
    )

    parsed = envfile.parse_env(path.read_text(encoding="utf-8"))

    assert parsed == {
        "PLAIN": "plain-value",
        "WITH_SPACES": "value with spaces",
        "EXPORTED": "exported-value",
        "EXPORT_WITH_SPACE": "exported with spaces",
        "DOUBLE": "double value",
        "SINGLE": "single value",
        "QUOTED_HASH": "a value # not a comment",
        "SINGLE_QUOTED_HASH": "another # kept",
        "INLINE": "inline-value",
        "EMPTY": "",
    }


def test_load_env_never_overrides_the_real_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("STORY_ENVFILE_REAL", "from-real-environment")
    monkeypatch.delenv("STORY_ENVFILE_NEW", raising=False)
    (tmp_path / ".env").write_text(
        "STORY_ENVFILE_REAL=from-file\n"
        "STORY_ENVFILE_NEW=fake-new-value\n",
        encoding="utf-8",
    )

    applied = envfile.load_env(tmp_path)

    assert os.environ["STORY_ENVFILE_REAL"] == "from-real-environment"
    assert os.environ["STORY_ENVFILE_NEW"] == "fake-new-value"
    assert applied == {"STORY_ENVFILE_NEW": "fake-new-value"}


def test_a_missing_file_is_fine(tmp_path):
    assert envfile.load_env(tmp_path) == {}
    assert not (tmp_path / ".env").exists()


def test_cli_loads_env_before_config_and_leaks_no_values(
    workspace, monkeypatch, capsys
):
    name = "STORY_ENVFILE_FAKE_SECRET"
    secret = "fake-secret-value-9f3c"
    monkeypatch.delenv(name, raising=False)
    (workspace / ".env").write_text(
        f"# fake value for tests only\n{name}={secret}\n", encoding="utf-8"
    )

    real_load_config = runner.load_config
    seen: dict[str, str | None] = {}

    def spy(root, path=None):
        seen["value_at_config_load"] = os.environ.get(name)
        return real_load_config(root, path)

    monkeypatch.setattr(cli.runner, "load_config", spy)

    assert cli.main(["--root", str(workspace), "run", "character_creation"]) == 0

    captured = capsys.readouterr()
    assert os.environ[name] == secret
    assert seen["value_at_config_load"] == secret
    assert secret not in captured.out
    assert secret not in captured.err

    project = workspace / "projects" / "demo"
    for path in project.rglob("*"):
        if path.is_file():
            assert secret not in path.read_text(encoding="utf-8", errors="replace")


def test_cli_reads_the_env_next_to_a_custom_config(tmp_path, monkeypatch, capsys):
    name = "STORY_ENVFILE_CUSTOM_CONFIG"
    fake = "fake-custom-config-value"
    monkeypatch.delenv(name, raising=False)

    root = tmp_path / "root"
    config_dir = tmp_path / "config-dir"
    root.mkdir()
    config_dir.mkdir()
    (config_dir / ".env").write_text(f"{name}={fake}\n", encoding="utf-8")
    config = config_dir / "config.yaml"
    config.write_text(
        "seed: 1\nchaos_dial: 1\nadapters:\n  llm:\n    type: echo\n",
        encoding="utf-8",
    )

    assert cli.main(["--root", str(root), "--config", str(config), "status"]) == 1

    captured = capsys.readouterr()
    assert os.environ[name] == fake
    assert fake not in captured.out
    assert fake not in captured.err
