"""M2: the seeded RNG must not depend on Python's hash randomisation."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from pipeline import runner
from pipeline.randomizer import seed_int

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_seed_is_derived_from_sha256_of_seed_stage_key():
    expected = int(hashlib.sha256(b"7|08-character_creation|flaw").hexdigest(), 16)

    assert seed_int(7, "08-character_creation", "flaw") == expected


def test_seed_differs_per_key_and_per_attempt():
    assert seed_int(7, "08-character_creation", "flaw") != seed_int(7, "08-character_creation", "quirk")
    assert seed_int(7, "08-character_creation", "flaw", attempt=1) != seed_int(
        7, "08-character_creation", "flaw"
    )


def test_seed_is_stable_for_the_same_inputs():
    assert seed_int(11, "11-outline", "chapter_shape") == seed_int(11, "11-outline", "chapter_shape")


def test_seed_does_not_use_builtin_hash():
    """hash() is salted per process; the sha256 derivation is not."""
    assert seed_int(1, "s", "k") == int(hashlib.sha256(b"1|s|k").hexdigest(), 16)
    assert seed_int(1, "s", "k") != hash((1, "s", "k"))


def _copy_tables(root):
    shutil.copytree(PROJECT_ROOT / "tables", root / "tables", ignore=shutil.ignore_patterns("used.json"))
    (root / "config.yaml").write_text(
        "seed: 99\nchaos_dial: 2\nadapters:\n  llm:\n    type: echo\n", encoding="utf-8"
    )
    runner.init_project(root, "demo")


def test_rolls_are_identical_under_different_pythonhashseed(tmp_path):
    results = []

    for hashseed in ("0", "12345"):
        root = tmp_path / f"root-{hashseed}"
        root.mkdir()
        _copy_tables(root)

        env = {**os.environ, "PYTHONPATH": str(PROJECT_ROOT), "PYTHONHASHSEED": hashseed}
        completed = subprocess.run(
            [sys.executable, "-m", "pipeline.cli", "--root", str(root), "roll", "8"],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            env=env,
            timeout=120,
        )

        assert completed.returncode == 0, completed.stderr
        data = json.loads((root / "projects" / "demo" / "rolls.json").read_text(encoding="utf-8"))
        results.append([(roll["key"], roll["value"]) for roll in data["rolls"]])

    assert results[0], "the roll command logged nothing"
    assert results[0] == results[1]
