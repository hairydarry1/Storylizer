"""Strict JSON replies, checked and retried.

M6b makes stages 11 and 12 model-authored, but only inside code-assigned constraints. Both
ask for one small JSON object per chapter, so the shared parts live here: pulling the object
out of a chatty reply, finding banned phrases, spotting near-duplicate text, and the retry
loop that feeds the validation errors back to the model.

There is no template fallback anywhere in this module. A reply that is still invalid after
the last attempt is a stage failure.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .narrator_voice import STARTER_PHRASES, banned_phrases_path

MAX_ATTEMPTS = 3
#: Jaccard similarity of word sets at or above this counts as a near-duplicate.
NEAR_DUPLICATE = 0.8


class ReplyError(ValueError):
    """The reply did not contain a usable JSON object."""


# --------------------------------------------------------------------------- parsing


def extract_json(reply: str) -> Any:
    """The first JSON value in a reply, tolerating fences and prose around the object."""
    text = (reply or "").strip()
    if not text:
        raise ReplyError("the reply was empty")

    if text.startswith("```"):
        body = text.split("```", 2)[1]
        if body.lstrip().casefold().startswith("json"):
            body = body.lstrip()[4:]
        text = body.strip().rstrip("`").strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    if start < 0:
        raise ReplyError("the reply contains no JSON object")

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        character = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                chunk = text[start : index + 1]
                try:
                    return json.loads(chunk)
                except json.JSONDecodeError as exc:
                    raise ReplyError(f"the JSON object is invalid: {exc}") from exc

    raise ReplyError("the JSON object is not closed")


# --------------------------------------------------------------------------- text checks


def load_banned_phrases(tables_dir: Path | str) -> list[str]:
    """The banned phrases from tables/banned_phrases.json, with the starter list as backup."""
    path = banned_phrases_path(tables_dir)
    if not path.is_file():
        return list(STARTER_PHRASES)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return list(STARTER_PHRASES)

    entries = raw.get("entries") if isinstance(raw, Mapping) else None
    phrases = [
        str(entry.get("value") or "").strip()
        for entry in entries or []
        if isinstance(entry, Mapping) and str(entry.get("value") or "").strip()
    ]
    return phrases or list(STARTER_PHRASES)


def banned_hits(texts: Iterable[str], phrases: Sequence[str]) -> list[str]:
    """Every banned phrase that occurs in any of the texts, case-insensitively."""
    haystack = " \n ".join(str(text or "").casefold() for text in texts)
    hits: list[str] = []
    for phrase in phrases:
        cleaned = str(phrase).strip()
        if cleaned and cleaned.casefold() in haystack and cleaned not in hits:
            hits.append(cleaned)
    return hits


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", str(text or "").casefold())).strip()


def _words(text: str) -> set[str]:
    return set(normalize(text).split())


def is_near_duplicate(text: str, others: Sequence[str]) -> bool:
    """True when `text` repeats or nearly repeats one of `others`."""
    normalized = normalize(text)
    if not normalized:
        return False
    words = _words(normalized)
    for other in others:
        other_normalized = normalize(other)
        if not other_normalized:
            continue
        if normalized == other_normalized:
            return True
        other_words = _words(other_normalized)
        union = words | other_words
        if union and len(words & other_words) / len(union) >= NEAR_DUPLICATE:
            return True
    return False


# --------------------------------------------------------------------------- partial work


def load_partial(path: Path | str | None, notes: list[str] | None = None) -> dict[int, dict[str, Any]]:
    """Validated chapters saved by an interrupted run, keyed by chapter number.

    An unreadable or malformed file is ignored with a note, never a crash: the run simply
    authors every chapter again.
    """
    notes = notes if notes is not None else []
    if path is None:
        return {}
    partial = Path(path)
    if not partial.is_file():
        return {}
    try:
        raw = json.loads(partial.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        notes.append(f"ignored the partial file {partial.name}: {exc}")
        return {}
    entries = raw.get("chapters") if isinstance(raw, Mapping) else None
    if not isinstance(entries, list):
        notes.append(f"ignored the partial file {partial.name}: it has no chapters list")
        return {}

    saved: dict[int, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        number = entry.get("number")
        if isinstance(number, bool) or not isinstance(number, int):
            continue
        saved[number] = {key: value for key, value in entry.items() if key != "number"}
    return saved


def save_partial(path: Path | str | None, entries: Mapping[int, Mapping[str, Any]]) -> None:
    """Write the validated chapters so a rerun can continue from the first missing one."""
    if path is None:
        return
    partial = Path(path)
    partial.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "chapters": [
            {"number": number, **dict(entries[number])} for number in sorted(entries)
        ]
    }
    partial.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- retries


def request_json(
    llm: Any,
    prompt_for: Callable[[Sequence[str]], str],
    validate: Callable[[Any], list[str]],
    *,
    system: str | None = None,
    model_tier: str | None = None,
    max_attempts: int = MAX_ATTEMPTS,
    max_tokens: int = 1500,
) -> tuple[Any | None, int, list[str]]:
    """Ask for JSON until `validate` accepts it, feeding the errors back each time.

    Returns `(payload, attempts, [])` on success and `(None, attempts, errors)` when the last
    attempt is still invalid. Every attempt is one `llm.complete` call.
    """
    errors: list[str] = []
    for attempt in range(1, max_attempts + 1):
        prompt = prompt_for(errors)
        try:
            reply = llm.complete(
                prompt, system=system, model_tier=model_tier, max_tokens=max_tokens
            )
        except Exception as exc:  # an adapter error is a failed attempt, not a crash
            errors = [f"the model call failed: {exc}"]
            continue
        try:
            payload = extract_json(reply)
        except ReplyError as exc:
            errors = [str(exc)]
            continue
        errors = validate(payload)
        if not errors:
            return payload, attempt, []
    return None, max_attempts, errors
