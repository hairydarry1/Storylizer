"""M6: stage 13 narrator voice, the craft targets and tables/banned_phrases.json."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline import runner

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STAGE13 = "13-narrator_voice"


def stage_dir(root, name):
    return root / "projects" / "demo" / "stages" / name


def read_meta(root, name=STAGE13):
    return json.loads((stage_dir(root, name) / "meta.json").read_text(encoding="utf-8"))


def test_narrator_voice_is_stage_thirteen_without_a_gate():
    skill = runner.load_skill(PROJECT_ROOT, "narrator_voice")

    assert skill.stage == 13
    assert skill.human_gate is False
    assert skill.uses_search is False
    assert skill.uses_randomizer is False


def test_narrator_voice_writes_voice_md_and_the_stage_tree(workspace):
    result = runner.run_stage(workspace, "demo", "narrator_voice")

    directory = stage_dir(workspace, STAGE13)
    assert result.status == runner.DONE
    for name in ("output.md", "voice.md", "meta.json"):
        assert (directory / name).is_file(), name
    assert result.meta["files"] == ["output.md", "voice.md", "meta.json"]
    assert (directory / "voice.md").read_text(encoding="utf-8") == result.output_path.read_text(
        encoding="utf-8"
    )


def test_voice_md_has_pov_targets_and_the_subtext_guide(workspace):
    result = runner.run_stage(workspace, "demo", "narrator_voice")

    text = result.output_path.read_text(encoding="utf-8")
    assert "## POV and tense" in text
    assert "## Sentence targets" in text
    assert "## Paragraph targets" in text
    assert "## Dialogue subtext guide" in text
    assert "## Banned phrases" in text
    assert result.meta["voice"]["pov"]
    assert result.meta["voice"]["sentence_words"] >= 1
    assert result.meta["voice"]["paragraph_sentences"] >= 1


def test_sentence_and_paragraph_targets_come_from_craft_targets(workspace):
    (workspace / "projects" / "demo" / "craft_targets.json").write_text(
        json.dumps(
            {
                "sentences": {"words": [11, 11]},
                "paragraphs": {"sentences": [4, 4]},
                "dialogue_ratio": [0.4, 0.4],
                "pov": "first person",
            }
        ),
        encoding="utf-8",
    )

    result = runner.run_stage(workspace, "demo", "narrator_voice")

    text = result.output_path.read_text(encoding="utf-8")
    assert "mean sentence: 11 words" in text
    assert "sentences per paragraph: 4" in text
    assert "first person" in text
    assert result.meta["voice"]["sentence_words"] == 11
    assert result.meta["voice"]["paragraph_sentences"] == 4
    assert result.meta["voice"]["dialogue_ratio"] == pytest.approx(0.4)
    assert result.meta["craft_targets"]["path"].endswith("craft_targets.json")


def test_defaults_are_used_without_craft_targets(workspace):
    result = runner.run_stage(workspace, "demo", "narrator_voice")

    assert result.meta["voice"]["sentence_words"] == 14
    assert result.meta["voice"]["paragraph_sentences"] == 3
    assert result.meta["craft_targets"]["path"] is None
    assert any("craft_targets" in note for note in result.notes)


def test_the_starter_banned_phrases_table_lists_the_ai_tells():
    table = json.loads((PROJECT_ROOT / "tables" / "banned_phrases.json").read_text(encoding="utf-8"))

    values = {entry["value"] for entry in table["entries"]}
    for phrase in ("a testament to", "tapestry of", "couldn't help but", "little did she know"):
        assert phrase in values


def test_narrator_voice_creates_a_missing_banned_phrases_table(workspace):
    (workspace / "tables" / "banned_phrases.json").unlink()

    result = runner.run_stage(workspace, "demo", "narrator_voice")

    table = json.loads((workspace / "tables" / "banned_phrases.json").read_text(encoding="utf-8"))
    values = {entry["value"] for entry in table["entries"]}
    assert "a testament to" in values
    assert any("created" in note.lower() for note in result.notes)
    assert "a testament to" in result.output_path.read_text(encoding="utf-8")


def test_an_existing_banned_phrases_table_is_not_overwritten(workspace):
    (workspace / "tables" / "banned_phrases.json").write_text(
        json.dumps(
            {
                "name": "banned_phrases",
                "entries": [{"value": "at the end of the day", "weight": 1, "tags": []}],
            }
        ),
        encoding="utf-8",
    )

    result = runner.run_stage(workspace, "demo", "narrator_voice")

    text = result.output_path.read_text(encoding="utf-8")
    assert "at the end of the day" in text
    assert "a testament to" not in text
    assert not any("created" in note.lower() for note in result.notes)


def test_the_echo_adapter_is_a_note_not_a_failure(workspace):
    result = runner.run_stage(workspace, "demo", "narrator_voice")

    assert result.status == runner.DONE
    assert any("no prose" in note.lower() for note in result.notes)


def test_narrator_voice_does_not_need_upstream_stages(workspace):
    result = runner.run_stage(workspace, "demo", "narrator_voice")

    assert result.status == runner.DONE
    assert any("01-intake" in note for note in result.notes)
