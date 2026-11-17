"""M5: the ledger delta engine - item sources, XP thresholds, prerequisites and paths."""

from __future__ import annotations

import copy

import pytest

from pipeline import ledger, schemas


RULES = {
    "system_type": "litrpg",
    "xp": {
        "curve": "triangular",
        "per_level": 100,
        "max_level": 5,
        "thresholds": {"1": 0, "2": 100, "3": 300, "4": 600, "5": 1000},
    },
    "skills": {
        "ledger-sight": {"name": "Ledger sight", "unlocks_at_level": 2, "requires": []},
        "sealed-reading": {
            "name": "Sealed reading",
            "unlocks_at_level": 3,
            "requires": ["ledger-sight"],
        },
    },
    "items": {
        "ledger": {"name": "The ledger", "sources": []},
        "wax-seal": {"name": "A wax seal", "sources": []},
        "sealed-ledger": {"name": "The sealed ledger", "sources": ["recipe:seal-the-ledger"]},
    },
    "recipes": [
        {
            "id": "seal-the-ledger",
            "produces": "sealed-ledger",
            "ingredients": {"ledger": 1, "wax-seal": 1},
            "requires_skill": None,
            "minutes": 30,
        }
    ],
    "locations": {
        "record-office": {"name": "The record office", "exits": {"market": {"minutes": 10}}},
        "market": {"name": "The market", "exits": {"record-office": {"minutes": 10}}},
        "river-dock": {"name": "The river dock", "exits": {}},
    },
    "start_location": "record-office",
}


def make_ledger(**entities):
    """A one-character ledger; pass entity values to change xp, level, inventory or location."""
    story = {
        "chapter": 0,
        "entities": {
            "protagonist": {
                "level": 1,
                "xp": 0,
                "skills": {},
                "inventory": [],
                "location": "record-office",
            }
        },
        "events": [],
        "applied_deltas": [],
    }
    for entity_id, values in entities.items():
        entity = story["entities"].setdefault(
            entity_id,
            {"level": 1, "xp": 0, "skills": {}, "inventory": [], "location": "record-office"},
        )
        entity.update(values)
    return story


def delta(ops, chapter=1):
    return {"chapter": chapter, "ops": ops}


def joined(report):
    return " | ".join(report.errors)


def none_rules():
    """The same story with no stat system at all (system_type: none)."""
    rules = copy.deepcopy(RULES)
    rules["system_type"] = "none"
    rules["xp"] = {"curve": "none", "per_level": 0, "max_level": 0, "thresholds": {}}
    rules["skills"] = {}
    return rules


def test_a_valid_crafting_chain_passes():
    story = make_ledger()

    applied = ledger.apply_delta(
        story,
        RULES,
        delta(
            [
                {"op": "event", "id": "found-ledger", "summary": "Mara finds the ledger"},
                {
                    "op": "add_item",
                    "entity": "protagonist",
                    "item": "ledger",
                    "source": "found-ledger",
                },
                {"op": "event", "id": "bought-seal", "summary": "Mara buys a wax seal"},
                {
                    "op": "add_item",
                    "entity": "protagonist",
                    "item": "wax-seal",
                    "source": "bought-seal",
                },
                {
                    "op": "add_item",
                    "entity": "protagonist",
                    "item": "sealed-ledger",
                    "recipe": "seal-the-ledger",
                },
            ]
        ),
    )

    inventory = applied["entities"]["protagonist"]["inventory"]
    assert inventory.count("sealed-ledger") == 1
    assert "ledger" not in inventory
    assert "wax-seal" not in inventory


def test_an_item_from_nowhere_is_rejected():
    report = ledger.validate_delta(
        make_ledger(),
        RULES,
        delta([{"op": "add_item", "entity": "protagonist", "item": "ledger"}]),
    )

    assert not report.ok
    assert "nowhere" in joined(report)


def test_an_unknown_source_is_rejected():
    report = ledger.validate_delta(
        make_ledger(),
        RULES,
        delta(
            [
                {
                    "op": "add_item",
                    "entity": "protagonist",
                    "item": "ledger",
                    "source": "because the plot says so",
                }
            ]
        ),
    )

    assert not report.ok
    assert "source" in joined(report).lower() or "nowhere" in joined(report)


def test_a_recipe_without_its_ingredients_is_rejected():
    story = make_ledger(
        protagonist={"inventory": ["ledger"]},
    )

    report = ledger.validate_delta(
        story,
        RULES,
        delta(
            [
                {
                    "op": "add_item",
                    "entity": "protagonist",
                    "item": "sealed-ledger",
                    "recipe": "seal-the-ledger",
                }
            ]
        ),
    )

    assert not report.ok
    assert "wax-seal" in joined(report)


def test_level_up_thresholds_are_enforced():
    above_the_line = make_ledger(protagonist={"level": 2, "xp": 120})

    too_far = ledger.validate_delta(
        above_the_line,
        RULES,
        delta([{"op": "level_up", "entity": "protagonist", "level": 3}]),
    )
    assert not too_far.ok
    assert "300" in joined(too_far)

    story = make_ledger(protagonist={"xp": 120})
    applied = ledger.apply_delta(
        story, RULES, delta([{"op": "level_up", "entity": "protagonist", "level": 2}])
    )
    assert applied["entities"]["protagonist"]["level"] == 2


def test_a_level_up_must_raise_exactly_one_level():
    story = make_ledger(protagonist={"xp": 1000})

    report = ledger.validate_delta(
        story, RULES, delta([{"op": "level_up", "entity": "protagonist", "level": 4}])
    )

    assert not report.ok
    assert "one level" in joined(report)


def test_a_skill_unlock_needs_its_prerequisites():
    story = make_ledger(protagonist={"level": 3, "xp": 300})

    premature = ledger.validate_delta(
        story, RULES, delta([{"op": "skill_unlock", "entity": "protagonist", "skill": "sealed-reading"}])
    )
    assert not premature.ok
    assert "ledger-sight" in joined(premature)

    learned = ledger.apply_delta(
        story,
        RULES,
        delta(
            [
                {"op": "skill_unlock", "entity": "protagonist", "skill": "ledger-sight"},
                {"op": "skill_unlock", "entity": "protagonist", "skill": "sealed-reading"},
            ]
        ),
    )
    assert set(learned["entities"]["protagonist"]["skills"]) == {"ledger-sight", "sealed-reading"}


def test_a_move_along_a_nonexistent_path_is_rejected():
    report = ledger.validate_delta(
        make_ledger(),
        RULES,
        delta([{"op": "move", "entity": "protagonist", "to": "river-dock"}]),
    )

    assert not report.ok
    assert "no path" in joined(report).lower()


def test_a_valid_move_updates_the_location_and_reports_the_travel_time():
    applied = ledger.apply_delta(
        make_ledger(),
        RULES,
        delta([{"op": "move", "entity": "protagonist", "to": "market"}]),
    )

    assert applied["entities"]["protagonist"]["location"] == "market"


def test_an_unknown_entity_and_an_unknown_location_are_rejected():
    ghost = ledger.validate_delta(
        make_ledger(),
        RULES,
        delta([{"op": "move", "entity": "ghost", "to": "market"}]),
    )
    assert not ghost.ok
    assert "unknown entity" in joined(ghost)

    atlantis = ledger.validate_delta(
        make_ledger(),
        RULES,
        delta([{"op": "move", "entity": "protagonist", "to": "atlantis"}]),
    )
    assert not atlantis.ok
    assert "unknown location" in joined(atlantis)


def test_system_type_none_skips_stat_checks():
    story = make_ledger(protagonist={"level": 0})

    report = ledger.validate_delta(
        story,
        none_rules(),
        delta(
            [
                {"op": "xp_gain", "entity": "protagonist", "amount": 5},
                {"op": "level_up", "entity": "protagonist", "level": 7},
                {"op": "skill_unlock", "entity": "protagonist", "skill": "shrugs off numbers"},
            ]
        ),
    )

    assert report.ok
    assert any("no stat system" in note for note in report.notes)


def test_reapplying_a_delta_is_rejected():
    story = make_ledger()
    once = delta([{"op": "event", "id": "the-body", "summary": "a body is found"}])

    applied = ledger.apply_delta(story, RULES, once)
    again = ledger.validate_delta(applied, RULES, once)

    assert not again.ok
    assert "already applied" in joined(again)


def test_apply_delta_refuses_an_invalid_delta():
    with pytest.raises(ledger.LedgerError, match="nowhere"):
        ledger.apply_delta(
            make_ledger(),
            RULES,
            delta([{"op": "add_item", "entity": "protagonist", "item": "ledger"}]),
        )


def test_apply_delta_returns_a_new_ledger_and_leaves_the_input_alone():
    story = make_ledger()

    applied = ledger.apply_delta(
        story, RULES, delta([{"op": "event", "id": "start", "summary": "chapter one"}])
    )

    assert story["events"] == []
    assert story["applied_deltas"] == []
    assert applied["chapter"] == 1
    assert [event["id"] for event in applied["events"]] == ["start"]


def test_a_delta_with_an_unknown_op_is_rejected():
    report = ledger.validate_delta(
        make_ledger(), RULES, delta([{"op": "set_the_world_on_fire", "entity": "protagonist"}])
    )

    assert not report.ok
    assert "set_the_world_on_fire" in joined(report)


def test_initial_ledger_has_every_character_and_the_start_location(sheet):
    cast = schemas.cast_from_dict(
        {
            "characters": [
                sheet(id="protagonist", name="Mara Voss", role="protagonist"),
                sheet(id="ally", name="Perrin Vale", role="ally"),
            ]
        }
    )

    story = ledger.initial_ledger(cast, RULES)

    assert set(story["entities"]) == {"protagonist", "ally"}
    assert story["entities"]["ally"]["location"] == "record-office"
    assert story["entities"]["protagonist"]["level"] == 1
    assert story["chapter"] == 0
    assert story["events"] == []


def test_rules_round_trip_through_json(tmp_path):
    path = ledger.save_rules(RULES, tmp_path / "rules.json")

    loaded = ledger.load_rules(path)

    assert loaded["system_type"] == "litrpg"
    assert loaded["xp"]["thresholds"][3] == 300
    assert loaded["recipes"][0]["ingredients"] == {"ledger": 1, "wax-seal": 1}
    assert loaded["locations"]["market"]["exits"]["record-office"]["minutes"] == 10


def test_validate_rules_rejects_a_bad_system_type():
    with pytest.raises(ledger.RulesError, match="system_type"):
        ledger.validate_rules({"system_type": "gurps"})


def test_build_rules_detects_litrpg_and_lists_thresholds(sheet):
    cast = schemas.cast_from_dict({"characters": [sheet(id="protagonist", talent="counts debts")]})

    rules = ledger.build_rules({"genre": "litrpg cultivation", "premise_seed": ""}, cast)

    assert rules["system_type"] == "litrpg"
    assert rules["xp"]["thresholds"]
    assert rules["xp"]["max_level"] >= 3


def test_build_rules_for_a_plain_genre_has_no_stat_system(sheet):
    cast = schemas.cast_from_dict({"characters": [sheet(id="protagonist", talent="counts debts")]})

    rules = ledger.build_rules({"genre": "cozy mystery", "premise_seed": ""}, cast)

    assert rules["system_type"] == "none"
    assert rules["xp"]["thresholds"] == {}
    assert rules["locations"]
    assert rules["items"]


def test_build_rules_gives_every_talent_a_skill_with_a_second_tier(sheet):
    cast = schemas.cast_from_dict(
        {
            "characters": [
                sheet(id="protagonist", talent="remembers every debt"),
                sheet(id="ally", role="ally", talent="reads a room"),
            ]
        }
    )

    rules = ledger.build_rules({"genre": "litrpg", "premise_seed": ""}, cast)

    assert "remembers-every-debt" in rules["skills"]
    assert rules["skills"]["remembers-every-debt"]["unlocks_at_level"] == 2
    assert rules["skills"]["remembers-every-debt-mastery"]["requires"] == ["remembers-every-debt"]


def test_a_generated_rules_file_is_walkable(sheet):
    cast = schemas.cast_from_dict({"characters": [sheet(id="protagonist", talent="counts debts")]})

    rules = ledger.build_rules({"genre": "fantasy"}, cast)
    ledger.validate_rules(rules)

    for location, node in rules["locations"].items():
        for target, exit_ in node["exits"].items():
            assert target in rules["locations"], f"{location} exits to unknown {target}"
            assert exit_["minutes"] >= 0
    assert rules["start_location"] in rules["locations"]
    for recipe in rules["recipes"]:
        assert recipe["produces"] in rules["items"]
