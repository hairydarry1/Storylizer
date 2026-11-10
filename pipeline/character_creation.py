"""Deterministic cast drafts for stage 8 (character_creation).

The randomizer is the source of truth: the protagonist's name, quirk, flaw and talent come
straight from the stage 8 rolls, and secondary characters are built around role frames so the
pipeline always has a valid cast even when the configured model returns prose or nothing
useful. A model reply that parses and validates replaces the draft; anything else is reported
and the draft stands.
"""

from __future__ import annotations

import json
import random
from typing import Any, Mapping, Sequence

import yaml

from . import schemas
from .randomizer import Roll, seed_int

CAST_ROLES = ("protagonist", "foil", "mentor", "ally")

SECONDARY_FRAMES: dict[str, dict[str, Any]] = {
    "foil": {
        "occupation": "council assessor",
        "age": 58,
        "gender": "man",
        "rhythm": "measured",
        "vocabulary": "formal, careful",
        "tic": "clears his throat before lying",
        "never_says": ["I was wrong"],
        "want": "to be chosen as the next keeper of the record",
        "need": "to be useful without being owned",
        "wound": "spent twenty years being someone else's evidence",
        "false_belief": "the institution rewards patience",
        "fear": "becoming unnecessary",
        "coping_habit": "files things that do not need filing",
        "start_state": "already counting the cost",
        "stakes": "the only standing he has in town",
        "flaw": "mistakes loyalty for proof",
        "background": "came up through the council's back office and never left it",
        "look": {
            "build": "narrow-shouldered",
            "hair": "grey, combed flat",
            "skin": "pale",
            "signature_clothing": "a council sash worn over a working coat",
        },
        "bond": "old colleague",
        "friction": "only one of them can hold the record",
    },
    "mentor": {
        "occupation": "index clerk",
        "age": 71,
        "gender": "woman",
        "rhythm": "meandering",
        "vocabulary": "archaic, exact",
        "tic": "repeats the last three words of a question before answering",
        "never_says": ["it cannot be done"],
        "want": "to finish the index before her memory gives out",
        "need": "to hand the work to someone who will not simplify it",
        "wound": "watched the first index burn and was told to start again",
        "false_belief": "an unfinished record is a failure",
        "fear": "forgetting the order of things",
        "coping_habit": "writes the day's date on her wrist",
        "start_state": "pretending the work is nearly done",
        "stakes": "the last person who trusts her judgment",
        "flaw": "tells the truth as a test",
        "background": "kept every index in the building for forty years",
        "look": {
            "build": "small, precise",
            "hair": "white braid",
            "skin": "deep brown",
            "signature_clothing": "fingerless gloves and a cardigan with ink on both cuffs",
        },
        "bond": "teacher",
        "friction": "she will not lend the index, only teach it",
    },
    "ally": {
        "occupation": "courier",
        "age": 22,
        "gender": "non-binary",
        "rhythm": "quick and dry",
        "vocabulary": "plain, current",
        "tic": "quotes prices in old currency",
        "never_says": ["that is not my problem"],
        "want": "to get out of town without leaving anyone behind",
        "need": "to stop treating every favour as a debt",
        "wound": "was the child sent to settle the family's accounts",
        "false_belief": "if you owe nothing, you are free",
        "fear": "being the one who is left",
        "coping_habit": "counts change twice",
        "start_state": "half-packed and pretending not to be",
        "stakes": "a sibling who works for the people they are robbing",
        "flaw": "agrees first and argues later",
        "background": "runs parcels between the record office and the river",
        "look": {
            "build": "quick, angular",
            "hair": "shaved at the sides",
            "skin": "light brown",
            "signature_clothing": "a courier's satchel with three replacement straps",
        },
        "bond": "accomplice",
        "friction": "the ally wants out; the protagonist needs them to stay",
    },
}

PROTAGONIST_LOOK = {
    "build": "wiry",
    "hair": "black, cut short with a knife",
    "skin": "brown",
    "signature_clothing": "a grey coat with too many pockets",
}


def _protagonist(rolled: Mapping[str, str], concept: Mapping[str, Any], name: str, tic: str) -> dict[str, Any]:
    premise = str(concept.get("premise_seed") or "").strip()
    marks = []
    mark = rolled.get("physical_mark")
    if mark:
        marks.append(
            {
                "what": mark,
                "meaning": "noticed before she is heard; she has learned to use it as a clock",
                "placement": "left forearm",
            }
        )
    return {
        "id": "protagonist",
        "name": name,
        "role": "protagonist",
        "gender": "woman",
        "age": 34,
        "occupation": "ledger keeper",
        "background": premise or "grew up inside the institution they now work for",
        "look": {**PROTAGONIST_LOOK, "marks": marks},
        "physical_differences": [],
        "intelligence_profile": {
            "sharp_at": [rolled.get("talent") or "ledgers and who owes whom"],
            "blind_at": [rolled.get("blind_spot") or "flattery"],
            "overconfident_about": ["her memory for faces"],
        },
        "emotional_core": {
            "want": "to keep the record out of the hands of the people who would use it",
            "need": "to trust one person with the part of the record she cannot amend",
            "wound": "was made the family's record-keeper at nine and never asked",
            "false_belief": "if the numbers are right, no one has to be forgiven",
            "fear": "being read as the person who kept the receipts",
            "coping_habit": rolled.get("quirk") or "counts exits when a room turns friendly",
            "start_state": rolled.get("emotional_start") or "braced for bad news that has not arrived",
            "arc_by_act": [
                "act 1: protects the record",
                "act 2: loses control of the record",
                "act 3: writes a true entry and pays for it",
            ],
            "laughs_at": "bureaucratic language used with total sincerity",
            "cries_at": "someone being kind without being asked",
            "stakes": "the only copy of the record that clears her mother",
        },
        "voice": {
            "rhythm": "clipped",
            "vocabulary": "precise, old-fashioned",
            "tics": [tic],
            "never_says": ["trust me"],
        },
        "relationships": [],
        "locked": [],
        "flaw": rolled.get("flaw") or "mistakes control for care",
        "quirk": rolled.get("quirk") or "",
        "talent": rolled.get("talent") or "",
        "tags": [],
    }


def _secondary(role: str, name: str) -> dict[str, Any]:
    frame = SECONDARY_FRAMES[role]
    return {
        "id": role,
        "name": name,
        "role": role,
        "gender": frame["gender"],
        "age": frame["age"],
        "occupation": frame["occupation"],
        "background": frame["background"],
        "look": {**frame["look"], "marks": []},
        "physical_differences": [],
        "intelligence_profile": {
            "sharp_at": [frame["occupation"]],
            "blind_at": [frame["fear"]],
            "overconfident_about": [frame["false_belief"]],
        },
        "emotional_core": {
            "want": frame["want"],
            "need": frame["need"],
            "wound": frame["wound"],
            "false_belief": frame["false_belief"],
            "fear": frame["fear"],
            "coping_habit": frame["coping_habit"],
            "start_state": frame["start_state"],
            "arc_by_act": [
                f"act 1: {frame['start_state']}",
                f"act 2: {frame['want']} costs more than expected",
                "act 3: chooses a different way to get it",
            ],
            "laughs_at": "other people's expense claims",
            "cries_at": "being thanked in public",
            "stakes": frame["stakes"],
        },
        "voice": {
            "rhythm": frame["rhythm"],
            "vocabulary": frame["vocabulary"],
            "tics": [frame["tic"]],
            "never_says": list(frame["never_says"]),
        },
        "relationships": [
            {"to": "protagonist", "bond": frame["bond"], "friction": frame["friction"]}
        ],
        "locked": [],
        "flaw": frame["flaw"],
        "quirk": "",
        "talent": "",
        "tags": [],
    }


def draft_cast(
    rolls: Sequence[Roll],
    concept: Mapping[str, Any],
    *,
    seed: int,
    names,
) -> schemas.Cast:
    """Build a valid cast from the stage 8 rolls; `names` is a randomizer.NameGenerator."""
    rolled = {roll.key: roll.value for roll in rolls}
    rng = random.Random(seed_int(seed, "08-character_creation", "cast_names"))

    protagonist_name = " ".join(
        part for part in (rolled.get("protagonist_given_name", ""), rolled.get("protagonist_family_name", "")) if part
    ).strip()
    if not protagonist_name:
        protagonist_name = f"{names.given(rng)} {names.family(rng)}"

    secondary_tic = {frame["tic"] for frame in SECONDARY_FRAMES.values()}
    tic = rolled.get("speech_tic") or ""
    if not tic or tic in secondary_tic:
        tic = "taps a pen twice before answering"

    data = [_protagonist(rolled, concept, protagonist_name, tic)]
    used_names = {protagonist_name.casefold()}
    used_given: set[str] = set()
    for role in CAST_ROLES[1:]:
        for _ in range(50):
            surname = names.family(rng, exclude=used_names)
            given = names.given(rng, exclude=used_given)
            full = f"{given} {surname}"
            if full.casefold() not in used_names:
                break
        used_names.add(full.casefold())
        used_given.add(given.casefold())
        data.append(_secondary(role, full))

    return schemas.cast_from_dict({"characters": data})


# --------------------------------------------------------------------------- model replies


def _extract_json(reply: str) -> Any:
    text = reply.strip()
    if text.startswith("```"):
        lines = text.splitlines()[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"model reply was not JSON: {reply[:120]!r}")
    return json.loads(text[start : end + 1])


def cast_from_reply(reply: str, draft: schemas.Cast) -> tuple[schemas.Cast, str | None]:
    """Use the model's cast when it validates; otherwise keep the draft and say why."""
    try:
        payload = _extract_json(reply)
    except (ValueError, json.JSONDecodeError) as exc:
        return draft, f"model cast unusable ({exc}); kept the validated draft"

    try:
        return schemas.cast_from_dict(payload), "cast came from the model reply"
    except schemas.SchemaError as exc:
        return draft, f"model cast rejected ({exc}); kept the validated draft"


def creation_prompt(
    skill,
    concept: Mapping[str, Any],
    rolls: Sequence[Roll],
    upstream: str,
    notes: Sequence[str],
) -> str:
    roll_lines = "\n".join(f"- {roll.key}: {roll.value}" for roll in rolls)
    sections = "\n\n".join(f"## {name}\n\n{text}" for name, text in skill.sections.items())
    upstream_text = upstream.strip() or "(no upstream stage output exists yet)"
    note_text = "\n".join(f"- {note}" for note in notes) or "- none"
    return (
        f"{sections}\n\n"
        "## This project\n\n"
        "concept.yaml:\n"
        f"```yaml\n{yaml.safe_dump(dict(concept), sort_keys=False)}```\n\n"
        "Randomizer rolls (constraints, not suggestions):\n"
        f"{roll_lines}\n\n"
        "Earlier stage outputs:\n"
        f"{upstream_text}\n\n"
        "Notes:\n"
        f"{note_text}\n\n"
        "Reply with JSON only: {\"characters\": [...]} following the sheet format above.\n"
    )


def render_cast(
    cast: schemas.Cast,
    concept: Mapping[str, Any],
    notes: Sequence[str],
    model_reply: str | None = None,
) -> str:
    title = str(concept.get("working_title") or "").strip() or "Untitled"
    lines = [f"# Cast — {title}", ""]
    for character in cast.characters:
        core = character.emotional_core
        lines.extend(
            [
                f"## {character.name} — {character.role} ({character.id})",
                "",
                f"- {character.gender}, {character.age}, {character.occupation}",
                f"- background: {character.background}",
                f"- want: {core.want or '(none)'}",
                f"- need: {core.need or '(none)'}",
                f"- stakes: {core.stakes or '(none)'}",
                f"- flaw: {character.flaw or '(none)'}",
            ]
        )
        if character.quirk:
            lines.append(f"- quirk: {character.quirk}")
        if character.talent:
            lines.append(f"- talent: {character.talent}")
        lines.append(f"- voice: {character.voice.rhythm}; {character.voice.vocabulary}")
        if character.voice.tics:
            lines.append(f"- tics: {'; '.join(character.voice.tics)}")
        for relationship in character.relationships:
            lines.append(
                f"- relationship: {relationship.to} ({relationship.bond}; {relationship.friction})"
            )
        lines.append("")

    if notes:
        lines.extend(["## Notes", ""])
        lines.extend(f"- {note}" for note in notes)
        lines.append("")

    if model_reply and model_reply.strip():
        lines.extend(["## Model reply", "", "```text", model_reply.strip()[:4000], "```", ""])

    return "\n".join(lines)
