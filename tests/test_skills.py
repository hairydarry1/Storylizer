"""M3: skill files carry the frontmatter and sections required by BUILD_SPEC.md section 5."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline import runner

PROJECT_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FRONTMATTER = (
    "name",
    "stage",
    "model_tier",
    "inputs",
    "outputs",
    "human_gate",
    "uses_search",
    "uses_randomizer",
)
REQUIRED_SECTIONS = ("Purpose", "Inputs", "Steps", "Output format", "Do not", "Self-check")


@pytest.mark.parametrize("name", ["character_creation", "ensemble_check"])
def test_the_skill_files_parse(name):
    skill = runner.load_skill(PROJECT_ROOT, name)

    assert skill.name == name
    assert skill.stage in (8, 9)
    assert skill.model_tier in ("planner", "writer", "checker", "none")
    for key in REQUIRED_FRONTMATTER:
        assert key in skill.frontmatter, f"{name} is missing frontmatter {key}"
    for section in REQUIRED_SECTIONS:
        assert skill.sections.get(section, "").strip(), f"{name} is missing section {section}"


def test_character_creation_is_a_randomizer_stage_without_a_gate():
    skill = runner.load_skill(PROJECT_ROOT, "character_creation")

    assert skill.stage == 8
    assert skill.uses_randomizer is True
    assert skill.human_gate is False
    assert "stakes" in skill.sections["Steps"].lower()


def test_ensemble_check_is_the_human_gate_after_stage_nine():
    skill = runner.load_skill(PROJECT_ROOT, "ensemble_check")

    assert skill.stage == 9
    assert skill.human_gate is True
    assert skill.model_tier == "checker"
    assert skill.uses_search is False
    body = skill.sections["Steps"].lower()
    for topic in ("voice", "want", "stereotype"):
        assert topic in body


def test_a_missing_skill_is_a_clear_error():
    with pytest.raises(runner.StoryError, match="skill"):
        runner.load_skill(PROJECT_ROOT, "no_such_skill")


def test_a_skill_for_the_wrong_stage_is_rejected(tmp_path):
    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "character_creation.md").write_text(
        "---\nname: character_creation\nstage: 9\nmodel_tier: planner\n"
        "inputs: []\noutputs: []\nhuman_gate: false\nuses_search: false\nuses_randomizer: true\n---\n"
        "## Purpose\nx\n## Inputs\nx\n## Steps\nx\n## Output format\nx\n## Do not\nx\n## Self-check\nx\n",
        encoding="utf-8",
    )

    with pytest.raises(runner.StoryError, match="stage"):
        runner.load_skill(tmp_path, "character_creation")
