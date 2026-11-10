"""M3: ensemble checks (BUILD_SPEC.md section 8): code first, checker model second."""

from __future__ import annotations

import json

from pipeline import ensemble, schemas
from pipeline.adapters.echo import EchoAdapter


def good_cast(sheet):
    return schemas.cast_from_dict(
        {
            "characters": [
                sheet(
                    id="mara",
                    name="Mara Voss",
                    role="protagonist",
                    age=34,
                    gender="woman",
                    voice={"rhythm": "clipped", "tics": ["taps a pen twice"], "vocabulary": "precise"},
                ),
                sheet(
                    id="ivo",
                    name="Ivo Sarn",
                    role="ally",
                    age=61,
                    gender="man",
                    voice={"rhythm": "meandering", "tics": ["hums before disagreeing"], "vocabulary": "wide"},
                    emotional_core={"want": "to finish the index", "stakes": "the last person who trusts him"},
                    relationships=[{"to": "mara", "bond": "sibling", "friction": "the ledger"}],
                ),
                sheet(
                    id="sena",
                    name="Sena Oduya",
                    role="pressure",
                    age=23,
                    gender="non-binary",
                    voice={"rhythm": "quick and dry", "tics": ["quotes prices in old currency"], "vocabulary": "plain"},
                    emotional_core={"want": "to get out of town", "stakes": "a sibling who works for the council"},
                    relationships=[{"to": "mara", "bond": "rival", "friction": "who owns the record"}],
                ),
            ]
        }
    )


def test_a_deliberately_bad_cast_is_flagged(bad_cast):
    report = ensemble.check_ensemble(schemas.cast_from_dict(bad_cast()))

    codes = {issue.code for issue in report.issues}
    assert "cast_one_age" in codes
    assert "cast_one_gender" in codes
    assert "cast_one_temperament" in codes
    assert "shared_voice_tic" in codes
    assert "too_many_quirky_and_clever" in codes
    assert report.passed is False


def test_a_varied_cast_passes_the_code_checks(sheet):
    report = ensemble.check_ensemble(good_cast(sheet))

    assert report.passed is True
    assert report.issues == []
    assert report.notes == []


def test_a_shared_voice_tic_names_both_characters(sheet):
    cast = schemas.cast_from_dict(
        {
            "characters": [
                sheet(id="a", name="A", role="protagonist", voice={"rhythm": "clipped", "tics": ["says 'right' after every question"]}),
                sheet(
                    id="b",
                    name="B",
                    role="ally",
                    age=50,
                    gender="man",
                    voice={"rhythm": "measured", "tics": ["Says 'Right' after every question"]},
                    emotional_core={"want": "to be taken seriously", "stakes": "the shop"},
                ),
            ]
        }
    )

    report = ensemble.check_ensemble(cast)

    issues = [issue for issue in report.issues if issue.code == "shared_voice_tic"]
    assert len(issues) == 1
    assert set(issues[0].characters) == {"a", "b"}


def test_one_quirky_character_is_not_too_many(sheet):
    cast = schemas.cast_from_dict(
        {
            "characters": [
                sheet(id="a", name="A", role="protagonist", tags=["quirky and clever"]),
                sheet(
                    id="b",
                    name="B",
                    role="ally",
                    age=50,
                    gender="man",
                    voice={"rhythm": "measured", "tics": ["hums"]},
                    emotional_core={"want": "to be taken seriously", "stakes": "the shop"},
                ),
            ]
        }
    )

    report = ensemble.check_ensemble(cast)

    assert "too_many_quirky_and_clever" not in {issue.code for issue in report.issues}


def test_judgment_checks_use_the_checker_tier(sheet):
    llm = EchoAdapter({"response": "echo"})

    report = ensemble.check_ensemble(good_cast(sheet), llm)

    assert llm.calls[0]["model_tier"] == "checker"
    prompt = llm.calls[0]["prompt"].lower()
    for topic in ("want", "stake", "flaw", "stereotype"):
        assert topic in prompt
    assert report.notes, "an unusable checker reply has to be reported, not silently accepted"
    assert "echo" in report.notes[0]


def test_judgment_issues_from_the_checker_are_flagged(sheet):
    reply = json.dumps(
        {
            "issues": [
                {
                    "kind": "conflicting_wants",
                    "characters": ["mara", "sena"],
                    "detail": "both want the same record and neither can share it",
                }
            ]
        }
    )
    llm = EchoAdapter({"response": reply})

    report = ensemble.check_ensemble(good_cast(sheet), llm)

    codes = {issue.code for issue in report.issues}
    assert "judgment_conflicting_wants" in codes
    issue = next(issue for issue in report.issues if issue.code == "judgment_conflicting_wants")
    assert issue.characters == ("mara", "sena")
    assert "same record" in issue.detail
    assert report.passed is False


def test_fenced_judgment_json_is_accepted(sheet):
    reply = "```json\n" + json.dumps({"issues": []}) + "\n```"
    llm = EchoAdapter({"response": reply})

    report = ensemble.check_ensemble(good_cast(sheet), llm)

    assert report.passed is True
    assert not [note for note in report.notes if "json" in note.lower()]
