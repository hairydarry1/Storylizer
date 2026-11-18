"""M7a: the deterministic linter, its report formats, and `story check`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from pipeline import cli
from pipeline.gates import linter

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def lint(text: str, *, banned_phrases=(), **overrides):
    options = linter.Options.from_mapping(overrides) if overrides else None
    return linter.lint_text(text, options=options, banned_phrases=banned_phrases)


def findings(report, check: str):
    return report.findings[check]


def test_repeated_three_to_five_word_phrases_are_flagged_with_lines():
    text = "\n".join(
        [
            "Mara found the brass key under the mat.",
            "The brass key was cold in her hand.",
            "She turned the brass key twice and waited.",
        ]
    )

    report = lint(text)

    phrases = {finding["phrase"]: finding for finding in findings(report, "repeated_phrases")}
    assert phrases["the brass key"]["count"] == 3
    assert phrases["the brass key"]["lines"] == [1, 2, 3]
    assert report.counts["repeated_phrases"] == 1
    assert report.passed is False


def test_a_two_word_repeat_is_not_a_repeated_phrase():
    text = "The key turned. The key stuck. The key fell."

    report = lint(text)

    assert findings(report, "repeated_phrases") == []


def test_overused_words_are_flagged_but_stopwords_are_ignored():
    text = "\n".join(
        [
            "The lantern swung once.",
            "The lantern swung twice.",
            "The lantern swung again.",
            "The lantern threw light on the wall.",
            "The lantern showed every crack.",
            "The lantern made the room smaller.",
            "The lantern went dark.",
            "The lantern was the only thing she watched.",
        ]
    )

    report = lint(text)

    words = {finding["word"]: finding for finding in findings(report, "overused_words")}
    assert words["lantern"]["count"] == 8
    assert words["lantern"]["per_1000"] >= 8
    assert words["lantern"]["lines"] == list(range(1, 9))
    assert "the" not in words
    assert report.counts["overused_words"] == 1


def test_uniform_sentence_length_is_flagged():
    text = "\n".join(["She walked to the door."] * 10)

    report = lint(text)

    uniform = findings(report, "uniform_sentence_length")
    assert uniform is not None
    assert uniform["stdev"] == pytest.approx(0.0)
    assert uniform["mean"] == pytest.approx(5.0)
    assert uniform["lines"] == list(range(1, 11))
    assert report.counts["uniform_sentence_length"] == 1


def test_varied_sentence_length_is_not_flagged():
    text = " ".join(
        [
            "She ran.",
            "The long corridor bent around a corner she had never noticed before.",
            "Rain hit the glass.",
            "A lamp buzzed above the empty desk while the clock ticked.",
            "He waited.",
            "Nobody came.",
            "The floorboards complained under her boots as she crossed the room.",
            "She left.",
        ]
    )

    report = lint(text)

    assert findings(report, "uniform_sentence_length") is None
    assert report.counts["uniform_sentence_length"] == 0


def test_banned_phrases_are_case_insensitive_and_counted_per_line():
    text = "\n".join(
        [
            "It was A TESTAMENT TO her patience.",
            "The air was thick with smoke and a testament to bad wiring.",
            "Nothing else happened.",
        ]
    )

    report = lint(text, banned_phrases=["a testament to", "the air was thick with"])

    phrases = {finding["phrase"]: finding for finding in findings(report, "banned_phrases")}
    assert phrases["a testament to"]["count"] == 2
    assert phrases["a testament to"]["lines"] == [1, 2]
    assert phrases["the air was thick with"]["count"] == 1
    assert phrases["the air was thick with"]["lines"] == [2]
    assert report.counts["banned_phrases"] == 2


def test_tic_words_are_measured_per_thousand_words_and_match_whole_words():
    text = "\n".join(["She just waited."] * 10 + ["The adjustment held."])

    report = lint(text, tic_words=["just"])

    tics = {finding["word"]: finding for finding in findings(report, "tic_words")}
    assert tics["just"]["count"] == 10
    assert tics["just"]["per_1000"] >= 5
    assert tics["just"]["lines"] == list(range(1, 11))
    assert report.counts["tic_words"] == 1


def test_repeated_paragraph_openers_are_flagged_with_paragraph_lines():
    text = "\n\n".join(
        [
            "She closed the door.",
            "She checked the lock twice.",
            "She counted the windows.",
            "She sat down at last.",
        ]
    )

    report = lint(text)

    openers = {
        finding["opener"]: finding for finding in findings(report, "repeated_paragraph_openers")
    }
    assert openers["she"]["count"] == 4
    assert openers["she"]["lines"] == [1, 3, 5, 7]
    assert report.counts["repeated_paragraph_openers"] == 1


def test_the_json_report_has_counts_lines_and_thresholds():
    report = lint("It was a testament to her patience.\nShe waited.", banned_phrases=["a testament to"])

    payload = report.to_dict()

    assert payload["chapter"] == ""
    assert payload["passed"] is False
    assert payload["words"] == 9
    assert payload["counts"]["banned_phrases"] == 1
    assert payload["findings"]["banned_phrases"][0]["lines"] == [1]
    assert payload["thresholds"]["repeated_phrase_min_count"] == 3
    json.dumps(payload)  # must be JSON-serialisable


def test_the_markdown_summary_names_each_flag_and_its_lines():
    text = "It was a testament to her patience.\nShe waited."

    report = lint(text, banned_phrases=["a testament to"])
    summary = linter.render_markdown(report, title="ch01.md")

    assert "# Linter report: ch01.md" in summary
    assert "- status: failed" in summary
    assert "## Banned phrases" in summary
    assert '"a testament to" x1 (lines 1)' in summary


def test_thresholds_come_from_config_mapping():
    options = linter.Options.from_mapping(
        {
            "repeated_phrase_min_count": 2,
            "overused_word_min_count": 4,
            "tic_per_1000": 2.5,
            "uniform_sentence_stdev": 1.5,
            "uniform_min_sentences": 4,
            "paragraph_opener_min_count": 2,
        }
    )

    assert options.repeated_phrase_min_count == 2
    assert options.overused_word_min_count == 4
    assert options.tic_per_1000 == pytest.approx(2.5)
    assert options.uniform_sentence_stdev == pytest.approx(1.5)
    assert options.uniform_min_sentences == 4
    assert options.paragraph_opener_min_count == 2


def test_the_banned_phrase_table_has_about_forty_ai_tells():
    table = json.loads(
        (PROJECT_ROOT / "tables" / "banned_phrases.json").read_text(encoding="utf-8")
    )
    values = {entry["value"] for entry in table["entries"]}

    assert 38 <= len(values) <= 44
    for phrase in (
        "a testament to",
        "tapestry of",
        "couldn't help but",
        "little did she know",
        "shivers down her spine",
        "the air was thick with",
        "a symphony of",
        "barely above a whisper",
        "heart hammered in her chest",
        "a breath she didn't know she was holding",
    ):
        assert phrase in values


def write_chapter(workspace, text: str, name: str = "ch01.md"):
    path = workspace / "projects" / "demo" / "chapters" / name
    path.write_text(text, encoding="utf-8")
    return path


def write_permissive_gates(workspace):
    config_path = workspace / "config.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["gates"] = {
        "linter": {
            "repeated_phrase_min_count": 99,
            "overused_word_min_count": 99,
            "tic_min_count": 99,
            "paragraph_opener_min_count": 99,
            "uniform_min_sentences": 999,
        }
    }
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")


def test_story_check_writes_json_and_markdown_reports(workspace, capsys):
    write_permissive_gates(workspace)
    write_chapter(
        workspace,
        "She ran.\n\nThe long corridor bent around a corner she had never noticed before. "
        "Rain hit the glass. A lamp buzzed above the empty desk while the clock ticked. "
        "He waited. Nobody came. The floorboards complained under her boots as she crossed "
        "the room. She left.",
    )

    assert cli.main(["--root", str(workspace), "check", "ch01"]) == 0

    out = capsys.readouterr().out
    assert "linter: ok" in out
    reports = workspace / "projects" / "demo" / "reports"
    payload = json.loads((reports / "lint-ch01.json").read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert payload["chapter"] == "ch01.md"
    assert "Linter report: ch01.md" in (reports / "lint-ch01.md").read_text(encoding="utf-8")


def test_story_check_returns_one_for_a_failing_chapter(workspace, capsys):
    write_chapter(workspace, "It was a testament to her patience.\nShe waited.")

    assert cli.main(["--root", str(workspace), "check", "ch01"]) == 1

    out = capsys.readouterr().out
    assert "linter: failed" in out
    reports = workspace / "projects" / "demo" / "reports"
    payload = json.loads((reports / "lint-ch01.json").read_text(encoding="utf-8"))
    assert payload["findings"]["banned_phrases"][0]["phrase"] == "a testament to"
    assert payload["findings"]["banned_phrases"][0]["lines"] == [1]


def test_story_check_reads_linter_thresholds_from_config(workspace):
    config_path = workspace / "config.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["gates"] = {"linter": {"repeated_phrase_min_count": 2}}
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    write_chapter(
        workspace,
        "Mara found the brass key under the mat.\nThe brass key was cold in her hand.",
    )

    assert cli.main(["--root", str(workspace), "check", "ch01"]) == 1

    report_path = workspace / "projects" / "demo" / "reports" / "lint-ch01.json"
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert any(
        finding["phrase"] == "the brass key"
        for finding in payload["findings"]["repeated_phrases"]
    )


def test_story_check_resolves_a_chapter_name_and_accepts_a_path(workspace, tmp_path):
    path = write_chapter(workspace, "She left.\n\nNobody followed.")

    assert cli.main(["--root", str(workspace), "check", "ch01"]) == 0
    assert cli.main(["--root", str(workspace), "check", str(path)]) == 0


def test_story_check_reports_a_missing_chapter(workspace, capsys):
    assert cli.main(["--root", str(workspace), "check", "ch99"]) == 1
    assert "chapter" in capsys.readouterr().err.lower()


def write_bible(workspace, rules=None, ledger=None):
    directory = workspace / "projects" / "demo" / "stages" / "10-series_bible"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "rules.json").write_text(
        json.dumps(rules or {"system_type": "none"}), encoding="utf-8"
    )
    (workspace / "projects" / "demo" / "ledger.json").write_text(
        json.dumps(ledger or {"chapter": 0, "entities": {}, "events": []}),
        encoding="utf-8",
    )


def write_delta(path, ops, chapter=1):
    path.write_text(json.dumps({"chapter": chapter, "ops": ops}), encoding="utf-8")
    return path


def test_story_check_runs_the_ledger_gate_when_a_delta_is_given(workspace, tmp_path, capsys):
    write_bible(workspace)
    write_chapter(workspace, "She left.\n\nNobody followed.")
    delta = write_delta(
        tmp_path / "delta.json", [{"op": "event", "id": "e1", "summary": "she left"}]
    )

    assert cli.main(["--root", str(workspace), "check", "ch01", "--delta", str(delta)]) == 0

    out = capsys.readouterr().out
    assert "ledger: ok" in out


def test_story_check_fails_when_the_ledger_delta_is_rejected(workspace, tmp_path, capsys):
    write_bible(workspace)
    write_chapter(workspace, "She left.\n\nNobody followed.")
    delta = write_delta(tmp_path / "delta.json", [{"op": "set_world_on_fire"}])

    assert cli.main(["--root", str(workspace), "check", "ch01", "--delta", str(delta)]) == 1

    captured = capsys.readouterr()
    assert "ledger: failed" in captured.out
    assert "unknown operation" in captured.err
