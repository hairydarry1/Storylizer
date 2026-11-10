"""M2: roll a stage, log it, lock keys, reroll them, and honour the chaos dial."""

from __future__ import annotations

import json

import pytest

from pipeline import randomizer, runner

RECORD_FIELDS = {"stage", "key", "table", "value", "seed", "locked", "timestamp"}


def make(workspace, slug="demo"):
    return randomizer.Randomizer(workspace, slug, runner.load_config(workspace))


def read_log(root, slug="demo"):
    path = root / "projects" / slug / "rolls.json"
    return json.loads(path.read_text(encoding="utf-8"))["rolls"]


def values(rolls):
    return {roll.key: roll.value for roll in rolls}


def test_roll_stage_logs_one_record_per_constraint_with_the_spec_fields(workspace):
    result = make(workspace).roll_stage(8)

    log = read_log(workspace)

    assert len(log) == len(result.rolls) == 5 + runner.load_config(workspace).chaos_dial
    for record in log:
        assert set(record) == RECORD_FIELDS
        assert record["stage"] == "08-character_creation"
        assert record["locked"] is False
        assert isinstance(record["seed"], int)
        assert record["timestamp"].endswith("+00:00")


def test_roll_stage_returns_the_same_values_twice_and_does_not_duplicate_records(workspace):
    first = make(workspace).roll_stage(8)
    second = make(workspace).roll_stage(8)

    assert values(first.rolls) == values(second.rolls)
    assert len(read_log(workspace)) == len(first.rolls)


def test_same_seed_rolls_the_same_values_in_a_fresh_workspace(make_workspace):
    one = make_workspace("one")
    two = make_workspace("two")

    assert values(make(one).roll_stage(8).rolls) == values(make(two).roll_stage(8).rolls)


def test_a_different_seed_rolls_different_values(make_workspace):
    one = make_workspace("one", seed=1)
    two = make_workspace("two", seed=2)

    assert values(make(one).roll_stage(8).rolls) != values(make(two).roll_stage(8).rolls)


def test_chaos_dial_0_applies_fewer_constraints_than_3(make_workspace):
    calm = make(make_workspace("calm", chaos_dial=0))
    wild = make(make_workspace("wild", chaos_dial=3))

    assert len(calm.roll_stage(8).rolls) < len(wild.roll_stage(8).rolls)
    assert len(calm.roll_stage(8).rolls) == 5
    assert len(wild.roll_stage(8).rolls) == 8


def test_chaos_dial_grows_the_outline_stage_too(make_workspace):
    calm = make(make_workspace("calm", chaos_dial=0))
    wild = make(make_workspace("wild", chaos_dial=3))

    assert len(calm.roll_stage(11).rolls) == 3
    assert len(wild.roll_stage(11).rolls) == 6


def test_reroll_changes_the_value_and_keeps_the_history(workspace):
    rnd = make(workspace)
    before = values(rnd.roll_stage(8).rolls)["flaw"]

    rolled = rnd.reroll("flaw")

    after = values(rnd.roll_stage(8).rolls)["flaw"]
    assert rolled.value == after != before
    flaw_records = [r for r in read_log(workspace) if r["key"] == "flaw"]
    assert len(flaw_records) == 2
    assert flaw_records[0]["value"] == before


def test_reroll_only_touches_the_named_key(workspace):
    rnd = make(workspace)
    before = values(rnd.roll_stage(8).rolls)

    rnd.reroll("quirk")

    after = values(rnd.roll_stage(8).rolls)
    assert after["quirk"] != before["quirk"]
    assert {k: v for k, v in after.items() if k != "quirk"} == {
        k: v for k, v in before.items() if k != "quirk"
    }


def test_locked_keys_never_change_on_reroll(workspace):
    rnd = make(workspace)
    before = values(rnd.roll_stage(8).rolls)["flaw"]

    rnd.lock("flaw")
    assert {record["locked"] for record in read_log(workspace) if record["key"] == "flaw"} == {True}

    with pytest.raises(randomizer.RandomizerError, match="locked"):
        rnd.reroll("flaw")

    assert values(rnd.roll_stage(8).rolls)["flaw"] == before


def test_locking_an_unknown_key_is_an_error(workspace):
    with pytest.raises(randomizer.RandomizerError, match="no roll"):
        make(workspace).lock("nope")


def test_rerolling_an_unknown_key_is_an_error(workspace):
    make(workspace).roll_stage(8)

    with pytest.raises(randomizer.RandomizerError, match="no roll"):
        make(workspace).reroll("nope")


def test_reroll_survives_a_fresh_process(workspace):
    """Locks and history live in rolls.json, not in memory."""
    make(workspace).roll_stage(8)
    make(workspace).lock("talent")

    with pytest.raises(randomizer.RandomizerError, match="locked"):
        make(workspace).reroll("talent")


def test_a_project_without_a_rolls_file_is_rolled_from_scratch(workspace):
    (workspace / "projects" / "demo" / "rolls.json").unlink()

    result = make(workspace).roll_stage(8)

    assert result.rolls
    assert read_log(workspace)


def test_stage_references_accept_number_and_names(workspace):
    rnd = make(workspace)

    assert randomizer.resolve_stage("8").dir_name == "08-character_creation"
    assert randomizer.resolve_stage("08").dir_name == "08-character_creation"
    assert randomizer.resolve_stage("character_creation").dir_name == "08-character_creation"
    assert randomizer.resolve_stage("08-character_creation").dir_name == "08-character_creation"
    assert rnd.roll_stage("outline").stage.number == 11


def test_a_stage_without_the_randomizer_is_rejected(workspace):
    with pytest.raises(randomizer.RandomizerError, match="randomizer"):
        make(workspace).roll_stage(1)


def test_unknown_stage_and_project_are_errors(workspace):
    with pytest.raises(randomizer.RandomizerError):
        randomizer.resolve_stage("20-nope")
    with pytest.raises(runner.StoryError):
        randomizer.Randomizer(workspace, "missing")


def test_each_constraint_uses_its_planned_table(workspace):
    rolls = make(workspace).roll_stage(8).rolls

    assert {r.table for r in rolls} >= {"names_given", "names_family", "quirks", "flaws", "talents"}
    assert values(rolls)["protagonist_given_name"]
