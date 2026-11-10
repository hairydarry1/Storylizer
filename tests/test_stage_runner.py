"""M3: the generic stage runner, the two built stages, and the human gate."""

from __future__ import annotations

import json

import pytest
import yaml

from pipeline import runner, schemas
from pipeline.adapters.echo import EchoAdapter

STAGE8 = "08-character_creation"
STAGE9 = "09-ensemble_check"


def stage_dir(root, name):
    return root / "projects" / "demo" / "stages" / name


def read_meta(root, name):
    return json.loads((stage_dir(root, name) / "meta.json").read_text(encoding="utf-8"))


def write_concept(root, **values):
    path = root / "projects" / "demo" / "concept.yaml"
    concept = yaml.safe_load(path.read_text(encoding="utf-8"))
    concept.update(values)
    path.write_text(yaml.safe_dump(concept, sort_keys=False), encoding="utf-8")


def test_character_creation_writes_the_stage_tree(workspace):
    result = runner.run_stage(workspace, "demo", "character_creation")

    directory = stage_dir(workspace, STAGE8)
    assert result.status == runner.DONE
    assert (directory / "output.md").is_file()
    assert (directory / "cast.json").is_file()
    assert result.meta["status"] == "done"
    assert result.meta["skill"] == "character_creation"
    assert result.meta["model_tier"] == "planner"
    assert result.meta["approved"] is False


def test_character_creation_uses_the_stage_eight_rolls(workspace):
    write_concept(workspace, premise_seed="a ledger that remembers debts", genre="literary mystery")
    llm = EchoAdapter({"response": "echo"})

    result = runner.run_stage(workspace, "demo", "character_creation", llm=llm)

    rolls = {roll["key"]: roll["value"] for roll in result.meta["rolls"]}
    cast = schemas.load_cast(stage_dir(workspace, STAGE8) / "cast.json")
    protagonist = cast.get("protagonist")

    assert protagonist.name == f"{rolls['protagonist_given_name']} {rolls['protagonist_family_name']}"
    assert protagonist.flaw == rolls["flaw"]

    prompt = llm.calls[0]["prompt"]
    assert rolls["quirk"] in prompt
    assert "a ledger that remembers debts" in prompt
    assert llm.calls[0]["model_tier"] == "planner"


def test_missing_upstream_stages_are_notes_not_failures(workspace):
    result = runner.run_stage(workspace, "demo", "character_creation")

    assert any("01-intake" in note for note in result.notes)
    assert any("07-tone_ceiling" in note for note in result.notes)
    assert not any("08-character_creation" in note for note in result.notes)


def test_an_unusable_model_reply_falls_back_to_the_validated_draft(workspace):
    result = runner.run_stage(workspace, "demo", "character_creation", llm=EchoAdapter({"response": "echo"}))

    assert any("model" in note.lower() for note in result.notes)
    cast = schemas.load_cast(stage_dir(workspace, STAGE8) / "cast.json")
    assert cast.get("protagonist").emotional_core.want


def test_a_model_cast_that_validates_is_used(workspace, sheet):
    payload = {
        "characters": [
            sheet(id="odelle", name="Odelle Farr", role="protagonist"),
            sheet(
                id="bram",
                name="Bram Teal",
                role="foil",
                age=55,
                gender="man",
                voice={"rhythm": "measured", "tics": ["clears his throat before lying"]},
                emotional_core={"want": "to own the ledger", "stakes": "his seat on the council"},
                relationships=[{"to": "odelle", "bond": "rival", "friction": "the record"}],
            ),
        ]
    }
    llm = EchoAdapter({"response": json.dumps(payload)})

    result = runner.run_stage(workspace, "demo", "character_creation", llm=llm)

    cast = schemas.load_cast(stage_dir(workspace, STAGE8) / "cast.json")
    assert [character.id for character in cast.characters] == ["odelle", "bram"]
    assert any("model" in note.lower() for note in result.notes)


def test_an_invalid_model_cast_is_rejected_and_noted(workspace, sheet):
    payload = {"characters": [sheet(id="odelle", name="", role="protagonist")]}
    llm = EchoAdapter({"response": json.dumps(payload)})

    result = runner.run_stage(workspace, "demo", "character_creation", llm=llm)

    cast = schemas.load_cast(stage_dir(workspace, STAGE8) / "cast.json")
    assert cast.get("protagonist").name != ""
    assert any("rejected" in note.lower() for note in result.notes)


def test_locked_fields_survive_a_stage_rerun(workspace, sheet):
    runner.run_stage(workspace, "demo", "character_creation")
    cast_path = stage_dir(workspace, STAGE8) / "cast.json"
    existing = schemas.load_cast(cast_path)
    protagonist = existing.get("protagonist")
    data = existing.to_dict()
    for character in data["characters"]:
        if character["id"] == "protagonist":
            character["locked"] = ["name"]
    cast_path.write_text(json.dumps(data), encoding="utf-8")

    renamed = sheet(id="protagonist", name="A Completely Different Name", role="protagonist")
    llm = EchoAdapter({"response": json.dumps({"characters": [renamed]})})
    runner.run_stage(workspace, "demo", "character_creation", llm=llm)

    after = schemas.load_cast(cast_path).get("protagonist")
    assert after.name == protagonist.name
    assert after.locked == ("name",)


def test_rerunning_an_unapproved_stage_is_allowed(workspace):
    runner.run_stage(workspace, "demo", "character_creation")
    second = runner.run_stage(workspace, "demo", "character_creation")

    assert second.status == runner.DONE
    assert (stage_dir(workspace, STAGE8) / "output.md").is_file()


def test_an_approved_stage_is_not_overwritten_without_force(workspace):
    runner.run_stage(workspace, "demo", "character_creation")
    meta_path = stage_dir(workspace, STAGE8) / "meta.json"
    meta = read_meta(workspace, STAGE8)
    meta["approved"] = True
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    with pytest.raises(runner.StoryError, match="approved"):
        runner.run_stage(workspace, "demo", "character_creation")

    assert runner.run_stage(workspace, "demo", "character_creation", force=True).status == runner.DONE


def test_ensemble_check_runs_after_character_creation(workspace):
    runner.run_stage(workspace, "demo", "character_creation")

    result = runner.run_stage(workspace, "demo", "ensemble_check")

    assert result.status == runner.NEEDS_APPROVAL
    assert result.meta["human_gate"] == 1
    assert result.meta["status"] == "done"
    output = (stage_dir(workspace, STAGE9) / "output.md").read_text(encoding="utf-8")
    assert "Ensemble" in output


def test_ensemble_check_needs_character_creation(workspace):
    with pytest.raises(runner.StoryError, match="character_creation"):
        runner.run_stage(workspace, "demo", "ensemble_check")


def test_ensemble_check_flags_a_bad_cast(workspace, bad_cast):
    runner.run_stage(workspace, "demo", "character_creation")
    (stage_dir(workspace, STAGE8) / "cast.json").write_text(json.dumps(bad_cast()), encoding="utf-8")

    result = runner.run_stage(workspace, "demo", "ensemble_check")

    assert result.status == runner.FAILED
    assert result.meta["status"] == "failed"
    assert result.meta["error"]
    assert "shared_voice_tic" in result.meta["error"]
    output = (stage_dir(workspace, STAGE9) / "output.md").read_text(encoding="utf-8")
    assert "shared_voice_tic" in output


def test_an_invalid_cast_file_is_reported(workspace, sheet):
    runner.run_stage(workspace, "demo", "character_creation")
    (stage_dir(workspace, STAGE8) / "cast.json").write_text(
        json.dumps({"characters": [sheet(id="x", role="protagonist", emotional_core={"want": ""})]}),
        encoding="utf-8",
    )

    with pytest.raises(runner.StoryError, match="invalid"):
        runner.run_stage(workspace, "demo", "ensemble_check")


def test_approve_gate_marks_the_stage_done(workspace):
    runner.run_stage(workspace, "demo", "character_creation")
    runner.run_stage(workspace, "demo", "ensemble_check")

    result = runner.approve_gate(workspace, "demo", "1")

    assert result.status == runner.DONE
    assert read_meta(workspace, STAGE9)["approved"] is True
    project = workspace / "projects" / "demo"
    state = runner.stage_state(project, runner.resolve_stage("ensemble_check"))
    assert state.status == runner.DONE


def test_approve_requires_the_gate_stage_to_have_run(workspace):
    with pytest.raises(runner.StoryError, match="run"):
        runner.approve_gate(workspace, "demo", "1")


def test_approve_refuses_a_failed_ensemble_check(workspace, bad_cast):
    runner.run_stage(workspace, "demo", "character_creation")
    (stage_dir(workspace, STAGE8) / "cast.json").write_text(json.dumps(bad_cast()), encoding="utf-8")
    runner.run_stage(workspace, "demo", "ensemble_check")

    with pytest.raises(runner.StoryError, match="failed"):
        runner.approve_gate(workspace, "demo", "1")

    assert runner.approve_gate(workspace, "demo", "1", force=True).status == runner.DONE


def test_later_gates_name_their_milestone(workspace):
    with pytest.raises(runner.StoryError, match="M6"):
        runner.approve_gate(workspace, "demo", "2")


def test_stages_without_a_skill_are_not_runnable(workspace):
    with pytest.raises(runner.StoryError, match="not built"):
        runner.run_stage(workspace, "demo", "series_bible")
