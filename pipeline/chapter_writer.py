"""Stage 14: draft one chapter at a time, check it, then update the ledger.

Per chapter there are two model calls. The writer tier gets the chapter's outline beats and
scene cards, the narrator voice, a bible and rules summary, the current ledger, the last two
chapter summaries, sampled craft targets, the chapter's shape and imagery, and the writing
rules. It writes prose to `chapters/chNN.md` and inserts the outline's illustration marker.

The checker tier gets that finished chapter and returns strict JSON with a `summary` and a
`delta`. The shared strict-JSON retry layer (`model_json.request_json`) gives it three
attempts and feeds validation errors back.

Nothing reaches the ledger until the gate passes: the linter, the illustration marker, a word
count inside 20% of target, and `ledger.validate_delta`. A failure leaves the ledger and
`summaries.json` untouched, marks the chapter `needs_revision`, and saves a report in
`reports/chapter-chNN.json`. A later run resumes at the first chapter without an accepted
summary.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import craft_targets, ledger, model_json
from .gates import linter

STAGE_DIR = "14-chapter_writer"
SUMMARY_FILE = "summaries.json"
TOLERANCE = 0.20
CHECKER_MAX_TOKENS = 1200
WRITER_MAX_TOKENS = 6000
CHECKER_KEYS = frozenset({"summary", "delta"})

CHAPTER_DIRNAME = "chapters"
REPORT_DIRNAME = "reports"

WRITING_RULES: tuple[str, ...] = (
    "The protagonist solves her own problems; allies may help, but she makes the choice.",
    "No lecture conversions: nobody changes their mind because of a speech.",
    "Show don't tell: render emotion as action, sensation and detail, never as a label.",
    "Dialogue carries subtext; every spoken line has an unspoken goal.",
    "Never use a banned phrase, in narration or dialogue.",
    "No meta commentary: no addressing the reader, no explaining the theme, no chapter notes.",
    "Vary sentence length and paragraph openings; do not settle into a rhythm.",
)


class ChapterWriterError(RuntimeError):
    """A user-facing stage-14 problem: missing inputs, bad scope, unreadable state."""


@dataclass
class BookContext:
    project: Path
    outline: dict[str, Any]
    cards: dict[int, dict[str, Any]]
    voice: str
    bible: str
    rules: dict[str, Any]
    story: dict[str, Any]
    summaries: dict[int, dict[str, Any]]
    ledger_path: Path
    summaries_path: Path


@dataclass
class ChapterResult:
    number: int
    status: str
    words: int = 0
    target_words: int = 0
    chapter_file: str = ""
    report_file: str = ""
    summary: str = ""
    delta_id: str = ""
    checker_attempts: int = 0
    resumed: bool = False
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "status": self.status,
            "words": self.words,
            "target_words": self.target_words,
            "chapter_file": self.chapter_file,
            "report_file": self.report_file,
            "summary": self.summary,
            "delta": self.delta_id,
            "checker_attempts": self.checker_attempts,
            "resumed": self.resumed,
            "errors": list(self.errors),
        }


@dataclass
class WriteReport:
    chapters: list[ChapterResult] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    writer_calls: int = 0
    checker_calls: int = 0
    checker_attempts: int = 0

    @property
    def ok(self) -> bool:
        return all(chapter.status == "accepted" for chapter in self.chapters)

    @property
    def resumed(self) -> int:
        return sum(1 for chapter in self.chapters if chapter.resumed)

    @property
    def errors(self) -> list[str]:
        return [
            f"chapter {chapter.number}: {'; '.join(chapter.errors)}"
            for chapter in self.chapters
            if chapter.errors
        ]

    @property
    def model(self) -> dict[str, Any]:
        return {
            "mode": "model",
            "writer_calls": self.writer_calls,
            "checker_calls": self.checker_calls,
            "checker_attempts": self.checker_attempts,
            "resumed": self.resumed,
        }


# --------------------------------------------------------------------------- inputs


def _required(path: Path, command: str) -> Path:
    if not path.is_file():
        raise ChapterWriterError(f"run `story run {command}` first: no {path}")
    return path


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ChapterWriterError(f"{path} is not valid JSON: {exc}") from exc


def load_summaries(path: Path | str) -> dict[int, dict[str, Any]]:
    """Accepted chapter summaries, keyed by chapter number. A broken file starts empty."""
    summary_path = Path(path)
    if not summary_path.is_file():
        return {}
    try:
        raw = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    entries = raw.get("chapters") if isinstance(raw, Mapping) else raw
    if not isinstance(entries, list):
        return {}
    summaries: dict[int, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        number = entry.get("number")
        if isinstance(number, bool) or not isinstance(number, int):
            continue
        summaries[number] = dict(entry)
    return summaries


def save_summaries(path: Path | str, summaries: Mapping[int, Mapping[str, Any]]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "chapters": [dict(summaries[number]) for number in sorted(summaries)]
    }
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return target


def load_context(project: Path | str) -> BookContext:
    """Everything stage 14 needs from disk, with a readable error for each missing input."""
    project = Path(project)
    stage = project / "stages"
    outline_path = _required(stage / "11-outline" / "outline.json", "outline")
    cards_path = _required(stage / "12-scene_card" / "cards.json", "scene_card")
    voice_path = _required(stage / "13-narrator_voice" / "voice.md", "narrator_voice")
    bible_path = _required(stage / "10-series_bible" / "bible.md", "series_bible")
    rules_path = _required(stage / "10-series_bible" / "rules.json", "series_bible")
    ledger_path = _required(project / "ledger.json", "series_bible")

    outline = _read_json(outline_path)
    cards_raw = _read_json(cards_path)
    if not isinstance(outline, Mapping) or not isinstance(outline.get("chapters"), list):
        raise ChapterWriterError(f"{outline_path} has no chapters list")
    if not isinstance(cards_raw, Mapping) or not isinstance(cards_raw.get("chapters"), list):
        raise ChapterWriterError(f"{cards_path} has no chapters list")

    cards = {
        int(entry["number"]): dict(entry)
        for entry in cards_raw["chapters"]
        if isinstance(entry, Mapping)
        and isinstance(entry.get("number"), int)
        and not isinstance(entry.get("number"), bool)
    }
    try:
        rules = ledger.load_rules(rules_path)
    except ledger.RulesError as exc:
        raise ChapterWriterError(f"invalid rules at {rules_path}: {exc}") from exc
    try:
        story = ledger.load_ledger(ledger_path)
    except ledger.LedgerError as exc:
        raise ChapterWriterError(f"invalid ledger at {ledger_path}: {exc}") from exc

    return BookContext(
        project=project,
        outline=dict(outline),
        cards=cards,
        voice=voice_path.read_text(encoding="utf-8"),
        bible=bible_path.read_text(encoding="utf-8"),
        rules=rules,
        story=story,
        summaries=load_summaries(project / SUMMARY_FILE),
        ledger_path=ledger_path,
        summaries_path=project / SUMMARY_FILE,
    )


# --------------------------------------------------------------------------- prompt material


def _rules_summary(rules: Mapping[str, Any]) -> str:
    xp = rules.get("xp") or {}
    locations = sorted(rules.get("locations") or {})
    items = sorted(rules.get("items") or {})
    skills = sorted(rules.get("skills") or {})
    return "\n".join(
        [
            f"- system: {rules.get('system_type')}",
            f"- max level: {xp.get('max_level')}",
            f"- start location: {rules.get('start_location')}",
            f"- locations: {', '.join(locations) or '(none)'}",
            f"- items: {', '.join(items) or '(none)'}",
            f"- skills: {', '.join(skills) or '(none)'}",
        ]
    )


def _bible_summary(text: str, limit: int = 3000) -> str:
    cleaned = text.strip()
    if len(cleaned) <= limit:
        return cleaned or "(the bible is empty)"
    return cleaned[:limit].rstrip() + "\n\n[bible summary truncated]"


def _previous_summaries(
    summaries: Mapping[int, Mapping[str, Any]], number: int, limit: int = 2
) -> str:
    prior = [summaries[item] for item in sorted(summaries) if item < number]
    if not prior:
        return "- none; this is the first chapter"
    lines = []
    for entry in prior[-limit:]:
        summary = str(entry.get("summary") or "").strip() or "(no summary)"
        lines.append(f"- ch{entry.get('number')}: {summary}")
    return "\n".join(lines)


def _target_words(
    chapter: Mapping[str, Any],
    targets: craft_targets.Targets | None,
    seed: int,
) -> tuple[int, bool]:
    raw = chapter.get("words")
    if isinstance(raw, int) and not isinstance(raw, bool) and raw > 0:
        return raw, True
    value, sampled = craft_targets.sample(
        targets,
        "chapters.words",
        seed=seed,
        stage=STAGE_DIR,
        key=f"words-{chapter.get('number')}",
    )
    return max(1, int(value)), sampled


def _craft_targets(
    chapter: Mapping[str, Any],
    targets: craft_targets.Targets | None,
    seed: int,
) -> dict[str, Any]:
    number = chapter.get("number")
    words, words_sampled = _target_words(chapter, targets, seed)
    sentence_words, sentence_sampled = craft_targets.sample(
        targets,
        "sentences.words",
        seed=seed,
        stage=STAGE_DIR,
        key=f"sentence-words-{number}",
    )
    dialogue_ratio, dialogue_sampled = craft_targets.sample(
        targets,
        "dialogue_ratio",
        seed=seed,
        stage=STAGE_DIR,
        key=f"dialogue-ratio-{number}",
    )
    return {
        "words": words,
        "sentence_words": max(1, int(sentence_words)),
        "dialogue_ratio": round(float(dialogue_ratio), 3),
        "source": str(targets.path) if targets is not None else None,
        "sampled": {
            "words": bool(words_sampled),
            "sentence_words": bool(sentence_sampled),
            "dialogue_ratio": bool(dialogue_sampled),
        },
    }


def _illustration(chapter: Mapping[str, Any]) -> tuple[str, str] | None:
    raw = chapter.get("illustration")
    number = chapter.get("number")
    if isinstance(raw, Mapping):
        slot = str(raw.get("slot") or "").strip()
        focus = str(raw.get("focus") or raw.get("description") or "").strip()
    elif isinstance(raw, str):
        slot, focus = raw.strip(), ""
    elif raw:
        slot, focus = "", ""
    else:
        return None
    slot = slot or f"ch{int(number):02d}-s1"
    focus = focus or "the chapter's central image"
    return slot, focus


def _skill_sections(skill: Any) -> str:
    names = ("Purpose", "Steps", "Do not")
    return "\n\n".join(
        f"## {name}\n\n{skill.sections[name]}" for name in names if skill.sections.get(name)
    )


def writer_prompt(
    skill: Any,
    context: BookContext,
    chapter: Mapping[str, Any],
    craft: Mapping[str, Any],
    banned: Sequence[str],
) -> str:
    number = int(chapter.get("number"))
    cards = context.cards.get(number, {"scenes": []})
    illustration = _illustration(chapter)
    illustration_text = (
        "Insert this marker exactly where the scene it describes reaches its image:\n\n"
        f"[[ILLUSTRATION: {illustration[0]} | {illustration[1]}]]"
        if illustration is not None
        else "This chapter has no illustration slot; do not add an illustration marker."
    )
    banned_text = ", ".join(f'"{phrase}"' for phrase in banned) or "(none)"
    constraints = {
        "number": number,
        "title": chapter.get("title"),
        "shape": chapter.get("shape"),
        "imagery": chapter.get("imagery"),
        "tension": chapter.get("tension"),
        "target_words": craft["words"],
        "illustration": (
            {"slot": illustration[0], "focus": illustration[1]}
            if illustration is not None
            else None
        ),
        "beats": chapter.get("beats") or [],
    }
    return "\n\n".join(
        [
            _skill_sections(skill),
            "## Chapter constraints\n\n"
            "These are fixed. Write inside them and do not change the outline.\n\n"
            f"```json\n{json.dumps(constraints, indent=2)}\n```",
            "## Scene cards\n\n"
            f"```json\n{json.dumps(cards.get('scenes') or [], indent=2)}\n```",
            "## Story bible\n\n" + _bible_summary(context.bible),
            "## Voice\n\n" + context.voice.strip(),
            "## Rules summary\n\n" + _rules_summary(context.rules),
            "## Ledger snapshot\n\n"
            f"```json\n{json.dumps(context.story, indent=2)}\n```",
            "## Previous chapter summaries\n\n"
            + _previous_summaries(context.summaries, number),
            "## Craft targets\n\n"
            f"```json\n{json.dumps(craft, indent=2)}\n```",
            "## Writing rules\n\n"
            + "\n".join(f"- {rule}" for rule in WRITING_RULES)
            + f"\n- Never use these phrases: {banned_text}",
            "## Illustration\n\n" + illustration_text,
            "## Draft the chapter\n\n"
            f"Write chapter {number} as finished prose only. No title, headings, notes or "
            "JSON. Do not explain what you are doing.",
        ]
    ).strip() + "\n"


def checker_prompt(
    skill: Any,
    chapter: Mapping[str, Any],
    prose: str,
    context: BookContext,
    feedback: Sequence[str] = (),
) -> str:
    number = int(chapter.get("number"))
    constraints = {
        "chapter": number,
        "words": len(prose.split()),
        "shape": chapter.get("shape"),
        "imagery": chapter.get("imagery"),
    }
    reply_shape = {
        "summary": "two to four sentences, concrete, no spoilers beyond this chapter",
        "delta": {
            "chapter": number,
            "ops": [
                {
                    "op": "event",
                    "id": f"ch{number:02d}-e1",
                    "summary": "one thing that changed and must be remembered",
                }
            ],
        },
    }
    lines = [
        _skill_sections(skill),
        "## Checker constraints\n\n"
        f"```json\n{json.dumps(constraints, indent=2)}\n```",
        "## Finished chapter\n\n" + prose.strip(),
        "## Current ledger\n\n"
        f"```json\n{json.dumps(context.story, indent=2)}\n```",
        "## Rules summary\n\n" + _rules_summary(context.rules),
        "## Your reply\n\n"
        "Reply with one JSON object and nothing else:\n\n"
        f"```json\n{json.dumps(reply_shape, indent=2)}\n```",
        f"- `summary` is a non-empty string about chapter {number}",
        f"- `delta.chapter` is exactly {number}",
        "- `delta.ops` is a non-empty list of earned operations from the ledger rules",
        "- record an event with a new id for anything the chapter changed",
        "- an item needs a recorded event or recipe; a move needs a real exit; a skill or "
        "level needs its threshold",
        "- do not invent entities, items, locations or events",
    ]
    if feedback:
        lines += [
            "",
            "## Your previous reply was rejected",
            "",
            *[f"- {error}" for error in feedback],
            "",
            "Fix every error and reply with one valid JSON object.",
        ]
    return "\n".join(lines).rstrip() + "\n"


# --------------------------------------------------------------------------- checks


def _marker_errors(prose: str, chapter: Mapping[str, Any]) -> list[str]:
    illustration = _illustration(chapter)
    if illustration is None:
        return []
    marker = f"[[ILLUSTRATION: {illustration[0]} |"
    if marker not in prose:
        return [
            f"missing illustration marker [[ILLUSTRATION: {illustration[0]} | ...]] "
            "required by the outline"
        ]
    return []


def _word_errors(words: int, target: int) -> list[str]:
    low = target * (1 - TOLERANCE)
    high = target * (1 + TOLERANCE)
    if low <= words <= high:
        return []
    return [
        f"word count {words} is outside 20% of the {target}-word target "
        f"({low:.0f}-{high:.0f})"
    ]


def _linter_errors(report: linter.LintReport) -> list[str]:
    errors = []
    for name in linter.CHECK_NAMES:
        count = report.counts[name]
        if count:
            errors.append(f"linter: {name.replace('_', ' ')} ({count})")
    return errors


def _checker_errors(
    payload: Any,
    *,
    number: int,
    story: Mapping[str, Any],
    rules: Mapping[str, Any],
) -> list[str]:
    if not isinstance(payload, Mapping):
        return ["the reply must be a JSON object"]
    extra = set(payload) - CHECKER_KEYS
    missing = CHECKER_KEYS - set(payload)
    errors: list[str] = []
    if missing:
        errors.append(f"missing keys: {', '.join(sorted(missing))}")
    if extra:
        errors.append(f"unexpected keys: {', '.join(sorted(extra))}")

    summary = payload.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        errors.append("summary must be a non-empty string")

    delta = payload.get("delta")
    if not isinstance(delta, Mapping):
        errors.append("delta must be a JSON object")
        return errors
    chapter = delta.get("chapter")
    if chapter != number:
        errors.append(f"delta.chapter must be {number} (got {chapter!r})")
    ops = delta.get("ops")
    if not isinstance(ops, list) or not ops:
        errors.append("delta.ops must be a non-empty list")

    if not errors:
        report = ledger.validate_delta(story, rules, delta)
        errors.extend(report.errors)
    return errors


def _relative(project: Path, path: Path) -> str:
    return str(path.relative_to(project)).replace("\\", "/")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# --------------------------------------------------------------------------- chapter loop


def _scope(
    chapters: Sequence[Mapping[str, Any]],
    chapter: int | None,
    from_chapter: int | None,
) -> list[Mapping[str, Any]]:
    if chapter is not None and from_chapter is not None:
        raise ChapterWriterError("use --chapter N or --from N, not both")
    numbers = [int(item["number"]) for item in chapters]
    if chapter is not None:
        if chapter not in numbers:
            raise ChapterWriterError(
                f"chapter {chapter} is not in the outline (chapters {min(numbers)}-{max(numbers)})"
            )
        return [item for item in chapters if int(item["number"]) == chapter]
    start = from_chapter if from_chapter is not None else (min(numbers) if numbers else 1)
    if start not in numbers:
        raise ChapterWriterError(
            f"chapter {start} is not in the outline (chapters {min(numbers)}-{max(numbers)})"
        )
    return [item for item in chapters if int(item["number"]) >= start]


def _write_chapter_report(path: Path, payload: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def write_chapters(
    context: BookContext,
    *,
    skill: Any,
    llm: Any,
    seed: int,
    targets: craft_targets.Targets | None,
    banned: Sequence[str],
    options: linter.Options | None = None,
    chapter: int | None = None,
    from_chapter: int | None = None,
    notes: list[str] | None = None,
) -> WriteReport:
    """Draft the selected chapters in order, stopping at the first one that needs revision."""
    notes = notes if notes is not None else []
    options = options or linter.Options()
    report = WriteReport()
    selected = _scope(context.outline.get("chapters") or [], chapter, from_chapter)
    project = context.project
    story = context.story
    summaries = dict(context.summaries)

    for chapter_data in selected:
        number = int(chapter_data["number"])
        chapter_file = project / CHAPTER_DIRNAME / f"ch{number:02d}.md"
        report_file = project / REPORT_DIRNAME / f"chapter-ch{number:02d}.json"

        saved = summaries.get(number)
        if saved is not None and chapter_file.is_file():
            report.chapters.append(
                ChapterResult(
                    number=number,
                    status="accepted",
                    words=int(saved.get("words") or 0),
                    target_words=int(saved.get("target_words") or 0),
                    chapter_file=_relative(project, chapter_file),
                    report_file=_relative(project, report_file),
                    summary=str(saved.get("summary") or ""),
                    delta_id=str(saved.get("delta") or ""),
                    resumed=True,
                )
            )
            continue

        craft = _craft_targets(chapter_data, targets, seed)
        target_words = int(craft["words"])
        result = ChapterResult(
            number=number,
            status="needs_revision",
            target_words=target_words,
            chapter_file=_relative(project, chapter_file),
            report_file=_relative(project, report_file),
        )
        payload: dict[str, Any] = {
            "chapter": number,
            "title": chapter_data.get("title"),
            "status": "needs_revision",
            "chapter_file": result.chapter_file,
            "report_file": result.report_file,
            "words": 0,
            "target_words": target_words,
            "target_range": [
                round(target_words * (1 - TOLERANCE)),
                round(target_words * (1 + TOLERANCE)),
            ],
            "linter": None,
            "ledger": None,
            "checker": {"attempts": 0, "summary": "", "delta": None},
            "errors": [],
        }

        try:
            prose = llm.complete(
                writer_prompt(skill, context, chapter_data, craft, banned),
                system=skill.sections.get("Purpose"),
                model_tier="writer",
                max_tokens=WRITER_MAX_TOKENS,
            )
        except Exception as exc:  # an adapter error is a chapter failure, not a crash
            prose = ""
            errors = [f"writer call failed: {exc}"]
        else:
            errors = []
        report.writer_calls += 1
        prose = str(prose or "").strip()

        chapter_file.parent.mkdir(parents=True, exist_ok=True)
        chapter_file.write_text(prose.rstrip() + ("\n" if prose else ""), encoding="utf-8")

        lint_report = linter.lint_text(
            prose,
            options=options,
            banned_phrases=banned,
            chapter=f"ch{number:02d}.md",
        )
        result.words = lint_report.words
        payload["words"] = lint_report.words
        payload["linter"] = lint_report.to_dict()
        errors.extend(_linter_errors(lint_report))
        errors.extend(_marker_errors(prose, chapter_data))
        errors.extend(_word_errors(lint_report.words, target_words))

        if errors:
            result.errors = errors
            payload["errors"] = list(errors)
            _write_chapter_report(report_file, payload)
            report.chapters.append(result)
            break

        def validate(reply_payload: Any) -> list[str]:
            return _checker_errors(
                reply_payload, number=number, story=story, rules=context.rules
            )

        checker_payload, attempts, checker_errors = model_json.request_json(
            llm,
            lambda feedback: checker_prompt(
                skill, chapter_data, prose, context, feedback
            ),
            validate,
            system=skill.sections.get("Purpose"),
            model_tier="checker",
            max_tokens=CHECKER_MAX_TOKENS,
        )
        report.checker_calls += attempts
        report.checker_attempts = max(report.checker_attempts, attempts)
        result.checker_attempts = attempts
        payload["checker"]["attempts"] = attempts

        if checker_payload is None:
            errors = checker_errors or ["the checker did not return a usable reply"]
            result.errors = errors
            payload["ledger"] = {
                "delta": "",
                "ok": False,
                "errors": list(errors),
                "notes": [],
            }
            payload["errors"] = list(errors)
            _write_chapter_report(report_file, payload)
            report.chapters.append(result)
            break

        summary = str(checker_payload["summary"]).strip()
        delta = dict(checker_payload["delta"])
        result.summary = summary
        payload["checker"].update({"summary": summary, "delta": delta})

        validation = ledger.validate_delta(story, context.rules, delta)
        payload["ledger"] = validation.to_dict()
        if not validation.ok:
            result.errors = list(validation.errors)
            payload["errors"] = list(validation.errors)
            _write_chapter_report(report_file, payload)
            report.chapters.append(result)
            break

        try:
            story = ledger.apply_delta(story, context.rules, delta)
            ledger.save_ledger(story, context.ledger_path)
        except (ledger.LedgerError, OSError) as exc:
            result.errors = [f"could not apply the ledger delta: {exc}"]
            payload["errors"] = list(result.errors)
            _write_chapter_report(report_file, payload)
            report.chapters.append(result)
            break

        context.story = story
        result.status = "accepted"
        result.delta_id = validation.delta_id
        payload["status"] = "accepted"
        summaries[number] = {
            "number": number,
            "summary": summary,
            "chapter": result.chapter_file,
            "words": result.words,
            "target_words": target_words,
            "delta": validation.delta_id,
            "accepted_at": _now(),
        }
        save_summaries(context.summaries_path, summaries)
        context.summaries = summaries
        _write_chapter_report(report_file, payload)
        report.chapters.append(result)

    if report.resumed:
        notes.append(f"resumed {report.resumed} accepted chapter(s)")
    return report


def render_report(report: WriteReport, *, scope: str = "all chapters") -> str:
    lines = ["# Chapter writer", "", f"- scope: {scope}", f"- status: {'ok' if report.ok else 'failed'}"]
    accepted = sum(1 for chapter in report.chapters if chapter.status == "accepted")
    lines.append(f"- chapters accepted: {accepted}/{len(report.chapters)}")
    lines.append(f"- resumed: {report.resumed}")
    lines += ["", "## Chapters", ""]
    for chapter in report.chapters:
        lines += [
            f"### Chapter {chapter.number} - {chapter.status}",
            "",
            f"- words: {chapter.words} / {chapter.target_words}",
            f"- file: {chapter.chapter_file}",
            f"- report: {chapter.report_file}",
        ]
        if chapter.summary:
            lines.append(f"- summary: {chapter.summary}")
        if chapter.delta_id:
            lines.append(f"- delta: {chapter.delta_id}")
        if chapter.resumed:
            lines.append("- resumed from summaries.json")
        for error in chapter.errors:
            lines.append(f"- error: {error}")
        lines.append("")
    if report.notes:
        lines += ["## Notes", ""]
        lines.extend(f"- {note}" for note in report.notes)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
