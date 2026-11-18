"""M7b: stage 14 drafts one chapter, checks it, and only then touches the ledger.

Every chapter is invented prose: a writer call produces chapters/chNN.md, a checker call
returns strict JSON with a summary and delta, and the linter, word-count and ledger gates all
have to pass before the delta is applied. A failure leaves the ledger untouched and marks the
chapter needs_revision with a saved report.
"""

from __future__ import annotations

import json

import pytest

from pipeline import cli, runner
from pipeline.adapters.echo import EchoAdapter

STAGE10 = "10-series_bible"
STAGE11 = "11-outline"
STAGE12 = "12-scene_card"
STAGE13 = "13-narrator_voice"
STAGE14 = "14-chapter_writer"

#: 52 invented words, six sentences with deliberately uneven lengths.
PROSE = (
    "Mara set the brass key beside the cold lamp and listened. "
    "The corridor smelled of wet rope. "
    "She counted three doors, then four, before the hinge complained above the stairs. "
    "Nobody answered. "
    "Rain tapped the window while the clerk shuffled papers behind his desk. "
    "The lock gave way with a dry click."
)
BANNED = " It was a testament to her patience."


def project_path(root):
    return root / "projects" / "demo"


def stage_dir(root, name):
    return project_path(root) / "stages" / name


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def json_block(prompt: str, header: str):
    tail = prompt.split(header, 1)[1]
    return json.loads(tail.split("```json", 1)[1].split("```", 1)[0])


def prepare(root, chapters: int = 2, *, illustration: bool = True):
    """A minimal synthetic project with an outline, cards, voice, bible, rules and ledger."""
    project = project_path(root)
    numbers = list(range(1, chapters + 1))
    outline_chapters = []
    card_chapters = []
    for number in numbers:
        outline_chapters.append(
            {
                "number": number,
                "title": f"Synthetic chapter {number}",
                "hook": f"A door opens on the invented street of chapter {number}.",
                "ends_on": f"The invented key turns in chapter {number}.",
                "shape": "a plan, a reversal, a cost",
                "imagery": "river engineering: sluices, silt, flood marks",
                "tension": 2,
                "words": 60,
                "complication": None,
                "illustration": (
                    {"slot": f"ch{number:02d}-s1", "status": "optional", "focus": "a river at dusk"}
                    if illustration and number == 1
                    else None
                ),
                "threat": False,
                "actor": "mara",
                "closing_actor": "mara",
                "beats": [
                    {
                        "id": f"ch{number:02d}-b1",
                        "kind": "setup",
                        "actor": "mara",
                        "action": f"Mara finds an invented ledger in chapter {number}.",
                        "obstacle": "the clerk invents a fee.",
                        "outcome": "she pays it.",
                    },
                    {
                        "id": f"ch{number:02d}-b2",
                        "kind": "turn",
                        "actor": "mara",
                        "action": "Mara reads the invented entry aloud.",
                        "obstacle": "the room goes quiet.",
                        "outcome": "a witness corrects her.",
                    },
                    {
                        "id": f"ch{number:02d}-b3",
                        "kind": "resolution",
                        "actor": "mara",
                        "action": "Mara chooses the invented door.",
                        "obstacle": "the key sticks.",
                        "outcome": "the lock opens.",
                    },
                ],
            }
        )
        card_chapters.append(
            {
                "number": number,
                "title": f"Synthetic chapter {number}",
                "scenes": [
                    {
                        "number": 1,
                        "goal": f"get the invented ledger in chapter {number}",
                        "conflict": "the clerk invents a fee",
                        "turn": "Mara pays with the brass key",
                    },
                    {
                        "number": 2,
                        "goal": "read the entry aloud",
                        "conflict": "the room goes quiet",
                        "turn": "a witness corrects the date",
                    },
                ],
            }
        )

    outline = {
        "title": "Synthetic Book",
        "target_words": chapters * 60,
        "words_per_chapter": 60,
        "background_threat": "the invented audit",
        "chapters": outline_chapters,
    }
    cards = {"chapters": card_chapters}
    rules = {"system_type": "none"}
    ledger = {"chapter": 0, "entities": {}, "events": [], "applied_deltas": []}

    write_json(stage_dir(root, STAGE11) / "outline.json", outline)
    write_json(stage_dir(root, STAGE12) / "cards.json", cards)
    write_json(stage_dir(root, STAGE10) / "rules.json", rules)
    write_json(project / "ledger.json", ledger)
    (stage_dir(root, STAGE13)).mkdir(parents=True, exist_ok=True)
    (stage_dir(root, STAGE13) / "voice.md").write_text(
        "# Narrator voice\n\n- pov: third person limited\n- tense: past\n\n"
        "## Dialogue subtext guide\n\n- every line wants something it does not say\n",
        encoding="utf-8",
    )
    (stage_dir(root, STAGE10) / "bible.md").write_text(
        "# Series bible\n\n## World rules\n\nIn this invented city, records are held in wax.\n",
        encoding="utf-8",
    )
    write_json(
        project / "craft_targets.json",
        {"sentences": {"words": [10, 18]}, "dialogue_ratio": [0.2, 0.4]},
    )
    return project


class ScriptedChapterAdapter(EchoAdapter):
    """Answers stage 14's writer and checker prompts with invented synthetic data."""

    def __init__(
        self,
        *,
        banned: bool = False,
        invalid_delta: bool = False,
        fail_delta_at: int | None = None,
    ) -> None:
        super().__init__({})
        self.banned = banned
        self.invalid_delta = invalid_delta
        self.fail_delta_at = fail_delta_at
        self.writer_calls = 0
        self.checker_calls = 0

    def complete(self, prompt, **kwargs):
        super().complete(prompt, **kwargs)
        if "## Draft the chapter" in prompt:
            self.writer_calls += 1
            data = json_block(prompt, "## Chapter constraints")
            text = PROSE
            if self.banned:
                text += BANNED
            illustration = data.get("illustration")
            if isinstance(illustration, dict) and illustration.get("slot"):
                focus = illustration.get("focus") or "an invented scene"
                text += f"\n\n[[ILLUSTRATION: {illustration['slot']} | {focus}]]"
            return text

        self.checker_calls += 1
        data = json_block(prompt, "## Checker constraints")
        number = int(data["chapter"])
        invalid = self.invalid_delta or self.fail_delta_at == number
        if invalid:
            return json.dumps(
                {
                    "summary": f"Chapter {number} invents a summary.",
                    "delta": {"chapter": number, "ops": [{"op": "set_world_on_fire"}]},
                }
            )
        return json.dumps(
            {
                "summary": f"Chapter {number} ends with the invented door open.",
                "delta": {
                    "chapter": number,
                    "ops": [
                        {
                            "op": "event",
                            "id": f"ch{number:02d}-e1",
                            "summary": f"Mara opens the invented door in chapter {number}.",
                        }
                    ],
                },
            }
        )


def read_ledger(root):
    return json.loads((project_path(root) / "ledger.json").read_text(encoding="utf-8"))


def read_summaries(root):
    path = project_path(root) / "summaries.json"
    if not path.is_file():
        return {"chapters": []}
    return json.loads(path.read_text(encoding="utf-8"))


def read_meta(root):
    return json.loads((stage_dir(root, STAGE14) / "meta.json").read_text(encoding="utf-8"))


def test_a_passing_chapter_applies_its_delta_and_saves_the_summary(workspace):
    prepare(workspace, chapters=2)
    adapter = ScriptedChapterAdapter()

    result = runner.run_stage(workspace, "demo", "chapter_writer", llm=adapter)

    assert result.status == runner.DONE
    project = project_path(workspace)
    first = (project / "chapters" / "ch01.md").read_text(encoding="utf-8")
    second = (project / "chapters" / "ch02.md").read_text(encoding="utf-8")
    assert "Mara set the brass key" in first
    assert "[[ILLUSTRATION: ch01-s1 | a river at dusk]]" in first
    assert "[[ILLUSTRATION:" not in second
    assert "Mara set the brass key" in second

    ledger = read_ledger(workspace)
    assert ledger["chapter"] == 2
    assert [event["id"] for event in ledger["events"]] == ["ch01-e1", "ch02-e1"]
    assert len(ledger["applied_deltas"]) == 2

    summaries = read_summaries(workspace)["chapters"]
    assert [entry["number"] for entry in summaries] == [1, 2]
    assert summaries[0]["summary"].startswith("Chapter 1")

    meta = read_meta(workspace)
    assert meta["status"] == "done"
    assert [entry["status"] for entry in meta["chapters"]] == ["accepted", "accepted"]
    assert meta["model"]["writer_calls"] == 2
    assert meta["model"]["checker_calls"] == 2
    assert meta["model"]["resumed"] == 0

    reports = project / "reports"
    assert (reports / "chapter-ch01.json").is_file()
    assert (reports / "chapter-ch02.json").is_file()
    report = json.loads((reports / "chapter-ch01.json").read_text(encoding="utf-8"))
    assert report["status"] == "accepted"
    assert report["ledger"]["ok"] is True
    assert report["linter"]["passed"] is True
    assert report["words"] == 58  # 52 prose words plus the illustration marker

    assert [call["model_tier"] for call in adapter.calls] == ["writer", "checker", "writer", "checker"]
    writer_prompt = adapter.calls[0]["prompt"]
    assert "## Story bible" in writer_prompt
    assert "## Voice" in writer_prompt
    assert "## Rules summary" in writer_prompt
    assert "## Ledger snapshot" in writer_prompt
    assert "## Scene cards" in writer_prompt
    assert "## Writing rules" in writer_prompt
    assert "protagonist solves her own problems" in writer_prompt.lower()
    assert "## Craft targets" in writer_prompt
    assert "sentence_words" in writer_prompt
    assert "dialogue_ratio" in writer_prompt
    assert "[[ILLUSTRATION: ch01-s1" in writer_prompt
    second_prompt = adapter.calls[2]["prompt"]
    assert "Chapter 1 ends with the invented door open." in second_prompt
    assert "ch01-e1" in second_prompt  # the current ledger, not the pre-chapter snapshot
    assert '"chapter": 1' in second_prompt


def test_an_invalid_delta_is_retried_three_times_then_flags_the_chapter(workspace):
    prepare(workspace, chapters=1)
    adapter = ScriptedChapterAdapter(invalid_delta=True)

    result = runner.run_stage(workspace, "demo", "chapter_writer", llm=adapter)

    assert result.status == runner.FAILED
    assert adapter.writer_calls == 1
    assert adapter.checker_calls == 3
    assert "## Your previous reply was rejected" in adapter.calls[2]["prompt"]
    assert "unknown operation" in adapter.calls[2]["prompt"]

    ledger = read_ledger(workspace)
    assert ledger["chapter"] == 0
    assert ledger["events"] == []
    assert ledger["applied_deltas"] == []
    assert read_summaries(workspace)["chapters"] == []

    meta = read_meta(workspace)
    assert meta["status"] == "failed"
    assert meta["chapters"][0]["status"] == "needs_revision"
    assert meta["chapters"][0]["checker_attempts"] == 3
    assert "unknown operation" in meta["error"]
    assert (project_path(workspace) / "chapters" / "ch01.md").is_file()

    report = json.loads(
        (project_path(workspace) / "reports" / "chapter-ch01.json").read_text(encoding="utf-8")
    )
    assert report["status"] == "needs_revision"
    assert report["ledger"]["ok"] is False
    assert any("unknown operation" in error for error in report["ledger"]["errors"])


def test_a_lint_failure_blocks_the_delta_without_calling_the_checker(workspace):
    prepare(workspace, chapters=1)
    adapter = ScriptedChapterAdapter(banned=True)

    result = runner.run_stage(workspace, "demo", "chapter_writer", llm=adapter)

    assert result.status == runner.FAILED
    assert adapter.writer_calls == 1
    assert adapter.checker_calls == 0
    assert read_ledger(workspace)["events"] == []
    assert read_summaries(workspace)["chapters"] == []

    report = json.loads(
        (project_path(workspace) / "reports" / "chapter-ch01.json").read_text(encoding="utf-8")
    )
    assert report["linter"]["passed"] is False
    assert report["linter"]["findings"]["banned_phrases"][0]["phrase"] == "a testament to"
    assert any("linter" in error.lower() for error in report["errors"])


def test_a_word_count_outside_twenty_percent_is_flagged_before_the_checker(workspace):
    prepare(workspace, chapters=1)
    (stage_dir(workspace, STAGE11) / "outline.json").write_text(
        json.dumps(
            {
                **json.loads((stage_dir(workspace, STAGE11) / "outline.json").read_text(encoding="utf-8")),
                "chapters": [
                    {
                        **json.loads((stage_dir(workspace, STAGE11) / "outline.json").read_text(encoding="utf-8"))["chapters"][0],
                        "words": 200,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    adapter = ScriptedChapterAdapter()

    result = runner.run_stage(workspace, "demo", "chapter_writer", llm=adapter)

    assert result.status == runner.FAILED
    assert adapter.writer_calls == 1
    assert adapter.checker_calls == 0
    assert read_ledger(workspace)["events"] == []
    report = json.loads(
        (project_path(workspace) / "reports" / "chapter-ch01.json").read_text(encoding="utf-8")
    )
    assert report["words"] == 58
    assert report["target_words"] == 200
    assert any("word count" in error.lower() for error in report["errors"])


def test_chapter_scope_writes_only_that_chapter(workspace):
    prepare(workspace, chapters=3)
    adapter = ScriptedChapterAdapter()

    result = runner.run_stage(workspace, "demo", "chapter_writer", llm=adapter, chapter=2)

    assert result.status == runner.DONE
    project = project_path(workspace)
    assert not (project / "chapters" / "ch01.md").exists()
    assert (project / "chapters" / "ch02.md").is_file()
    assert not (project / "chapters" / "ch03.md").exists()
    assert read_ledger(workspace)["chapter"] == 2
    assert [entry["number"] for entry in read_summaries(workspace)["chapters"]] == [2]
    assert adapter.writer_calls == 1


def test_from_scope_starts_at_the_requested_chapter(workspace):
    prepare(workspace, chapters=3)
    adapter = ScriptedChapterAdapter()

    result = runner.run_stage(workspace, "demo", "chapter_writer", llm=adapter, from_chapter=2)

    assert result.status == runner.DONE
    project = project_path(workspace)
    assert not (project / "chapters" / "ch01.md").exists()
    assert (project / "chapters" / "ch02.md").is_file()
    assert (project / "chapters" / "ch03.md").is_file()
    assert [entry["number"] for entry in read_summaries(workspace)["chapters"]] == [2, 3]


def test_resume_skips_accepted_chapters_and_retries_the_failed_one(workspace):
    prepare(workspace, chapters=2)
    first = ScriptedChapterAdapter(fail_delta_at=2)

    failed = runner.run_stage(workspace, "demo", "chapter_writer", llm=first)

    assert failed.status == runner.FAILED
    assert [entry["number"] for entry in read_summaries(workspace)["chapters"]] == [1]
    assert [event["id"] for event in read_ledger(workspace)["events"]] == ["ch01-e1"]

    second = ScriptedChapterAdapter()
    resumed = runner.run_stage(workspace, "demo", "chapter_writer", llm=second)

    assert resumed.status == runner.DONE
    assert second.writer_calls == 1  # chapter 1 was already accepted
    assert [entry["number"] for entry in read_summaries(workspace)["chapters"]] == [1, 2]
    assert [event["id"] for event in read_ledger(workspace)["events"]] == ["ch01-e1", "ch02-e1"]
    meta = read_meta(workspace)
    assert meta["model"]["resumed"] == 1
    assert [entry["number"] for entry in meta["chapters"]] == [1, 2]
    assert [entry["status"] for entry in meta["chapters"]] == ["accepted", "accepted"]


def test_resume_after_everything_is_accepted_makes_no_model_calls(workspace):
    prepare(workspace, chapters=2)
    runner.run_stage(workspace, "demo", "chapter_writer", llm=ScriptedChapterAdapter())
    adapter = ScriptedChapterAdapter()

    result = runner.run_stage(workspace, "demo", "chapter_writer", llm=adapter)

    assert result.status == runner.DONE
    assert adapter.calls == []
    assert result.meta["model"]["resumed"] == 2
    assert [entry["status"] for entry in result.meta["chapters"]] == ["accepted", "accepted"]


def test_max_calls_fails_before_an_unpaid_checker_can_apply_a_delta(workspace):
    prepare(workspace, chapters=1)

    result = runner.run_stage(
        workspace, "demo", "chapter_writer", llm=ScriptedChapterAdapter(), max_calls=1
    )

    assert result.status == runner.FAILED
    assert result.meta["calls"]["run"] == 1
    assert read_ledger(workspace)["events"] == []
    assert read_summaries(workspace)["chapters"] == []


def test_both_chapter_scopes_at_once_are_rejected(workspace):
    prepare(workspace, chapters=2)

    with pytest.raises(runner.StoryError, match="chapter"):
        runner.run_stage(
            workspace,
            "demo",
            "chapter_writer",
            llm=ScriptedChapterAdapter(),
            chapter=1,
            from_chapter=2,
        )


def test_the_cli_accepts_chapter_and_from(workspace, capsys):
    prepare(workspace, chapters=3)

    assert cli.main(
        ["--root", str(workspace), "run", "chapter_writer", "--chapter", "2"]
    ) == 1  # the echo adapter cannot meet the word target, but the scope is wired
    project = project_path(workspace)
    assert not (project / "chapters" / "ch01.md").exists()
    assert (project / "chapters" / "ch02.md").is_file()
    assert "14-chapter_writer" in capsys.readouterr().out

    assert cli.main(
        ["--root", str(workspace), "run", "chapter_writer", "--from", "3"]
    ) == 1
    assert (project / "chapters" / "ch03.md").is_file()
    assert "14-chapter_writer" in capsys.readouterr().out


def test_the_skill_file_declares_the_writer_tier(workspace):
    skill = runner.load_skill(workspace, "chapter_writer")

    assert skill.stage == 14
    assert skill.model_tier == "writer"
    assert skill.human_gate is False
    assert "protagonist solves her own problems" in skill.body.lower()
    assert "ledger delta" in skill.body.lower()
