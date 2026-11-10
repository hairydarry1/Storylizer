"""Shared test setup: make the project root importable when pytest runs from anywhere."""

from __future__ import annotations

import copy
import shutil
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline import runner  # noqa: E402  (needs the path entry above)

TABLES_DIR = PROJECT_ROOT / "tables"
SKILLS_DIR = PROJECT_ROOT / "skills"


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: test that waits on real time")


@pytest.fixture
def make_workspace(tmp_path):
    """A throwaway pipeline root: config.yaml, its own copy of tables/ and one project.

    Each workspace gets a private tables/ directory, so tables/used.json memory does not
    leak between tests (or into the real repo). The skills/ folder is copied too, because
    stage runs read their prompt material from it.
    """

    def _make(name="ws", *, slot="demo", seed=4242, chaos_dial=1):
        root = tmp_path / name
        tables = root / "tables"
        tables.mkdir(parents=True)
        for source in TABLES_DIR.glob("*.json"):
            if source.name == "used.json":
                continue
            shutil.copy(source, tables / source.name)
        if SKILLS_DIR.is_dir():
            shutil.copytree(SKILLS_DIR, root / "skills")
        (root / "config.yaml").write_text(
            "seed: {seed}\nchaos_dial: {chaos}\nadapters:\n  llm:\n    type: echo\n".format(
                seed=seed, chaos=chaos_dial
            ),
            encoding="utf-8",
        )
        runner.init_project(root, slot)
        return root

    return _make


@pytest.fixture
def workspace(make_workspace):
    return make_workspace()


def _merge(base: dict, overrides: dict) -> dict:
    merged = copy.deepcopy(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


VALID_SHEET = {
    "id": "mara",
    "name": "Mara Voss",
    "role": "protagonist",
    "gender": "woman",
    "age": 34,
    "occupation": "ledger keeper",
    "background": "raised in the record office, never asked whether she wanted it",
    "look": {
        "build": "wiry",
        "hair": "black, cut short with a knife",
        "skin": "brown",
        "signature_clothing": "a grey coat with too many pockets",
        "marks": [{"what": "ink stain", "meaning": "she writes left-handed", "placement": "right palm"}],
    },
    "physical_differences": [],
    "intelligence_profile": {
        "sharp_at": ["ledgers", "who owes whom"],
        "blind_at": ["flattery"],
        "overconfident_about": ["her memory for faces"],
    },
    "emotional_core": {
        "want": "to keep the ledger out of the council's hands",
        "need": "to trust one person with the part of the record she cannot amend",
        "wound": "made the family's record-keeper at nine",
        "false_belief": "if the numbers are right, no one has to be forgiven",
        "fear": "being read as the person who kept the receipts",
        "coping_habit": "counts exits when a room turns friendly",
        "start_state": "braced for bad news that has not arrived",
        "arc_by_act": ["protects the ledger", "loses control of the record", "writes a true entry"],
        "laughs_at": "bureaucratic language used with total sincerity",
        "cries_at": "someone being kind without being asked",
        "stakes": "the only copy of the record that clears her mother",
    },
    "voice": {
        "rhythm": "clipped",
        "vocabulary": "precise, old-fashioned",
        "tics": ["taps a pen twice before answering"],
        "never_says": ["trust me"],
    },
    "relationships": [],
    "locked": [],
    "flaw": "mistakes control for care",
    "tags": [],
}


@pytest.fixture
def sheet():
    """Factory for a valid character sheet dict; pass nested overrides to break one field."""

    def _sheet(**overrides):
        return _merge(VALID_SHEET, overrides)

    return _sheet


@pytest.fixture
def bad_cast(sheet):
    """A deliberately bad ensemble: one age, one gender, one rhythm, a shared tic, 3 quirky."""

    def _character(index: int, **overrides) -> dict:
        character = sheet(
            id=f"c{index}",
            name=f"Character {index}",
            role="ally",
            age=30,
            gender="man",
            voice={"rhythm": "clipped", "tics": ["taps a pen twice before answering"]},
            tags=["quirky and clever"] if index < 3 else [],
            emotional_core={
                "want": f"to be the one who is right about the bridge (variant {index})",
                "stakes": f"the bridge contract, variant {index}",
            },
            **overrides,
        )
        character["relationships"] = [{"to": "c0", "bond": "rival", "friction": "everything"}]
        if index == 0:
            character["relationships"] = []
        return character

    def _cast(**overrides):
        return {"characters": [_character(index, **overrides) for index in range(4)]}

    return _cast
