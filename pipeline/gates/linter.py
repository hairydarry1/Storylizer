"""The deterministic linter gate (BUILD_SPEC.md section 7): repetition and AI tells, no model.

`lint_text` returns a JSON-friendly report with counts and line numbers for six checks:
repeated 3-5 word phrases, overused words, uniform sentence length, banned phrases, tic
words per 1,000 words, and repeated paragraph openers. `render_markdown` turns the same
report into the summary the chapter revision loop can attach to its feedback.

Thresholds live under `gates.linter` in config.yaml; `Options.from_mapping` validates them.
"""

from __future__ import annotations

import json
import re
import statistics
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..narrator_voice import STARTER_PHRASES

CHECK_NAMES: tuple[str, ...] = (
    "repeated_phrases",
    "overused_words",
    "uniform_sentence_length",
    "banned_phrases",
    "tic_words",
    "repeated_paragraph_openers",
)

TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:['\u2019\-][A-Za-z0-9]+)*")
SENTENCE_END_RE = re.compile(r"[.!?]+(?=\s|$)")

#: Common English function words: never "overused" on their own.
STOPWORDS: frozenset[str] = frozenset(
    """
    a about above after again against all also am an and any are as at be because been
    before being below between both but by can could did do does doing down during each
    few for from further had has have having he her here hers herself him himself his how
    i if in into is it its itself just me more most my myself no nor not now of off on once
    only or other our ours ourselves out over own quite really same she should so some such
    than that the their theirs them themselves then there these they this those through to
    too under until up very was we were what when where which while who whom why will with
    would you your yours yourself yourselves
    """.split()
)

#: Words that tend to creep into every draft; a high rate is a style tic.
DEFAULT_TIC_WORDS: tuple[str, ...] = (
    "just",
    "really",
    "very",
    "suddenly",
    "somehow",
    "actually",
    "quite",
    "almost",
    "only",
    "even",
    "still",
    "then",
)


class LinterError(RuntimeError):
    """A user-facing linter problem: unreadable chapter, bad threshold, bad table."""


@dataclass(frozen=True)
class Options:
    """Linter thresholds. Defaults are deliberately conservative for a chapter draft."""

    repeated_phrase_lengths: tuple[int, ...] = (3, 4, 5)
    repeated_phrase_min_count: int = 3
    overused_word_min_count: int = 6
    overused_word_per_1000: float = 8.0
    tic_words: tuple[str, ...] = DEFAULT_TIC_WORDS
    tic_min_count: int = 3
    tic_per_1000: float = 5.0
    uniform_sentence_stdev: float = 2.5
    uniform_min_sentences: int = 8
    paragraph_opener_words: int = 1
    paragraph_opener_min_count: int = 3
    banned_phrase_min_count: int = 1
    ignore_words: tuple[str, ...] = tuple(STOPWORDS)

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any] | None) -> "Options":
        """Build options from `gates.linter` in config.yaml, rejecting unusable values."""
        if not mapping:
            return cls()
        if not isinstance(mapping, Mapping):
            raise LinterError("gates.linter must be a mapping of threshold names")

        changes: dict[str, Any] = {}
        integer_keys = (
            "repeated_phrase_min_count",
            "overused_word_min_count",
            "tic_min_count",
            "uniform_min_sentences",
            "paragraph_opener_words",
            "paragraph_opener_min_count",
            "banned_phrase_min_count",
        )
        for key in integer_keys:
            if key in mapping:
                changes[key] = _as_int(mapping[key], f"gates.linter.{key}")
                if changes[key] < 0:
                    raise LinterError(f"gates.linter.{key} must be zero or more")
        for key in ("overused_word_per_1000", "tic_per_1000", "uniform_sentence_stdev"):
            if key in mapping:
                changes[key] = _as_float(mapping[key], f"gates.linter.{key}")
                if changes[key] < 0:
                    raise LinterError(f"gates.linter.{key} must be zero or more")

        if "repeated_phrase_lengths" in mapping:
            raw = mapping["repeated_phrase_lengths"]
            if not isinstance(raw, (list, tuple)) or not raw:
                raise LinterError("gates.linter.repeated_phrase_lengths must be a non-empty list")
            lengths = []
            for value in raw:
                length = _as_int(value, "gates.linter.repeated_phrase_lengths")
                if length < 1:
                    raise LinterError("gates.linter.repeated_phrase_lengths needs positive numbers")
                lengths.append(length)
            changes["repeated_phrase_lengths"] = tuple(sorted(set(lengths)))

        for key in ("tic_words", "ignore_words"):
            if key in mapping:
                raw = mapping[key]
                if isinstance(raw, str) or not isinstance(raw, (list, tuple)):
                    raise LinterError(f"gates.linter.{key} must be a list of words")
                values = []
                for value in raw:
                    word = str(value).strip().casefold()
                    if word:
                        values.append(word)
                changes[key] = tuple(values)

        return replace(cls(), **changes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "repeated_phrase_lengths": list(self.repeated_phrase_lengths),
            "repeated_phrase_min_count": self.repeated_phrase_min_count,
            "overused_word_min_count": self.overused_word_min_count,
            "overused_word_per_1000": self.overused_word_per_1000,
            "tic_words": list(self.tic_words),
            "tic_min_count": self.tic_min_count,
            "tic_per_1000": self.tic_per_1000,
            "uniform_sentence_stdev": self.uniform_sentence_stdev,
            "uniform_min_sentences": self.uniform_min_sentences,
            "paragraph_opener_words": self.paragraph_opener_words,
            "paragraph_opener_min_count": self.paragraph_opener_min_count,
            "banned_phrase_min_count": self.banned_phrase_min_count,
        }


@dataclass
class LintReport:
    chapter: str
    words: int
    sentences: int
    paragraphs: int
    passed: bool
    counts: dict[str, int]
    findings: dict[str, Any]
    thresholds: dict[str, Any]
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chapter": self.chapter,
            "passed": self.passed,
            "words": self.words,
            "sentences": self.sentences,
            "paragraphs": self.paragraphs,
            "counts": dict(self.counts),
            "findings": self.findings,
            "thresholds": self.thresholds,
            "notes": list(self.notes),
        }


def _as_int(value: Any, where: str) -> int:
    if isinstance(value, bool):
        raise LinterError(f"{where} must be a whole number")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise LinterError(f"{where} must be a whole number") from exc
    if isinstance(value, float) and value != number:
        raise LinterError(f"{where} must be a whole number")
    return number


def _as_float(value: Any, where: str) -> float:
    if isinstance(value, bool):
        raise LinterError(f"{where} must be a number")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise LinterError(f"{where} must be a number") from exc


def _tokens(text: str) -> list[tuple[str, int]]:
    """(normalised word, 1-based line) for every word-like token, in order."""
    tokens: list[tuple[str, int]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for match in TOKEN_RE.finditer(line):
            tokens.append((match.group(0).casefold().replace("\u2019", "'"), number))
    return tokens


def _unique(numbers: Iterable[int]) -> list[int]:
    seen: set[int] = set()
    ordered: list[int] = []
    for number in numbers:
        if number not in seen:
            seen.add(number)
            ordered.append(number)
    return ordered


def _repeated_phrases(
    tokens: Sequence[tuple[str, int]], options: Options
) -> list[dict[str, Any]]:
    occurrences: dict[str, list[int]] = {}
    for size in options.repeated_phrase_lengths:
        for start in range(len(tokens) - size + 1):
            words = tokens[start : start + size]
            phrase = " ".join(word for word, _ in words)
            occurrences.setdefault(phrase, []).append(words[0][1])

    candidates = [
        (phrase, lines)
        for phrase, lines in occurrences.items()
        if len(lines) >= options.repeated_phrase_min_count
    ]
    # Keep the longest useful form: "the brass key" subsumes "brass key" when both repeat.
    candidates.sort(key=lambda item: (-len(item[0].split()), -len(item[1]), item[0]))
    kept: list[tuple[str, list[int]]] = []
    for phrase, lines in candidates:
        if any(
            f" {phrase} " in f" {longer} " and len(lines) <= len(longer_lines)
            for longer, longer_lines in kept
        ):
            continue
        kept.append((phrase, lines))

    return [
        {"phrase": phrase, "count": len(lines), "lines": _unique(lines)}
        for phrase, lines in kept
    ]


def _overused_words(
    tokens: Sequence[tuple[str, int]], options: Options
) -> list[dict[str, Any]]:
    total_words = len(tokens)
    if total_words == 0:
        return []
    ignored = {word.casefold() for word in options.ignore_words}
    counts: dict[str, list[int]] = {}
    for word, line in tokens:
        if len(word) <= 2 or word in ignored or not any(char.isalpha() for char in word):
            continue
        counts.setdefault(word, []).append(line)

    findings = []
    for word, lines in counts.items():
        per_1000 = len(lines) / total_words * 1000
        if len(lines) < options.overused_word_min_count:
            continue
        if per_1000 < options.overused_word_per_1000:
            continue
        findings.append(
            {
                "word": word,
                "count": len(lines),
                "per_1000": round(per_1000, 1),
                "lines": _unique(lines),
            }
        )
    findings.sort(key=lambda item: (-item["count"], item["word"]))
    return findings


def _tic_words(tokens: Sequence[tuple[str, int]], options: Options) -> list[dict[str, Any]]:
    total_words = len(tokens)
    if total_words == 0:
        return []
    wanted = {word.casefold() for word in options.tic_words}
    counts: dict[str, list[int]] = {}
    for word, line in tokens:
        if word in wanted:
            counts.setdefault(word, []).append(line)

    findings = []
    for word, lines in counts.items():
        per_1000 = len(lines) / total_words * 1000
        if len(lines) < options.tic_min_count or per_1000 < options.tic_per_1000:
            continue
        findings.append(
            {
                "word": word,
                "count": len(lines),
                "per_1000": round(per_1000, 1),
                "lines": _unique(lines),
            }
        )
    findings.sort(key=lambda item: (-item["count"], item["word"]))
    return findings


def _sentences(text: str) -> list[dict[str, Any]]:
    sentences: list[dict[str, Any]] = []
    start = 0
    boundaries = list(SENTENCE_END_RE.finditer(text))
    chunks: list[tuple[int, str]] = []
    for match in boundaries:
        chunks.append((start, text[start : match.end()]))
        start = match.end()
    chunks.append((start, text[start:]))

    for chunk_start, chunk in chunks:
        stripped = chunk.strip()
        if not stripped:
            continue
        words = TOKEN_RE.findall(stripped)
        if not words:
            continue
        leading = len(chunk) - len(chunk.lstrip())
        absolute = chunk_start + leading
        line = text.count("\n", 0, absolute) + 1
        sentences.append({"words": len(words), "line": line})
    return sentences


def _uniform_sentence_length(
    sentences: Sequence[Mapping[str, Any]], options: Options
) -> dict[str, Any] | None:
    if len(sentences) < options.uniform_min_sentences:
        return None
    lengths = [int(sentence["words"]) for sentence in sentences]
    stdev = statistics.pstdev(lengths)
    if stdev > options.uniform_sentence_stdev:
        return None
    return {
        "mean": round(statistics.fmean(lengths), 1),
        "stdev": round(stdev, 1),
        "min": min(lengths),
        "max": max(lengths),
        "lines": _unique(int(sentence["line"]) for sentence in sentences),
    }


def _banned_phrases(
    lines: Sequence[str], phrases: Iterable[str], options: Options
) -> list[dict[str, Any]]:
    findings = []
    for raw in phrases:
        phrase = str(raw).strip()
        if not phrase:
            continue
        needle = phrase.casefold()
        found_lines: list[int] = []
        count = 0
        for number, line in enumerate(lines, start=1):
            hits = line.casefold().count(needle)
            if hits:
                count += hits
                found_lines.append(number)
        if count < options.banned_phrase_min_count:
            continue
        findings.append(
            {"phrase": phrase, "count": count, "lines": _unique(found_lines)}
        )
    findings.sort(key=lambda item: (-item["count"], item["phrase"]))
    return findings


def _paragraphs(text: str) -> list[tuple[int, str]]:
    paragraphs: list[tuple[int, str]] = []
    current: list[str] = []
    start = 0
    for number, line in enumerate(text.splitlines(), start=1):
        if line.strip():
            if not current:
                start = number
            current.append(line)
        elif current:
            paragraphs.append((start, "\n".join(current)))
            current = []
    if current:
        paragraphs.append((start, "\n".join(current)))
    return paragraphs


def _repeated_openers(
    paragraphs: Sequence[tuple[int, str]], options: Options
) -> list[dict[str, Any]]:
    counts: dict[str, list[int]] = {}
    for line, paragraph in paragraphs:
        words = TOKEN_RE.findall(paragraph)
        if not words:
            continue
        opener = " ".join(
            word.casefold().replace("\u2019", "'")
            for word in words[: options.paragraph_opener_words]
        )
        counts.setdefault(opener, []).append(line)

    findings = [
        {"opener": opener, "count": len(lines), "lines": _unique(lines)}
        for opener, lines in counts.items()
        if len(lines) >= options.paragraph_opener_min_count
    ]
    findings.sort(key=lambda item: (-item["count"], item["opener"]))
    return findings


def lint_text(
    text: str,
    *,
    options: Options | None = None,
    banned_phrases: Iterable[str] = (),
    chapter: str = "",
) -> LintReport:
    """Run every deterministic check over one chapter's text."""
    options = options or Options()
    lines = text.splitlines()
    tokens = _tokens(text)
    sentences = _sentences(text)
    paragraphs = _paragraphs(text)

    repeated = _repeated_phrases(tokens, options)
    overused = _overused_words(tokens, options)
    uniform = _uniform_sentence_length(sentences, options)
    banned = _banned_phrases(lines, banned_phrases, options)
    tics = _tic_words(tokens, options)
    openers = _repeated_openers(paragraphs, options)

    counts = {
        "repeated_phrases": len(repeated),
        "overused_words": len(overused),
        "uniform_sentence_length": 1 if uniform is not None else 0,
        "banned_phrases": len(banned),
        "tic_words": len(tics),
        "repeated_paragraph_openers": len(openers),
    }
    return LintReport(
        chapter=chapter,
        words=len(tokens),
        sentences=len(sentences),
        paragraphs=len(paragraphs),
        passed=not any(counts.values()),
        counts=counts,
        findings={
            "repeated_phrases": repeated,
            "overused_words": overused,
            "uniform_sentence_length": uniform,
            "banned_phrases": banned,
            "tic_words": tics,
            "repeated_paragraph_openers": openers,
        },
        thresholds=options.to_dict(),
    )


def lint_file(
    path: Path | str,
    *,
    options: Options | None = None,
    banned_phrases: Iterable[str] = (),
) -> LintReport:
    chapter_path = Path(path)
    try:
        text = chapter_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise LinterError(f"chapter file {chapter_path} is unreadable: {exc}") from exc
    return lint_text(
        text,
        options=options,
        banned_phrases=banned_phrases,
        chapter=chapter_path.name,
    )


def load_banned_phrases(path: Path | str) -> list[str]:
    """Read tables/banned_phrases.json; a missing or broken table falls back to the starter list."""
    table = Path(path)
    if table.is_dir():
        table = table / "banned_phrases.json"
    if not table.is_file():
        return list(STARTER_PHRASES)
    try:
        raw = json.loads(table.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return list(STARTER_PHRASES)
    entries = raw.get("entries") if isinstance(raw, Mapping) else None
    phrases = [
        str(entry.get("value") or "").strip()
        for entry in entries or []
        if isinstance(entry, Mapping) and str(entry.get("value") or "").strip()
    ]
    return phrases or list(STARTER_PHRASES)


def _line_list(lines: Iterable[int]) -> str:
    return ", ".join(str(line) for line in lines)


def render_markdown(report: LintReport, *, title: str | None = None) -> str:
    """The revision-loop summary: one section per check, with counts and line numbers."""
    heading = title or report.chapter or "(untitled chapter)"
    lines = [
        f"# Linter report: {heading}",
        "",
        f"- status: {'passed' if report.passed else 'failed'}",
        f"- words: {report.words} ({report.sentences} sentences, {report.paragraphs} paragraphs)",
    ]
    for name in CHECK_NAMES:
        lines.append(f"- {name.replace('_', ' ')}: {report.counts[name]}")
    lines.append("")

    sections = (
        (
            "Repeated phrases",
            "repeated_phrases",
            lambda finding: (
                f'- "{finding["phrase"]}" x{finding["count"]} '
                f'(lines {_line_list(finding["lines"])})'
            ),
        ),
        (
            "Overused words",
            "overused_words",
            lambda finding: (
                f'- "{finding["word"]}" x{finding["count"]} '
                f'({finding["per_1000"]} per 1,000 words; lines '
                f'{_line_list(finding["lines"])})'
            ),
        ),
        (
            "Banned phrases",
            "banned_phrases",
            lambda finding: (
                f'- "{finding["phrase"]}" x{finding["count"]} '
                f'(lines {_line_list(finding["lines"])})'
            ),
        ),
        (
            "Tic words",
            "tic_words",
            lambda finding: (
                f'- "{finding["word"]}" x{finding["count"]} '
                f'({finding["per_1000"]} per 1,000 words; lines '
                f'{_line_list(finding["lines"])})'
            ),
        ),
        (
            "Repeated paragraph openers",
            "repeated_paragraph_openers",
            lambda finding: (
                f'- "{finding["opener"]}" x{finding["count"]} '
                f'(lines {_line_list(finding["lines"])})'
            ),
        ),
    )
    for title_text, key, render in sections:
        values = report.findings[key]
        lines += [f"## {title_text}", ""]
        if values:
            lines.extend(render(finding) for finding in values)
        else:
            lines.append("None.")
        lines.append("")

    uniform = report.findings["uniform_sentence_length"]
    lines += ["## Uniform sentence length", ""]
    if uniform is None:
        lines.append(
            f"Not flagged (needs at least {report.thresholds['uniform_min_sentences']} "
            f"sentences below a standard deviation of "
            f"{report.thresholds['uniform_sentence_stdev']})."
        )
    else:
        lines.append(
            f"- mean {uniform['mean']} words, stdev {uniform['stdev']} "
            f"(range {uniform['min']}-{uniform['max']}; lines "
            f"{_line_list(uniform['lines'])})"
        )
    lines.append("")
    return "\n".join(lines)
