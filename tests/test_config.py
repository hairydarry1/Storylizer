"""M1: config.yaml selects the adapters, and the shipped config is valid."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline import runner
from pipeline.adapters.echo import EchoAdapter

REPO_ROOT = Path(__file__).resolve().parents[1]


def write_config(root, text):
    (root / "config.yaml").write_text(text, encoding="utf-8")


def test_config_reads_seed_chaos_dial_and_adapter(tmp_path):
    write_config(
        tmp_path,
        "seed: 42\n"
        "chaos_dial: 2\n"
        "adapters:\n"
        "  llm:\n"
        "    type: echo\n"
        "    options:\n"
        "      response: hello\n",
    )

    config = runner.load_config(tmp_path)

    assert config.seed == 42
    assert config.chaos_dial == 2
    adapter = runner.load_llm_adapter(config)
    assert isinstance(adapter, EchoAdapter)
    assert adapter.complete("anything") == "hello"


def test_missing_config_is_a_story_error(tmp_path):
    with pytest.raises(runner.StoryError):
        runner.load_config(tmp_path)


def test_chaos_dial_outside_0_to_3_is_rejected(tmp_path):
    write_config(tmp_path, "seed: 1\nchaos_dial: 9\nadapters:\n  llm:\n    type: echo\n")

    with pytest.raises(runner.StoryError):
        runner.load_config(tmp_path)


def test_non_integer_seed_is_rejected(tmp_path):
    write_config(tmp_path, "seed: abc\nchaos_dial: 1\nadapters:\n  llm:\n    type: echo\n")

    with pytest.raises(runner.StoryError):
        runner.load_config(tmp_path)


def test_missing_llm_adapter_is_a_story_error(tmp_path):
    write_config(tmp_path, "seed: 1\nchaos_dial: 1\nadapters: {}\n")

    config = runner.load_config(tmp_path)
    with pytest.raises(runner.StoryError):
        runner.load_llm_adapter(config)


def test_shipped_config_is_valid_and_uses_a_safe_adapter():
    config = runner.load_config(REPO_ROOT)

    assert config.seed == 20261106
    assert 0 <= config.chaos_dial <= 3
    assert isinstance(runner.load_llm_adapter(config), EchoAdapter)
