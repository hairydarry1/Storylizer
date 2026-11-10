"""M1: `story init` creates the project tree from the spec."""

from __future__ import annotations

import json

import pytest
import yaml

from pipeline import runner


def test_init_creates_the_project_tree(tmp_path):
    result = runner.init_project(tmp_path, "my-book")

    project = tmp_path / "projects" / "my-book"
    assert result.project == project
    assert (project / "concept.yaml").is_file()
    assert (project / "rolls.json").is_file()
    assert (project / "ledger.json").is_file()
    assert (project / "stages").is_dir()
    assert (project / "chapters").is_dir()
    assert (project / "reports").is_dir()


def test_init_writes_the_concept_template_from_the_spec(tmp_path):
    runner.init_project(tmp_path, "my-book")

    concept = yaml.safe_load((tmp_path / "projects" / "my-book" / "concept.yaml").read_text(encoding="utf-8"))

    assert concept["slug"] == "my-book"
    assert concept["working_title"] == ""
    assert concept["genre"] == ""
    assert concept["tone_dial"] == 1
    assert concept["audience"] == ""
    assert concept["target_words"] == 60000
    assert concept["pen_name"] == ""
    assert concept["premise_seed"] == ""
    assert concept["must_include"] == []
    assert concept["must_avoid"] == []


def test_init_writes_empty_state_files(tmp_path):
    runner.init_project(tmp_path, "my-book")
    project = tmp_path / "projects" / "my-book"

    assert json.loads((project / "rolls.json").read_text(encoding="utf-8")) == {"rolls": []}
    ledger = json.loads((project / "ledger.json").read_text(encoding="utf-8"))
    assert ledger == {"chapter": 0, "entities": {}, "events": []}


def test_init_is_idempotent_and_keeps_user_edits(tmp_path):
    runner.init_project(tmp_path, "my-book")
    concept_path = tmp_path / "projects" / "my-book" / "concept.yaml"
    concept = yaml.safe_load(concept_path.read_text(encoding="utf-8"))
    concept["premise_seed"] = "A lighthouse keeper who can hear the sea's opinion of her."
    concept_path.write_text(yaml.safe_dump(concept), encoding="utf-8")

    second = runner.init_project(tmp_path, "my-book")

    assert concept_path in second.kept
    reloaded = yaml.safe_load(concept_path.read_text(encoding="utf-8"))
    assert reloaded["premise_seed"].startswith("A lighthouse keeper")


def test_init_force_overwrites_the_concept_template(tmp_path):
    runner.init_project(tmp_path, "my-book")
    concept_path = tmp_path / "projects" / "my-book" / "concept.yaml"
    concept_path.write_text("slug: my-book\npremise_seed: edited\n", encoding="utf-8")

    runner.init_project(tmp_path, "my-book", force=True)

    concept = yaml.safe_load(concept_path.read_text(encoding="utf-8"))
    assert concept["premise_seed"] == ""
    assert concept["target_words"] == 60000


@pytest.mark.parametrize("slug", ["", "My Book", "my_book", "-leading", "trailing-", "two--hyphens", "ünïcode"])
def test_invalid_slugs_are_rejected(tmp_path, slug):
    with pytest.raises(runner.StoryError):
        runner.init_project(tmp_path, slug)

    assert not (tmp_path / "projects").exists()


def test_list_projects_returns_initialised_projects_sorted(tmp_path):
    runner.init_project(tmp_path, "second")
    runner.init_project(tmp_path, "first")
    (tmp_path / "projects" / "scratch").mkdir()

    assert runner.list_projects(tmp_path) == ["first", "second"]
