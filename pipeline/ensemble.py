"""Ensemble check (BUILD_SPEC.md section 8): cheap code checks, then judgment.

The code checks are deterministic and always run: one age, one gender or one temperament,
two characters sharing a voice tic, and too many characters tagged "quirky and clever".
The checks that need reading (conflicting wants, a flaw that exists only to be fixed,
stereotyped portrayals) go to a checker-tier model, which must reply with JSON. A model
that cannot answer is reported as a note instead of silently passing or failing the cast.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from .adapters.base import LLMAdapter
from .schemas import Cast, Character

MAX_QUIRKY_SHARE = 0.4
MIN_QUIRKY_TO_FLAG = 2

JUDGMENT_SYSTEM = (
    "You are the ensemble editor for a novel. Judge the cast only on the questions asked. "
    "Reply with JSON only."
)

JUDGMENT_KINDS = ("conflicting_wants", "flaw_only_to_be_fixed", "stereotype")


@dataclass(frozen=True)
class Issue:
    code: str
    detail: str
    characters: tuple[str, ...] = ()


@dataclass
class EnsembleReport:
    issues: list[Issue] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.issues

    def codes(self) -> set[str]:
        return {issue.code for issue in self.issues}


def temperament(character: Character) -> str:
    """The cast-level temperament proxy: how the character's voice moves."""
    return character.voice.rhythm.strip().casefold()


def code_checks(cast: Cast) -> list[Issue]:
    characters = cast.characters
    issues: list[Issue] = []

    if len(characters) >= 2:
        if len({str(character.age).strip().casefold() for character in characters}) == 1:
            issues.append(
                Issue(
                    "cast_one_age",
                    f"every character is {characters[0].age}; vary the ages so the cast is not one cohort",
                    tuple(character.id for character in characters),
                )
            )
        if len({character.gender.strip().casefold() for character in characters}) == 1:
            issues.append(
                Issue(
                    "cast_one_gender",
                    f"every character is {characters[0].gender}; the cast has one gender",
                    tuple(character.id for character in characters),
                )
            )
        if len({temperament(character) for character in characters}) == 1:
            issues.append(
                Issue(
                    "cast_one_temperament",
                    f"every character shares the voice rhythm {characters[0].voice.rhythm!r}",
                    tuple(character.id for character in characters),
                )
            )

    for index, left in enumerate(characters):
        for right in characters[index + 1 :]:
            shared = {tic.casefold() for tic in left.voice.tics} & {
                tic.casefold() for tic in right.voice.tics
            }
            for tic in sorted(shared):
                issues.append(
                    Issue(
                        "shared_voice_tic",
                        f"{left.name} and {right.name} both use the voice tic {tic!r}",
                        (left.id, right.id),
                    )
                )

    quirky = [
        character
        for character in characters
        if any("quirky" in tag.casefold() for tag in character.tags)
    ]
    if (
        len(quirky) >= MIN_QUIRKY_TO_FLAG
        and len(quirky) / len(characters) > MAX_QUIRKY_SHARE
    ):
        issues.append(
            Issue(
                "too_many_quirky_and_clever",
                f"{len(quirky)} of {len(characters)} characters are tagged quirky and clever",
                tuple(character.id for character in quirky),
            )
        )

    return issues


def judgment_prompt(cast: Cast) -> str:
    lines = []
    for character in cast.characters:
        core = character.emotional_core
        lines.append(
            " | ".join(
                [
                    character.id,
                    character.name,
                    character.role,
                    f"want: {core.want or '(none)'}",
                    f"stakes: {core.stakes or '(none)'}",
                    f"flaw: {character.flaw or '(none)'}",
                    f"false belief: {core.false_belief or '(none)'}",
                    f"coping habit: {core.coping_habit or '(none)'}",
                ]
            )
        )

    return (
        "Read this cast and flag only these problems:\n"
        "1. two characters whose wants cannot both be satisfied (conflicting_wants);\n"
        "2. a flaw that exists only so the protagonist can fix it (flaw_only_to_be_fixed);\n"
        "3. a stereotyped portrayal (stereotype).\n"
        "Do not flag variety, quality or taste. If the cast is fine, return no issues.\n\n"
        "Reply with JSON only, in this shape:\n"
        '{"issues": [{"kind": "conflicting_wants", "characters": ["id"], "detail": "one line"}]}\n\n'
        "Cast:\n" + "\n".join(lines)
    )


def parse_judgment(reply: str) -> list[Issue]:
    """Turn a checker reply into issues, or raise ValueError with a readable reason."""
    text = reply.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"checker reply was not JSON: {reply[:120]!r}")
    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"checker reply was not usable JSON ({exc}): {reply[:120]!r}") from exc

    items = payload.get("issues") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise ValueError("checker reply has no 'issues' list")

    issues: list[Issue] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("checker reply has an issue that is not an object")
        kind = str(item.get("kind") or "").strip().casefold()
        if not kind:
            raise ValueError("checker reply has an issue without a kind")
        code = "judgment_" + re.sub(r"[^a-z0-9]+", "_", kind).strip("_")
        detail = str(item.get("detail") or "").strip() or f"checker flagged {kind}"
        characters = item.get("characters") or []
        if not isinstance(characters, (list, tuple)):
            raise ValueError(f"checker reply for {kind!r} has non-list 'characters'")
        issues.append(
            Issue(
                code=code,
                detail=detail,
                characters=tuple(str(character).strip() for character in characters if str(character).strip()),
            )
        )
    return issues


def render_ensemble(cast: Cast, report: EnsembleReport, notes: list[str] | tuple[str, ...] = ()) -> str:
    lines = [
        "# Ensemble check",
        "",
        f"cast: {len(cast.characters)} characters",
        f"status: {'passed' if report.passed else 'flagged'}",
        "",
    ]
    if report.issues:
        lines.extend(["## Findings", ""])
        for issue in report.issues:
            characters = f" (characters: {', '.join(issue.characters)})" if issue.characters else ""
            lines.append(f"- {issue.code}: {issue.detail}{characters}")
        lines.append("")
    else:
        lines.extend(["No findings.", ""])

    if notes:
        lines.extend(["## Notes", ""])
        lines.extend(f"- {note}" for note in notes)
        lines.append("")
    return "\n".join(lines)


def check_ensemble(cast: Cast, llm: LLMAdapter | None = None) -> EnsembleReport:
    issues = code_checks(cast)
    notes: list[str] = []

    if llm is not None:
        reply = llm.complete(
            judgment_prompt(cast),
            system=JUDGMENT_SYSTEM,
            model_tier="checker",
            max_tokens=900,
        )
        try:
            issues.extend(parse_judgment(reply))
        except ValueError as exc:
            notes.append(f"judgment checks skipped: {exc}")

    return EnsembleReport(issues=issues, notes=notes)
