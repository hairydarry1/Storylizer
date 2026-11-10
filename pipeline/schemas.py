"""Character sheets and casts (BUILD_SPEC.md section 4), with the M3 rules enforced.

Validation is deliberately explicit rather than lenient: a sheet that reaches the outline
stage is load-bearing, so a missing want or a dangling relationship has to fail here.

Two rules are not in the spec's field list but are required by the milestone:

* Every secondary character carries its own ``stakes`` inside ``emotional_core``.
* ``flaw``, ``quirk``, ``talent`` and ``tags`` are kept on the sheet because the randomizer
  rolls them and the ensemble check has to see them.

A numeric IQ is rejected anywhere in the input, at any depth. There is no accepted place
for one; ``intelligence_profile`` is the only intelligence field.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


class SchemaError(ValueError):
    """A character sheet or cast the pipeline cannot use."""


ROLES = ("protagonist", "foil", "mentor", "ally", "pressure", "comic", "wildcard")

REQUIRED_STRING_FIELDS = ("id", "name", "gender", "occupation", "background")

#: Normalised keys that mean "a numeric IQ lives here". `intelligence` counts too: the
#: supported home for intelligence is `intelligence_profile`.
IQ_KEYS = frozenset(
    {
        "iq",
        "iqscore",
        "intelligence",
        "intelligencescore",
        "intelligencequotient",
        "intelligencequotientscore",
    }
)

LOCKABLE_FORBIDDEN = frozenset({"id", "locked"})


# --------------------------------------------------------------------------- helpers


def _normalise_key(key: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).casefold())


def find_iq_fields(data: Any, path: str = "") -> list[str]:
    """Every path in `data` whose key denotes an IQ. Returned for error messages."""
    found: list[str] = []
    if isinstance(data, Mapping):
        for key, value in data.items():
            here = f"{path}.{key}" if path else str(key)
            normalised = _normalise_key(key)
            if normalised in IQ_KEYS or normalised.endswith("iq") or normalised.startswith("iq"):
                found.append(here)
            found.extend(find_iq_fields(value, here))
    elif isinstance(data, (list, tuple)):
        for index, item in enumerate(data):
            found.extend(find_iq_fields(item, f"{path}[{index}]"))
    return found


def _get_path(data: Mapping[str, Any], path: str, *, where: str) -> Any:
    current: Any = data
    walked: list[str] = []
    for part in path.split("."):
        walked.append(part)
        if not isinstance(current, Mapping) or part not in current:
            raise SchemaError(f"{where}: locked field {'.'.join(walked)!r} does not exist on the sheet")
        current = current[part]
    return current


def _set_path(data: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    current = data
    for part in parts[:-1]:
        current = current[part]
    current[parts[-1]] = value


def _require_string(data: Mapping[str, Any], key: str, *, where: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SchemaError(f"{where}: '{key}' must be a non-empty string")
    return value.strip()


def _optional_string(data: Mapping[str, Any], key: str, *, where: str, default: str = "") -> str:
    value = data.get(key, default)
    if value is None:
        return default
    if not isinstance(value, str):
        raise SchemaError(f"{where}: '{key}' must be a string")
    return value.strip()


def _string_tuple(data: Mapping[str, Any], key: str, *, where: str) -> tuple[str, ...]:
    value = data.get(key, [])
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise SchemaError(f"{where}: '{key}' must be a list of strings")
    items: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise SchemaError(f"{where}: '{key}' must contain non-empty strings")
        items.append(item.strip())
    return tuple(items)


def _mapping(data: Mapping[str, Any], key: str, *, where: str) -> Mapping[str, Any]:
    value = data.get(key)
    if not isinstance(value, Mapping):
        raise SchemaError(f"{where}: '{key}' must be an object")
    return value


def _list_of_mappings(data: Mapping[str, Any], key: str, *, where: str) -> list[Mapping[str, Any]]:
    value = data.get(key, [])
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise SchemaError(f"{where}: '{key}' must be a list")
    if not all(isinstance(item, Mapping) for item in value):
        raise SchemaError(f"{where}: '{key}' must contain objects")
    return list(value)


# --------------------------------------------------------------------------- dataclasses


@dataclass(frozen=True)
class Mark:
    what: str
    meaning: str
    placement: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, where: str) -> "Mark":
        return cls(
            what=_require_string(data, "what", where=where),
            meaning=_require_string(data, "meaning", where=where),
            placement=_require_string(data, "placement", where=where),
        )

    def to_dict(self) -> dict[str, str]:
        return {"what": self.what, "meaning": self.meaning, "placement": self.placement}


@dataclass(frozen=True)
class PhysicalDifference:
    what: str
    how_it_shapes_behavior: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, where: str) -> "PhysicalDifference":
        return cls(
            what=_require_string(data, "what", where=where),
            how_it_shapes_behavior=_require_string(data, "how_it_shapes_behavior", where=where),
        )

    def to_dict(self) -> dict[str, str]:
        return {"what": self.what, "how_it_shapes_behavior": self.how_it_shapes_behavior}


@dataclass(frozen=True)
class IntelligenceProfile:
    sharp_at: tuple[str, ...] = ()
    blind_at: tuple[str, ...] = ()
    overconfident_about: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, where: str) -> "IntelligenceProfile":
        return cls(
            sharp_at=_string_tuple(data, "sharp_at", where=where),
            blind_at=_string_tuple(data, "blind_at", where=where),
            overconfident_about=_string_tuple(data, "overconfident_about", where=where),
        )

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "sharp_at": list(self.sharp_at),
            "blind_at": list(self.blind_at),
            "overconfident_about": list(self.overconfident_about),
        }


@dataclass(frozen=True)
class EmotionalCore:
    want: str
    need: str
    wound: str
    false_belief: str
    fear: str
    coping_habit: str
    start_state: str
    arc_by_act: tuple[str, ...] = ()
    laughs_at: str = ""
    cries_at: str = ""
    stakes: str = ""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, where: str) -> "EmotionalCore":
        return cls(
            want=_optional_string(data, "want", where=where),
            need=_optional_string(data, "need", where=where),
            wound=_optional_string(data, "wound", where=where),
            false_belief=_optional_string(data, "false_belief", where=where),
            fear=_optional_string(data, "fear", where=where),
            coping_habit=_optional_string(data, "coping_habit", where=where),
            start_state=_optional_string(data, "start_state", where=where),
            arc_by_act=_string_tuple(data, "arc_by_act", where=where),
            laughs_at=_optional_string(data, "laughs_at", where=where),
            cries_at=_optional_string(data, "cries_at", where=where),
            stakes=_optional_string(data, "stakes", where=where),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "want": self.want,
            "need": self.need,
            "wound": self.wound,
            "false_belief": self.false_belief,
            "fear": self.fear,
            "coping_habit": self.coping_habit,
            "start_state": self.start_state,
            "arc_by_act": list(self.arc_by_act),
            "laughs_at": self.laughs_at,
            "cries_at": self.cries_at,
            "stakes": self.stakes,
        }


@dataclass(frozen=True)
class Voice:
    rhythm: str
    vocabulary: str
    tics: tuple[str, ...] = ()
    never_says: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, where: str) -> "Voice":
        return cls(
            rhythm=_require_string(data, "rhythm", where=where),
            vocabulary=_require_string(data, "vocabulary", where=where),
            tics=_string_tuple(data, "tics", where=where),
            never_says=_string_tuple(data, "never_says", where=where),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "rhythm": self.rhythm,
            "vocabulary": self.vocabulary,
            "tics": list(self.tics),
            "never_says": list(self.never_says),
        }


@dataclass(frozen=True)
class Relationship:
    to: str
    bond: str
    friction: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, where: str) -> "Relationship":
        return cls(
            to=_require_string(data, "to", where=where),
            bond=_require_string(data, "bond", where=where),
            friction=_require_string(data, "friction", where=where),
        )

    def to_dict(self) -> dict[str, str]:
        return {"to": self.to, "bond": self.bond, "friction": self.friction}


@dataclass(frozen=True)
class Look:
    build: str
    hair: str
    skin: str
    signature_clothing: str
    marks: tuple[Mark, ...] = ()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, where: str) -> "Look":
        marks = tuple(
            Mark.from_dict(item, where=f"{where}.marks[{index}]")
            for index, item in enumerate(_list_of_mappings(data, "marks", where=where))
        )
        return cls(
            build=_require_string(data, "build", where=where),
            hair=_require_string(data, "hair", where=where),
            skin=_require_string(data, "skin", where=where),
            signature_clothing=_require_string(data, "signature_clothing", where=where),
            marks=marks,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "build": self.build,
            "hair": self.hair,
            "skin": self.skin,
            "signature_clothing": self.signature_clothing,
            "marks": [mark.to_dict() for mark in self.marks],
        }


@dataclass(frozen=True)
class Character:
    id: str
    name: str
    role: str
    gender: str
    age: int | str
    occupation: str
    background: str
    look: Look
    intelligence_profile: IntelligenceProfile
    emotional_core: EmotionalCore
    voice: Voice
    relationships: tuple[Relationship, ...] = ()
    physical_differences: tuple[PhysicalDifference, ...] = ()
    locked: tuple[str, ...] = ()
    flaw: str = ""
    quirk: str = ""
    talent: str = ""
    tags: tuple[str, ...] = ()

    @property
    def is_secondary(self) -> bool:
        return self.role != "protagonist"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, where: str = "character") -> "Character":
        if not isinstance(data, Mapping):
            raise SchemaError(f"{where}: a character sheet must be an object")

        iq_paths = find_iq_fields(data)
        if iq_paths:
            raise SchemaError(
                f"{where}: numeric IQ field(s) {', '.join(iq_paths)}; "
                "remove them and use intelligence_profile instead"
            )

        character_id = _require_string(data, "id", where=where)
        where = f"character {character_id!r}"

        role = _require_string(data, "role", where=where).casefold()
        if role not in ROLES:
            raise SchemaError(f"{where}: unknown role {role!r} (use one of {', '.join(ROLES)})")

        age = data.get("age")
        if isinstance(age, bool) or not isinstance(age, (int, str)):
            raise SchemaError(f"{where}: 'age' must be a number or a non-empty string")
        if isinstance(age, int) and age < 0:
            raise SchemaError(f"{where}: 'age' cannot be negative")
        if isinstance(age, str) and not age.strip():
            raise SchemaError(f"{where}: 'age' must not be empty")

        emotional_core = EmotionalCore.from_dict(
            _mapping(data, "emotional_core", where=where), where=f"{where}.emotional_core"
        )
        if not emotional_core.want:
            raise SchemaError(f"{where}: 'emotional_core.want' must be a non-empty string")
        if role != "protagonist" and not emotional_core.stakes:
            raise SchemaError(
                f"{where}: secondary character {character_id!r} needs its own want and stakes "
                "('emotional_core.stakes' is empty)"
            )

        relationships = tuple(
            Relationship.from_dict(item, where=f"{where}.relationships[{index}]")
            for index, item in enumerate(_list_of_mappings(data, "relationships", where=where))
        )
        physical_differences = tuple(
            PhysicalDifference.from_dict(item, where=f"{where}.physical_differences[{index}]")
            for index, item in enumerate(_list_of_mappings(data, "physical_differences", where=where))
        )

        locked = _string_tuple(data, "locked", where=where)
        for path in locked:
            if path in LOCKABLE_FORBIDDEN:
                raise SchemaError(f"{where}: '{path}' cannot be locked")
            _get_path(data, path, where=where)
        if len(set(locked)) != len(locked):
            raise SchemaError(f"{where}: 'locked' lists a field twice")
        if "locked" in (path.split(".")[0] for path in locked):
            raise SchemaError(f"{where}: 'locked' cannot lock itself")

        return cls(
            id=character_id,
            name=_require_string(data, "name", where=where),
            role=role,
            gender=_require_string(data, "gender", where=where),
            age=age,
            occupation=_require_string(data, "occupation", where=where),
            background=_require_string(data, "background", where=where),
            look=Look.from_dict(_mapping(data, "look", where=where), where=f"{where}.look"),
            intelligence_profile=IntelligenceProfile.from_dict(
                _mapping(data, "intelligence_profile", where=where),
                where=f"{where}.intelligence_profile",
            ),
            emotional_core=emotional_core,
            voice=Voice.from_dict(_mapping(data, "voice", where=where), where=f"{where}.voice"),
            relationships=relationships,
            physical_differences=physical_differences,
            locked=locked,
            flaw=_optional_string(data, "flaw", where=where),
            quirk=_optional_string(data, "quirk", where=where),
            talent=_optional_string(data, "talent", where=where),
            tags=_string_tuple(data, "tags", where=where),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "gender": self.gender,
            "age": self.age,
            "occupation": self.occupation,
            "background": self.background,
            "look": self.look.to_dict(),
            "physical_differences": [item.to_dict() for item in self.physical_differences],
            "intelligence_profile": self.intelligence_profile.to_dict(),
            "emotional_core": self.emotional_core.to_dict(),
            "voice": self.voice.to_dict(),
            "relationships": [relationship.to_dict() for relationship in self.relationships],
            "locked": list(self.locked),
            "flaw": self.flaw,
            "quirk": self.quirk,
            "talent": self.talent,
            "tags": list(self.tags),
        }


@dataclass(frozen=True)
class Cast:
    characters: tuple[Character, ...] = ()

    @property
    def by_id(self) -> dict[str, Character]:
        return {character.id: character for character in self.characters}

    def get(self, character_id: str) -> Character:
        try:
            return self.by_id[character_id]
        except KeyError:
            raise SchemaError(f"cast has no character {character_id!r}") from None

    @classmethod
    def from_dict(cls, data: Any) -> "Cast":
        if isinstance(data, Mapping):
            data = data.get("characters")
        if not isinstance(data, (list, tuple)):
            raise SchemaError("a cast must be a list of characters or {'characters': [...]}")

        characters = tuple(
            Character.from_dict(item, where=f"cast[{index}]") for index, item in enumerate(data)
        )
        if not characters:
            raise SchemaError("a cast needs at least one character")

        ids = [character.id for character in characters]
        duplicates = sorted({character_id for character_id in ids if ids.count(character_id) > 1})
        if duplicates:
            raise SchemaError(f"duplicate character id(s): {', '.join(duplicates)}")

        known = set(ids)
        for character in characters:
            for relationship in character.relationships:
                if relationship.to not in known:
                    raise SchemaError(
                        f"character {character.id!r} has a relationship to unknown character "
                        f"{relationship.to!r}"
                    )
        return cls(characters=characters)

    def to_dict(self) -> dict[str, Any]:
        return {"characters": [character.to_dict() for character in self.characters]}


# --------------------------------------------------------------------------- public API


def character_from_dict(data: Mapping[str, Any], *, where: str = "character") -> Character:
    return Character.from_dict(data, where=where)


def cast_from_dict(data: Any) -> Cast:
    return Cast.from_dict(data)


def load_cast(path: Path | str) -> Cast:
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SchemaError(f"cast file {path} is unreadable or not valid JSON: {exc}") from exc
    return Cast.from_dict(raw)


def save_cast(cast: Cast, path: Path | str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cast.to_dict(), indent=2) + "\n", encoding="utf-8")
    return path


def merge_locked(previous: Character, candidate: Character) -> tuple[Character, tuple[str, ...]]:
    """Regenerate a character without touching the fields the user locked.

    Returns the merged character and the locked paths that the candidate tried to change.
    """
    if previous.id != candidate.id:
        raise SchemaError(
            f"regeneration cannot change a character's id ({previous.id!r} -> {candidate.id!r})"
        )

    merged = copy.deepcopy(candidate.to_dict())
    kept: list[str] = []
    for path in previous.locked:
        old = copy.deepcopy(_get_path(previous.to_dict(), path, where=f"character {previous.id!r}"))
        new = _get_path(merged, path, where=f"character {candidate.id!r}")
        if old != new:
            _set_path(merged, path, old)
            kept.append(path)
    merged["locked"] = list(previous.locked)

    return Character.from_dict(merged, where=f"character {previous.id!r}"), tuple(kept)
