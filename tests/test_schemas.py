"""M3: character sheets and casts validate per BUILD_SPEC.md section 4."""

from __future__ import annotations

import pytest

from pipeline import schemas


def test_a_valid_sheet_parses_and_round_trips(sheet):
    character = schemas.character_from_dict(sheet())

    assert character.id == "mara"
    assert character.role == "protagonist"
    assert character.look.marks[0].placement == "right palm"
    assert character.intelligence_profile.sharp_at == ("ledgers", "who owes whom")
    assert character.emotional_core.stakes.startswith("the only copy")

    again = schemas.character_from_dict(character.to_dict())
    assert again == character


def test_a_missing_required_field_is_rejected(sheet):
    data = sheet()
    del data["name"]

    with pytest.raises(schemas.SchemaError, match="name"):
        schemas.character_from_dict(data)


def test_an_unknown_role_is_rejected(sheet):
    with pytest.raises(schemas.SchemaError, match="role"):
        schemas.character_from_dict(sheet(role="love interest"))


def test_an_unknown_locked_field_is_rejected(sheet):
    with pytest.raises(schemas.SchemaError, match="locked"):
        schemas.character_from_dict(sheet(locked=["favourite_food"]))


def test_a_numeric_iq_field_is_rejected(sheet):
    with pytest.raises(schemas.SchemaError, match="IQ"):
        schemas.character_from_dict(sheet(iq=142))


def test_a_numeric_iq_field_nested_anywhere_is_rejected(sheet):
    data = sheet()
    data["look"]["marks"][0]["measured_iq"] = 118

    with pytest.raises(schemas.SchemaError, match="IQ"):
        schemas.character_from_dict(data)


def test_a_numeric_intelligence_quotient_is_rejected(sheet):
    data = sheet()
    data["stats"] = {"intelligence_quotient": 131, "notes": "keep this out of the sheet"}

    with pytest.raises(schemas.SchemaError, match="IQ"):
        schemas.character_from_dict(data)


def test_the_intelligence_profile_is_the_supported_alternative(sheet):
    character = schemas.character_from_dict(sheet())

    assert character.intelligence_profile.overconfident_about == ("her memory for faces",)


def test_a_secondary_character_needs_its_own_want(sheet):
    data = sheet(role="ally", emotional_core={"want": ""})

    with pytest.raises(schemas.SchemaError, match="want"):
        schemas.character_from_dict(data)


def test_a_secondary_character_needs_its_own_stakes(sheet):
    data = sheet(role="mentor", emotional_core={"stakes": ""})

    with pytest.raises(schemas.SchemaError, match="stakes"):
        schemas.character_from_dict(data)


def test_the_protagonist_may_omit_stakes(sheet):
    character = schemas.character_from_dict(sheet(role="protagonist", emotional_core={"stakes": ""}))

    assert character.emotional_core.want


def test_relationships_must_point_at_existing_characters(sheet):
    cast = {"characters": [sheet(relationships=[{"to": "ghost", "bond": "old friend", "friction": "none"}])]}

    with pytest.raises(schemas.SchemaError, match="ghost"):
        schemas.cast_from_dict(cast)


def test_a_relationship_to_a_real_character_is_fine(sheet):
    cast = schemas.cast_from_dict(
        {
            "characters": [
                sheet(id="mara", name="Mara", role="protagonist"),
                sheet(
                    id="ivo",
                    name="Ivo",
                    role="ally",
                    relationships=[{"to": "mara", "bond": "sibling", "friction": "the ledger"}],
                ),
            ]
        }
    )

    assert cast.get("ivo").relationships[0].to == "mara"


def test_duplicate_character_ids_are_rejected(sheet):
    cast = {"characters": [sheet(id="mara"), sheet(id="mara", name="Other Mara")]}

    with pytest.raises(schemas.SchemaError, match="duplicate"):
        schemas.cast_from_dict(cast)


def test_an_empty_cast_is_rejected():
    with pytest.raises(schemas.SchemaError, match="at least one"):
        schemas.cast_from_dict({"characters": []})


def test_locked_fields_survive_regeneration(sheet):
    previous = schemas.character_from_dict(sheet(locked=["name", "voice.rhythm"]))
    candidate = schemas.character_from_dict(
        sheet(name="Someone Else", voice={"rhythm": "meandering"}, occupation="cartographer")
    )

    merged, kept = schemas.merge_locked(previous, candidate)

    assert merged.name == "Mara Voss"
    assert merged.voice.rhythm == "clipped"
    assert merged.occupation == "cartographer"
    assert set(kept) == {"name", "voice.rhythm"}
    assert merged.locked == ("name", "voice.rhythm")


def test_regeneration_may_not_change_the_id(sheet):
    previous = schemas.character_from_dict(sheet())
    candidate = schemas.character_from_dict(sheet(id="other"))

    with pytest.raises(schemas.SchemaError, match="id"):
        schemas.merge_locked(previous, candidate)


def test_unlocked_sheets_are_free_to_change(sheet):
    previous = schemas.character_from_dict(sheet())
    candidate = schemas.character_from_dict(sheet(name="Mara Venn"))

    merged, kept = schemas.merge_locked(previous, candidate)

    assert merged.name == "Mara Venn"
    assert kept == ()
