"""M6: `story rules merge` validates additive rules and never overwrites an existing entry."""

from __future__ import annotations

import copy
import json

from pipeline import cli, ledger, runner

BASE_RULES = {
    "system_type": "litrpg",
    "xp": {"curve": "triangular", "per_level": 100, "max_level": 3, "thresholds": {"1": 0, "2": 100, "3": 300}},
    "skills": {"ledger-sight": {"unlocks_at_level": 2, "requires": []}},
    "items": {"ledger": {"name": "the ledger", "sources": []}, "wax-seal": {"name": "a wax seal", "sources": []}},
    "recipes": [],
    "locations": {"record-office": {"name": "The record office", "exits": {"market": {"minutes": 10}}},
                  "market": {"name": "The market", "exits": {"record-office": {"minutes": 10}}}},
    "start_location": "record-office",
}


def base_rules():
    return copy.deepcopy(BASE_RULES)


ADDITIONS = {
    "items": {
        "chapter-dossier": {"name": "the dossier", "sources": ["recipe:bind-the-dossier"]},
        "witness-statement": {"name": "a witness statement", "sources": []},
    },
    "recipes": [
        {
            "id": "bind-the-dossier",
            "produces": "chapter-dossier",
            "ingredients": {"ledger": 1, "witness-statement": 1},
            "requires_skill": None,
            "minutes": 45,
        }
    ],
    "skills": {
        "ledger-sight-under-pressure": {
            "name": "ledger sight under pressure",
            "unlocks_at_level": 3,
            "requires": ["ledger-sight"],
            "requires_items": [],
        }
    },
    "locations": {
        "the-river-engineering": {"name": "The river engineering", "exits": {"record-office": {"minutes": 25}}}
    },
}


def test_merge_adds_new_entries_and_reports_the_diff():
    rules = base_rules()

    result = ledger.merge_rules(rules, ADDITIONS)

    assert result.ok, result.errors
    assert any("item chapter-dossier" in entry for entry in result.added)
    assert any("recipe bind-the-dossier" in entry for entry in result.added)
    assert any("location the-river-engineering" in entry for entry in result.added)
    assert any("skill ledger-sight-under-pressure" in entry for entry in result.added)
    assert result.rules["items"]["chapter-dossier"]["sources"] == ["recipe:bind-the-dossier"]
    assert result.rules["recipes"][0]["id"] == "bind-the-dossier"
    assert result.rules["skills"]["ledger-sight-under-pressure"]["requires"] == ["ledger-sight"]
    assert "the-river-engineering" in result.rules["locations"]
    # the input is not mutated
    assert "chapter-dossier" not in rules["items"]


def test_merge_never_overwrites_an_existing_entry():
    rules = base_rules()
    additions = {
        "items": {"ledger": {"name": "a completely different ledger", "sources": ["somewhere"]}},
        "skills": {"ledger-sight": {"unlocks_at_level": 1, "requires": []}},
        "locations": {"market": {"name": "The other market", "exits": {}}},
    }

    result = ledger.merge_rules(rules, additions)

    assert result.ok
    assert result.added == []
    assert any("item ledger" in entry for entry in result.kept)
    assert result.rules["items"]["ledger"]["name"] == "the ledger"
    assert result.rules["locations"]["market"]["name"] == "The market"
    assert result.rules["skills"]["ledger-sight"]["unlocks_at_level"] == 2


def test_merge_rejects_an_addition_that_breaks_the_rules_schema():
    rules = base_rules()
    additions = {
        "recipes": [
            {"id": "ghost-recipe", "produces": "no-such-item", "ingredients": {"ledger": 1}}
        ]
    }

    result = ledger.merge_rules(rules, additions)

    assert not result.ok
    assert any("no-such-item" in error for error in result.errors)
    assert "ghost-recipe" not in {recipe["id"] for recipe in result.rules["recipes"]}


def test_merge_rejects_keys_that_are_not_additive():
    result = ledger.merge_rules(base_rules(), {"xp": {"thresholds": {"4": 900}}})

    assert not result.ok
    assert any("xp" in error for error in result.errors)


def test_merge_rejects_a_recipe_ingredient_that_does_not_exist():
    additions = {
        "recipes": [
            {"id": "spin-gold", "produces": "ledger", "ingredients": {"straw": 3}}
        ]
    }

    result = ledger.merge_rules(base_rules(), additions)

    assert not result.ok
    assert any("straw" in error for error in result.errors)


def test_merge_is_idempotent():
    first = ledger.merge_rules(base_rules(), ADDITIONS)
    second = ledger.merge_rules(first.rules, ADDITIONS)

    assert second.ok
    assert second.added == []
    assert len(second.kept) == len(first.added)
    assert len(second.rules["recipes"]) == 1


def test_format_merge_diff_prints_plus_and_equals_lines():
    result = ledger.merge_rules(base_rules(), ADDITIONS)

    diff = ledger.format_merge_diff(result)

    assert "+ item chapter-dossier" in diff
    assert "recipe bind-the-dossier" in diff


# --------------------------------------------------------------------------- CLI


def build_bible_and_outline(root):
    runner.run_stage(root, "demo", "character_creation")
    runner.run_stage(root, "demo", "series_bible")
    return runner.run_stage(root, "demo", "outline")


def rules_path(root):
    return root / "projects" / "demo" / "stages" / "10-series_bible" / "rules.json"


def test_cli_rules_merge_uses_the_outline_additions_by_default(workspace, capsys):
    build_bible_and_outline(workspace)
    before = json.loads(rules_path(workspace).read_text(encoding="utf-8"))

    assert cli.main(["--root", str(workspace), "rules", "merge"]) == 0

    out = capsys.readouterr().out
    assert "+" in out
    after = json.loads(rules_path(workspace).read_text(encoding="utf-8"))
    assert set(after["items"]) > set(before["items"])
    assert after["locations"] != before["locations"]


def test_cli_rules_merge_is_idempotent(workspace, capsys):
    build_bible_and_outline(workspace)
    assert cli.main(["--root", str(workspace), "rules", "merge"]) == 0
    capsys.readouterr()

    assert cli.main(["--root", str(workspace), "rules", "merge"]) == 0

    out = capsys.readouterr().out
    assert "kept existing" in out
    assert "+" not in out


def test_cli_rules_merge_rejects_bad_additions_and_leaves_rules_alone(workspace, capsys, tmp_path):
    build_bible_and_outline(workspace)
    before = rules_path(workspace).read_text(encoding="utf-8")
    bad = tmp_path / "additions.json"
    bad.write_text(
        json.dumps({"recipes": [{"id": "bad", "produces": "nowhere", "ingredients": {"x": 1}}]}),
        encoding="utf-8",
    )

    assert cli.main(["--root", str(workspace), "rules", "merge", str(bad)]) == 1

    assert "nowhere" in capsys.readouterr().err
    assert rules_path(workspace).read_text(encoding="utf-8") == before


def test_cli_rules_merge_wants_the_bible_first(workspace, capsys):
    assert cli.main(["--root", str(workspace), "rules", "merge"]) == 1
    assert "series_bible" in capsys.readouterr().err
