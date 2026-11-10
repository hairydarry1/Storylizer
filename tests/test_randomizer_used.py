"""M2: tables/used.json remembers picks across projects."""

from __future__ import annotations

import json

from pipeline import randomizer, runner


def rnd(root, slug):
    return randomizer.Randomizer(root, slug, runner.load_config(root))


def used(root):
    return json.loads((root / "tables" / "used.json").read_text(encoding="utf-8"))["used"]


def test_a_roll_records_the_pick_in_tables_used_json(workspace):
    result = rnd(workspace, "demo").roll_stage(8)
    picks = used(workspace)

    given = next(r.value for r in result.rolls if r.table == "names_given")
    records = picks["names_given"]
    assert records[0]["value"] == given
    assert records[0]["project"] == "demo"
    assert records[0]["stage"] == "08-character_creation"


def test_a_second_project_does_not_reuse_the_first_projects_picks(workspace):
    runner.init_project(workspace, "second")

    first = rnd(workspace, "demo").roll_stage(8)
    second = rnd(workspace, "second").roll_stage(8)

    first_values = {r.table: r.value for r in first.rolls}
    second_values = {r.table: r.value for r in second.rolls}
    for table in ("names_given", "names_family", "quirks", "flaws", "talents"):
        assert second_values[table] != first_values[table]

    picks = used(workspace)
    assert {record["project"] for record in picks["quirks"]} == {"demo", "second"}


def test_reuse_is_allowed_once_every_entry_has_been_used(workspace):
    """A small table must not deadlock the pipeline."""
    tables = workspace / "tables"
    (tables / "quirks.json").write_text(
        json.dumps(
            {
                "name": "quirks",
                "entries": [
                    {"value": "whistles at bad news", "weight": 1, "tags": []},
                    {"value": "counts exits", "weight": 1, "tags": []},
                ],
            }
        ),
        encoding="utf-8",
    )
    runner.init_project(workspace, "second")

    first = rnd(workspace, "demo").roll_stage(8)
    second = rnd(workspace, "second").roll_stage(8)

    values = {r.value for r in first.rolls + second.rolls if r.table == "quirks"}
    assert values == {"whistles at bad news", "counts exits"}


def test_used_json_only_lists_tables_that_were_rolled(workspace):
    rnd(workspace, "demo").roll_stage(8)

    picks = used(workspace)

    assert "weather" not in picks
    assert picks["names_given"]


def test_a_corrupt_used_file_does_not_stop_a_roll(workspace):
    path = workspace / "tables" / "used.json"
    path.write_text("{not json", encoding="utf-8")

    result = rnd(workspace, "demo").roll_stage(8)

    assert result.rolls
    assert used(workspace)["names_given"]
