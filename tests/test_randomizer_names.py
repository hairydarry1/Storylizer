"""M2: names come from phonetic patterns and never land on a banned AI-default name."""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from pipeline import randomizer

TABLES_DIR = Path(__file__).resolve().parents[1] / "tables"

BANNED = {"Elara", "Voss", "Kael", "Lyra", "Thorne"}


@pytest.fixture(scope="module")
def tables():
    return randomizer.Tables(TABLES_DIR)


@pytest.fixture(scope="module")
def names(tables):
    return randomizer.NameGenerator(tables)


def roll_name(names, table, seed):
    rng = random.Random(randomizer.seed_int(seed, "08-character_creation", table))
    return names.given(rng) if table == "names_given" else names.family(rng)


def test_the_banned_table_lists_common_ai_default_names(tables):
    banned = tables.banned_names()

    assert {name.casefold() for name in BANNED} <= banned
    assert all(name == name.strip() for name in banned)


def test_name_tables_are_phonetic_not_fixed_lists(tables):
    """A fixed list would make 'banned names never appear' trivially true."""
    for table in ("names_given", "names_family"):
        loaded = tables.table(table)
        assert loaded.entries == ()
        assert loaded.phonetic, f"{table} has no phonetic block"
        assert loaded.phonetic.get("onset")
        assert loaded.phonetic.get("nucleus")


def test_no_banned_given_name_across_1000_seeds(names):
    generated = {roll_name(names, "names_given", seed) for seed in range(1000)}

    hits = generated & BANNED
    assert not hits, f"banned names were generated: {sorted(hits)}"


def test_no_banned_family_name_across_1000_seeds(names):
    generated = {roll_name(names, "names_family", seed) for seed in range(1000)}

    hits = generated & BANNED
    assert not hits, f"banned names were generated: {sorted(hits)}"


def test_phonetic_names_are_varied(names):
    generated = {roll_name(names, "names_given", seed) for seed in range(1000)}

    assert len(generated) > 300, f"only {len(generated)} distinct given names in 1000 rolls"


def test_names_are_well_formed(names):
    for seed in range(200):
        given = roll_name(names, "names_given", seed)
        family = roll_name(names, "names_family", seed)
        for value in (given, family):
            assert 3 <= len(value) <= 14, value
            assert value[0].isupper(), value
            assert value.replace("-", "").replace("'", "").isalpha(), value
            assert "{" not in value and "}" not in value, value


def test_a_table_that_can_only_produce_a_banned_name_refuses_instead(tmp_path):
    """Better to fail loudly than to hand back a name the spec forbids."""
    tables_dir = tmp_path / "tables"
    tables_dir.mkdir()
    (tables_dir / "names_given.json").write_text(
        """
        {
          "name": "names_given",
          "phonetic": {
            "syllable_patterns": ["{onset}{nucleus}{coda}"],
            "onset": ["k"],
            "nucleus": ["ae"],
            "coda": ["l"],
            "min_syllables": 1,
            "max_syllables": 1
          },
          "entries": []
        }
        """,
        encoding="utf-8",
    )
    (tables_dir / "banned_names.json").write_text(
        '{"name": "banned_names", "entries": [{"value": "Kael", "weight": 1, "tags": []}]}',
        encoding="utf-8",
    )
    generator = randomizer.NameGenerator(randomizer.Tables(tables_dir))

    with pytest.raises(randomizer.RandomizerError, match="banned"):
        generator.given(random.Random(1))


def test_generator_honours_exclusions(names):
    rng = random.Random(5)
    first = names.given(rng)
    second = names.given(random.Random(5), exclude={first})

    assert second != first


def test_tables_report_a_useful_error_for_an_unknown_table(tables):
    with pytest.raises(randomizer.RandomizerError, match="unknown table"):
        tables.table("no_such_table")


def test_tables_directory_must_exist(tmp_path):
    with pytest.raises(randomizer.RandomizerError, match="tables"):
        randomizer.Tables(tmp_path / "nowhere")


def test_the_real_tables_directory_has_every_table_from_the_spec(tables):
    expected = {
        "names_given",
        "names_family",
        "quirks",
        "flaws",
        "talents",
        "blind_spots",
        "physical_marks",
        "emotional_starts",
        "speech_tics",
        "setting_customs",
        "smells_tastes",
        "weather",
        "complications",
        "chapter_shapes",
        "imagery_domains",
        "ending_types",
        "banned_names",
    }

    assert expected <= set(tables.names())


def test_table_files_declare_their_own_name(tables):
    for name in tables.names():
        assert Path(TABLES_DIR / f"{name}.json").is_file()
        assert tables.table(name).name == name
