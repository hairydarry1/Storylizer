"""Series bible rules (`rules.json`) and the story ledger (`ledger.json`).

Stage 10 writes both: `build_rules` derives the machine-readable rules from the concept and
the cast, `initial_ledger` seeds the state from `cast.json`, and `render_bible` writes the
human-readable bible.

`validate_delta` is the state gate from BUILD_SPEC.md section 7. A chapter's delta is a list
of operations and every operation has to be earned: an item needs a recorded event or a
craftable recipe, a level-up needs the XP threshold, a skill needs its prerequisites, a move
needs an edge in the location graph, and an entity has to exist. `apply_delta` only returns
state for a delta that passed, and it records the delta id, so replaying a delta is rejected.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

SYSTEM_TYPES = ("none", "litrpg", "magic", "other")
OPS = ("add_item", "remove_item", "xp_gain", "level_up", "skill_unlock", "move", "event")

START_LEVEL = 5

#: keyword -> system type. Checked in order, so "progression fantasy" is litrpg, not magic.
SYSTEM_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "litrpg",
        (
            "litrpg",
            "gamelit",
            "game-lit",
            "progression fantasy",
            "cultivation",
            "isekai",
            "system apocalypse",
            "level up",
            "level-up",
            "levelling",
            "leveling",
            "stat sheet",
        ),
    ),
    (
        "magic",
        ("fantasy", "magic", "witch", "wizard", "arcane", "fae", "sorcery", "mythic"),
    ),
    (
        "other",
        (
            "science fiction",
            "sci-fi",
            "scifi",
            "cyberpunk",
            "steampunk",
            "space opera",
            "post-apocalyptic",
            "dystopian",
            "superhero",
            "time travel",
        ),
    ),
)

#: A starter prop set and location graph; the skill tells the user to edit rules.json.
STARTER_ITEMS: dict[str, dict[str, Any]] = {
    "ledger": {"name": "the ledger", "sources": []},
    "wax-seal": {"name": "a wax seal", "sources": []},
    "sealed-ledger": {"name": "the sealed ledger", "sources": ["recipe:seal-the-ledger"]},
}

STARTER_RECIPES: tuple[dict[str, Any], ...] = (
    {
        "id": "seal-the-ledger",
        "produces": "sealed-ledger",
        "ingredients": {"ledger": 1, "wax-seal": 1},
        "requires_skill": None,
        "minutes": 30,
    },
)

STARTER_LOCATIONS: dict[str, dict[str, Any]] = {
    "record-office": {
        "name": "The record office",
        "exits": {"market": {"minutes": 10}, "council-hall": {"minutes": 5}},
    },
    "market": {
        "name": "The market",
        "exits": {"record-office": {"minutes": 10}, "river-dock": {"minutes": 15}},
    },
    "river-dock": {
        "name": "The river dock",
        "exits": {"market": {"minutes": 15}, "council-hall": {"minutes": 20}},
    },
    "council-hall": {
        "name": "The council hall",
        "exits": {"record-office": {"minutes": 5}, "river-dock": {"minutes": 20}},
    },
}


class LedgerError(ValueError):
    """A ledger or delta the pipeline cannot use."""


class RulesError(ValueError):
    """A rules.json the ledger checks cannot run against."""


# --------------------------------------------------------------------------- small helpers


def _as_int(value: Any, default: int | None = None) -> int | None:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.fullmatch(r"-?\d+", value.strip()):
        return int(value.strip())
    return default


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(text).casefold()).strip("-")[:40].strip("-")
    return slug or "talent"


def _string_list(value: Any, *, where: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, (list, tuple)):
        raise RulesError(f"{where}: expected a list of strings")
    return [str(item).strip() for item in value if str(item).strip()]


# --------------------------------------------------------------------------- rules


def validate_rules(rules: Any) -> dict[str, Any]:
    """Normalise rules.json, rejecting anything the ledger checks cannot reason about."""
    if not isinstance(rules, Mapping):
        raise RulesError("rules.json must contain a JSON object")

    system = str(rules.get("system_type") or "").strip().casefold()
    if system not in SYSTEM_TYPES:
        raise RulesError(
            f"rules.json: 'system_type' must be one of {', '.join(SYSTEM_TYPES)} "
            f"(got {rules.get('system_type')!r})"
        )

    xp_raw = rules.get("xp") or {}
    if not isinstance(xp_raw, Mapping):
        raise RulesError("rules.json: 'xp' must be an object")

    thresholds_raw = xp_raw.get("thresholds") or {}
    if not isinstance(thresholds_raw, Mapping):
        raise RulesError("rules.json: 'xp.thresholds' must map level -> XP")
    thresholds: dict[int, int] = {}
    for key, value in thresholds_raw.items():
        level = _as_int(key)
        need = _as_int(value)
        if level is None or need is None or level < 1 or need < 0:
            raise RulesError(
                f"rules.json: xp.thresholds entry {key!r}: {value!r} is not a level -> XP number"
            )
        if level in thresholds:
            raise RulesError(f"rules.json: xp.thresholds lists level {level} twice")
        thresholds[level] = need

    if system != "none" and not thresholds:
        raise RulesError(
            "rules.json: a story with a stat system needs at least one level threshold "
            "(use system_type: none when the story has no stats)"
        )

    previous: int | None = None
    for level in sorted(thresholds):
        if previous is not None and thresholds[level] <= previous:
            raise RulesError(f"rules.json: xp.thresholds must increase with level (level {level})")
        previous = thresholds[level]

    max_level = _as_int(xp_raw.get("max_level"), max(thresholds) if thresholds else 0)
    if max_level is None or max_level < 0:
        raise RulesError("rules.json: 'xp.max_level' must be a number from 0 up")
    if thresholds and max_level < max(thresholds):
        raise RulesError("rules.json: 'xp.max_level' is below the highest threshold")

    skills_raw = rules.get("skills") or {}
    if not isinstance(skills_raw, Mapping):
        raise RulesError("rules.json: 'skills' must be an object")
    skills: dict[str, dict[str, Any]] = {}
    for skill_id, node in skills_raw.items():
        if not isinstance(node, Mapping):
            raise RulesError(f"rules.json: skill {skill_id!r} must be an object")
        requires = _string_list(node.get("requires"), where=f"rules.json: skill {skill_id!r}.requires")
        for requirement in requires:
            if requirement not in skills_raw:
                raise RulesError(
                    f"rules.json: skill {skill_id!r} requires unknown skill {requirement!r}"
                )
        skills[str(skill_id)] = {
            "name": str(node.get("name") or skill_id),
            "unlocks_at_level": _as_int(node.get("unlocks_at_level"), 1) or 1,
            "requires": requires,
            "requires_items": _string_list(
                node.get("requires_items"), where=f"rules.json: skill {skill_id!r}.requires_items"
            ),
            "note": str(node.get("note") or ""),
        }

    items_raw = rules.get("items") or {}
    if not isinstance(items_raw, Mapping):
        raise RulesError("rules.json: 'items' must be an object")
    items: dict[str, dict[str, Any]] = {}
    for item_id, node in items_raw.items():
        if not isinstance(node, Mapping):
            raise RulesError(f"rules.json: item {item_id!r} must be an object")
        items[str(item_id)] = {
            "name": str(node.get("name") or item_id),
            "sources": _string_list(node.get("sources"), where=f"rules.json: item {item_id!r}.sources"),
        }

    recipes_raw = rules.get("recipes") or []
    if not isinstance(recipes_raw, (list, tuple)):
        raise RulesError("rules.json: 'recipes' must be a list")
    recipes: list[dict[str, Any]] = []
    seen_recipes: set[str] = set()
    for entry in recipes_raw:
        if not isinstance(entry, Mapping):
            raise RulesError("rules.json: every recipe must be an object")
        recipe_id = str(entry.get("id") or "").strip()
        produces = str(entry.get("produces") or "").strip()
        if not recipe_id or not produces:
            raise RulesError("rules.json: every recipe needs 'id' and 'produces'")
        if recipe_id in seen_recipes:
            raise RulesError(f"rules.json: recipe {recipe_id!r} is listed twice")
        seen_recipes.add(recipe_id)
        if produces not in items:
            raise RulesError(f"rules.json: recipe {recipe_id!r} produces unknown item {produces!r}")

        ingredients_raw = entry.get("ingredients") or {}
        if not isinstance(ingredients_raw, Mapping):
            raise RulesError(f"rules.json: recipe {recipe_id!r}.ingredients must be an object")
        ingredients: dict[str, int] = {}
        for ingredient, count in ingredients_raw.items():
            amount = _as_int(count)
            if amount is None or amount < 1:
                raise RulesError(
                    f"rules.json: recipe {recipe_id!r} needs a positive count for {ingredient!r}"
                )
            if str(ingredient) not in items:
                raise RulesError(
                    f"rules.json: recipe {recipe_id!r} uses unknown item {ingredient!r}"
                )
            ingredients[str(ingredient)] = amount

        requires_skill = entry.get("requires_skill")
        requires_skill = str(requires_skill).strip() if requires_skill else None
        if requires_skill and requires_skill not in skills:
            raise RulesError(
                f"rules.json: recipe {recipe_id!r} needs unknown skill {requires_skill!r}"
            )
        recipes.append(
            {
                "id": recipe_id,
                "produces": produces,
                "ingredients": ingredients,
                "requires_skill": requires_skill,
                "minutes": max(0, _as_int(entry.get("minutes"), 0) or 0),
            }
        )

    locations_raw = rules.get("locations") or {}
    if not isinstance(locations_raw, Mapping):
        raise RulesError("rules.json: 'locations' must be an object")
    locations: dict[str, dict[str, Any]] = {}
    for location_id, node in locations_raw.items():
        if not isinstance(node, Mapping):
            raise RulesError(f"rules.json: location {location_id!r} must be an object")
        exits_raw = node.get("exits") or {}
        if not isinstance(exits_raw, Mapping):
            raise RulesError(f"rules.json: location {location_id!r}.exits must be an object")
        exits: dict[str, dict[str, int]] = {}
        for target, exit_node in exits_raw.items():
            if isinstance(exit_node, Mapping):
                minutes = _as_int(exit_node.get("minutes"), 0)
            else:
                minutes = _as_int(exit_node, 0)
            exits[str(target)] = {"minutes": max(0, minutes or 0)}
        locations[str(location_id)] = {
            "name": str(node.get("name") or location_id),
            "exits": exits,
        }

    for location_id, node in locations.items():
        for target in node["exits"]:
            if target not in locations:
                raise RulesError(
                    f"rules.json: location {location_id!r} exits to unknown location {target!r}"
                )

    start = str(rules.get("start_location") or "").strip()
    if not start and locations:
        start = next(iter(locations))
    if start and locations and start not in locations:
        raise RulesError(f"rules.json: 'start_location' {start!r} is not in the location graph")

    return {
        "system_type": system,
        "xp": {
            "curve": str(xp_raw.get("curve") or "table"),
            "per_level": max(0, _as_int(xp_raw.get("per_level"), 0) or 0),
            "max_level": max_level,
            "thresholds": thresholds,
        },
        "skills": skills,
        "items": items,
        "recipes": recipes,
        "locations": locations,
        "start_location": start,
        "notes": _string_list(rules.get("notes"), where="rules.json: notes"),
    }


def load_rules(path: Path | str) -> dict[str, Any]:
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RulesError(f"rules file {path} is unreadable: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RulesError(f"rules file {path} is not valid JSON: {exc}") from exc
    return validate_rules(raw)


def save_rules(rules: Any, path: Path | str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(validate_rules(rules), indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    return path


def xp_for_level(level: int, rules: Mapping[str, Any]) -> int | None:
    return rules["xp"]["thresholds"].get(level)


def level_for_xp(xp: int, rules: Mapping[str, Any]) -> int:
    thresholds = rules["xp"]["thresholds"]
    if not thresholds:
        return 0
    level = min(thresholds)
    for candidate, need in sorted(thresholds.items()):
        if xp >= need:
            level = candidate
    return level


# --------------------------------------------------------------------------- ledger


def normalise_ledger(ledger: Any) -> dict[str, Any]:
    """A ledger with every entity field present, so checks never guess at a shape."""
    if not isinstance(ledger, Mapping):
        raise LedgerError("a ledger must be a JSON object")

    entities_raw = ledger.get("entities") or {}
    if not isinstance(entities_raw, Mapping):
        raise LedgerError("ledger: 'entities' must be an object")
    entities: dict[str, dict[str, Any]] = {}
    for entity_id, node in entities_raw.items():
        if not isinstance(node, Mapping):
            raise LedgerError(f"ledger: entity {entity_id!r} must be an object")
        inventory = node.get("inventory") or []
        if not isinstance(inventory, (list, tuple)):
            raise LedgerError(f"ledger: entity {entity_id!r} inventory must be a list")
        skills = node.get("skills") or {}
        if not isinstance(skills, Mapping):
            raise LedgerError(f"ledger: entity {entity_id!r} skills must be an object")
        entities[str(entity_id)] = {
            "level": max(0, _as_int(node.get("level"), 0) or 0),
            "xp": max(0, _as_int(node.get("xp"), 0) or 0),
            "skills": {str(key): max(1, _as_int(value, 1) or 1) for key, value in skills.items()},
            "inventory": [str(item) for item in inventory],
            "location": str(node.get("location") or ""),
        }

    events_raw = ledger.get("events") or []
    if not isinstance(events_raw, (list, tuple)):
        raise LedgerError("ledger: 'events' must be a list")
    events: list[dict[str, Any]] = []
    for entry in events_raw:
        if not isinstance(entry, Mapping) or not str(entry.get("id") or "").strip():
            raise LedgerError("ledger: every event needs an 'id'")
        events.append(
            {
                "id": str(entry["id"]).strip(),
                "chapter": max(0, _as_int(entry.get("chapter"), 0) or 0),
                "summary": str(entry.get("summary") or ""),
            }
        )

    applied = ledger.get("applied_deltas") or []
    if not isinstance(applied, (list, tuple)):
        raise LedgerError("ledger: 'applied_deltas' must be a list")

    return {
        "chapter": max(0, _as_int(ledger.get("chapter"), 0) or 0),
        "entities": entities,
        "events": events,
        "applied_deltas": [str(value) for value in applied],
    }


def load_ledger(path: Path | str) -> dict[str, Any]:
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise LedgerError(f"ledger file {path} is unreadable: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise LedgerError(f"ledger file {path} is not valid JSON: {exc}") from exc
    return normalise_ledger(raw)


def save_ledger(ledger: Any, path: Path | str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(normalise_ledger(ledger), indent=2) + "\n", encoding="utf-8"
    )
    return path


def initial_ledger(cast: Any, rules: Any) -> dict[str, Any]:
    """Seed ledger.json from cast.json: one entity per character, at the start location."""
    rules = validate_rules(rules)
    level = 0 if rules["system_type"] == "none" else min(rules["xp"]["thresholds"] or {1: 0})
    entities = {
        character.id: {
            "level": level,
            "xp": 0,
            "skills": {},
            "inventory": [],
            "location": rules["start_location"],
        }
        for character in cast.characters
    }
    return normalise_ledger(
        {"chapter": 0, "entities": entities, "events": [], "applied_deltas": []}
    )


def delta_id(delta: Mapping[str, Any]) -> str:
    """The explicit delta id, or a stable hash of chapter + ops."""
    explicit = str(delta.get("id") or "").strip()
    if explicit:
        return explicit
    payload = json.dumps(
        [delta.get("chapter"), delta.get("ops")],
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return "auto-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


@dataclass
class ValidationReport:
    delta_id: str = ""
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "delta": self.delta_id,
            "ok": self.ok,
            "errors": list(self.errors),
            "notes": list(self.notes),
        }


def _entity(
    ledger: Mapping[str, Any], op: Mapping[str, Any], report: ValidationReport, where: str
) -> tuple[dict[str, Any] | None, str]:
    entity_id = str(op.get("entity") or "").strip()
    if not entity_id:
        report.errors.append(f"{where}: missing 'entity'")
        return None, ""
    entity = ledger["entities"].get(entity_id)
    if entity is None:
        known = ", ".join(sorted(ledger["entities"])) or "(no entities)"
        report.errors.append(f"{where}: unknown entity {entity_id!r} (the ledger has {known})")
        return None, entity_id
    return entity, entity_id


def _craft(
    entity_id: str,
    entity: dict[str, Any],
    recipe: Mapping[str, Any],
    quantity: int,
    report: ValidationReport,
    where: str,
) -> None:
    inventory = entity["inventory"]
    missing: list[str] = []
    for ingredient, needed in recipe["ingredients"].items():
        have = inventory.count(ingredient)
        if have < needed * quantity:
            missing.append(f"{ingredient} x{needed * quantity - have}")
    if missing:
        report.errors.append(
            f"{where}: recipe {recipe['id']!r} needs {', '.join(missing)} and {entity_id} has none"
        )
        return
    requires_skill = recipe.get("requires_skill")
    if requires_skill and requires_skill not in entity["skills"]:
        report.errors.append(
            f"{where}: recipe {recipe['id']!r} needs the skill {requires_skill!r}"
        )
        return

    for ingredient, needed in recipe["ingredients"].items():
        for _ in range(needed * quantity):
            inventory.remove(ingredient)
    inventory.extend([recipe["produces"]] * quantity)
    report.notes.append(
        f"{recipe['produces']} x{quantity} crafted with {recipe['id']!r} ({recipe['minutes']} minutes)"
    )


def _apply_op(
    ledger: dict[str, Any],
    rules: Mapping[str, Any],
    op: Mapping[str, Any],
    report: ValidationReport,
    where: str,
    chapter: int,
    system: str,
) -> None:
    kind = str(op.get("op") or "").strip().lower()

    if kind == "event":
        event_id = str(op.get("id") or op.get("event") or "").strip()
        if not event_id:
            report.errors.append(f"{where}: an event needs an 'id'")
            return
        if any(event["id"] == event_id for event in ledger["events"]):
            report.errors.append(f"{where}: event {event_id!r} is already recorded")
            return
        ledger["events"].append(
            {"id": event_id, "chapter": chapter, "summary": str(op.get("summary") or "").strip()}
        )
        return

    entity, entity_id = _entity(ledger, op, report, where)
    if entity is None:
        return

    if kind == "add_item":
        item = str(op.get("item") or "").strip()
        if not item:
            report.errors.append(f"{where}: add_item needs an 'item'")
            return
        quantity = _as_int(op.get("qty"), 1)
        if quantity is None or quantity < 1:
            report.errors.append(f"{where}: 'qty' must be a positive whole number")
            return

        recipes = {recipe["id"]: recipe for recipe in rules["recipes"]}
        recipe_id = str(op.get("recipe") or "").strip()
        if recipe_id:
            recipe = recipes.get(recipe_id)
            if recipe is None:
                report.errors.append(f"{where}: unknown recipe {recipe_id!r}")
                return
            if recipe["produces"] != item:
                report.errors.append(
                    f"{where}: recipe {recipe_id!r} makes {recipe['produces']!r}, not {item!r}"
                )
                return
            _craft(entity_id, entity, recipe, quantity, report, where)
            return

        source = str(op.get("source") or "").strip()
        candidates = [source] if source else list((rules["items"].get(item) or {}).get("sources") or [])
        if not candidates:
            report.errors.append(
                f"{where}: item {item!r} comes from nowhere: no recorded event and no "
                "crafting recipe produces it"
            )
            return

        failures: list[str] = []
        for candidate in candidates:
            if candidate.startswith("recipe:"):
                recipe = recipes.get(candidate.split(":", 1)[1].strip())
                if recipe is None:
                    failures.append(f"unknown recipe {candidate!r}")
                    continue
                if recipe["produces"] != item:
                    failures.append(f"recipe {recipe['id']!r} makes {recipe['produces']!r}")
                    continue
                before = len(report.errors)
                _craft(entity_id, entity, recipe, quantity, report, where)
                if len(report.errors) == before:
                    return
                failures.extend(report.errors[before:])
                del report.errors[before:]
            elif any(event["id"] == candidate for event in ledger["events"]):
                entity["inventory"].extend([item] * quantity)
                report.notes.append(
                    f"{item} x{quantity} to {entity_id} from the recorded event {candidate!r}"
                )
                return
            else:
                failures.append(f"no recorded event {candidate!r}")

        report.errors.append(
            f"{where}: item {item!r} comes from nowhere ({'; '.join(failures)})"
        )
        return

    if kind == "remove_item":
        item = str(op.get("item") or "").strip()
        if not item:
            report.errors.append(f"{where}: remove_item needs an 'item'")
            return
        quantity = _as_int(op.get("qty"), 1)
        if quantity is None or quantity < 1:
            report.errors.append(f"{where}: 'qty' must be a positive whole number")
            return
        inventory = entity["inventory"]
        have = inventory.count(item)
        if have < quantity:
            report.errors.append(
                f"{where}: {entity_id} has {have} {item!r}, cannot remove {quantity}"
            )
            return
        for _ in range(quantity):
            inventory.remove(item)
        return

    if kind == "xp_gain":
        amount = _as_int(op.get("amount"), None)
        if amount is None or amount < 1:
            report.errors.append(f"{where}: xp_gain needs a positive 'amount'")
            return
        entity["xp"] += amount
        if system == "none":
            report.notes.append(
                "xp_gain accepted without a rules check: this story has no stat system"
            )
        return

    if kind == "level_up":
        target = _as_int(op.get("level"), None)
        if target is None or target < 1:
            report.errors.append(f"{where}: level_up needs a level number")
            return
        current = entity["level"]
        if system == "none":
            if target <= current:
                report.errors.append(
                    f"{where}: level_up must raise {entity_id} above level {current}"
                )
                return
            entity["level"] = target
            report.notes.append(
                "level_up accepted without a rules check: this story has no stat system"
            )
            return
        if target != current + 1:
            report.errors.append(
                f"{where}: level_up from level {current} must go to {current + 1} "
                f"(one level at a time), not {target}"
            )
            return
        need = xp_for_level(target, rules)
        if need is None:
            report.errors.append(
                f"{where}: level {target} is above the rules' maximum level "
                f"({rules['xp']['max_level']})"
            )
            return
        if entity["xp"] < need:
            report.errors.append(
                f"{where}: level_up to level {target} needs {need} XP but "
                f"{entity_id} has {entity['xp']}"
            )
            return
        entity["level"] = target
        report.notes.append(f"{entity_id} is now level {target} ({entity['xp']} XP)")
        return

    if kind == "skill_unlock":
        skill = str(op.get("skill") or "").strip()
        if not skill:
            report.errors.append(f"{where}: skill_unlock needs a 'skill'")
            return
        if system == "none":
            entity["skills"].setdefault(skill, 1)
            report.notes.append(
                "skill_unlock accepted without a rules check: this story has no stat system"
            )
            return
        node = rules["skills"].get(skill)
        if node is None:
            known = ", ".join(sorted(rules["skills"])) or "(none)"
            report.errors.append(f"{where}: unknown skill {skill!r} (rules.json lists {known})")
            return
        if skill in entity["skills"]:
            report.errors.append(f"{where}: {entity_id} already knows {skill!r}")
            return
        if entity["level"] < node["unlocks_at_level"]:
            report.errors.append(
                f"{where}: skill {skill!r} unlocks at level {node['unlocks_at_level']} "
                f"but {entity_id} is level {entity['level']}"
            )
            return
        missing = [needed for needed in node["requires"] if needed not in entity["skills"]]
        if missing:
            report.errors.append(
                f"{where}: skill {skill!r} needs {', '.join(missing)} first"
            )
            return
        missing_items = [
            item for item in node["requires_items"] if item not in entity["inventory"]
        ]
        if missing_items:
            report.errors.append(
                f"{where}: skill {skill!r} needs {', '.join(missing_items)} in the inventory"
            )
            return
        entity["skills"][skill] = 1
        report.notes.append(f"{entity_id} unlocks {skill!r}")
        return

    if kind == "move":
        destination = str(op.get("to") or "").strip()
        if not destination:
            report.errors.append(f"{where}: move needs a 'to' location")
            return
        locations = rules["locations"]
        if not locations:
            entity["location"] = destination
            report.notes.append("rules define no location graph; move accepted unchecked")
            return
        if destination not in locations:
            known = ", ".join(sorted(locations)) or "(none)"
            report.errors.append(
                f"{where}: unknown location {destination!r} (rules.json lists {known})"
            )
            return
        current = entity["location"]
        if current not in locations:
            report.errors.append(f"{where}: {entity_id} is at unknown location {current!r}")
            return
        exits = locations[current]["exits"]
        if destination not in exits:
            known = ", ".join(sorted(exits)) or "(none)"
            report.errors.append(
                f"{where}: no path from {current!r} to {destination!r} (exits: {known})"
            )
            return
        entity["location"] = destination
        report.notes.append(
            f"{entity_id} moved to {destination!r} ({exits[destination]['minutes']} minutes)"
        )
        return

    report.errors.append(f"{where}: unknown operation {kind!r}")  # pragma: no cover - guarded


def _run(
    ledger_data: Any, rules: Any, delta: Any
) -> tuple[dict[str, Any], ValidationReport]:
    working = normalise_ledger(ledger_data)
    rules = validate_rules(rules)
    report = ValidationReport()

    if not isinstance(delta, Mapping):
        report.errors.append("a delta must be a JSON object with 'chapter' and 'ops'")
        return working, report

    report.delta_id = delta_id(delta)
    if report.delta_id in working["applied_deltas"]:
        report.errors.append(
            f"delta {report.delta_id!r} was already applied to this ledger "
            "(reapplying a delta is rejected)"
        )
        return working, report

    chapter = _as_int(delta.get("chapter"), None)
    if chapter is None or chapter < 0:
        report.errors.append("delta 'chapter' must be a whole number from 0 up")
        return working, report

    ops = delta.get("ops")
    if not isinstance(ops, (list, tuple)) or not ops:
        report.errors.append("delta 'ops' must be a non-empty list")
        return working, report

    system = rules["system_type"]
    for index, op in enumerate(ops):
        where = f"op {index + 1}"
        if not isinstance(op, Mapping):
            report.errors.append(f"{where}: every op must be an object")
            continue
        kind = str(op.get("op") or "").strip().lower()
        where = f"op {index + 1} ({kind or '?'})"
        if kind not in OPS:
            report.errors.append(
                f"{where}: unknown operation {kind!r} (use {', '.join(OPS)})"
            )
            continue
        _apply_op(working, rules, op, report, where, chapter, system)

    if report.ok:
        working["applied_deltas"].append(report.delta_id)
        if chapter > working["chapter"]:
            working["chapter"] = chapter

    return working, report


def validate_delta(ledger: Any, rules: Any, delta: Any) -> ValidationReport:
    """Check a delta against the ledger and the bible's rules without changing either."""
    return _run(ledger, rules, delta)[1]


def apply_delta(ledger: Any, rules: Any, delta: Any) -> dict[str, Any]:
    """Return the ledger after a delta that passed validation; raise on a rejected one."""
    working, report = _run(ledger, rules, delta)
    if not report.ok:
        raise LedgerError("delta rejected: " + "; ".join(report.errors))
    return working


# --------------------------------------------------------------------------- stage 10


def detect_system_type(concept: Mapping[str, Any]) -> str:
    text = " ".join(
        str(concept.get(key) or "") for key in ("genre", "premise_seed", "audience")
    ).casefold()
    for system, keywords in SYSTEM_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return system
    return "none"


def _thresholds(system: str) -> tuple[dict[int, int], str, int, int]:
    """(thresholds, curve, per_level, max_level) for the detected system."""
    if system == "none":
        return {}, "none", 0, 0
    per_level = 100
    thresholds = {level: per_level * level * (level - 1) // 2 for level in range(1, START_LEVEL + 1)}
    return thresholds, "triangular", per_level, START_LEVEL


def _talent_skills(cast: Any) -> dict[str, dict[str, Any]]:
    skills: dict[str, dict[str, Any]] = {}
    for character in cast.characters:
        talent = str(character.talent or "").strip()
        if not talent:
            continue
        skill_id = _slug(talent)
        if skill_id in skills:
            continue
        skills[skill_id] = {
            "name": talent,
            "unlocks_at_level": 2,
            "requires": [],
            "requires_items": [],
            "note": f"{character.name}'s rolled talent",
        }
        skills[f"{skill_id}-mastery"] = {
            "name": f"{talent}, mastered",
            "unlocks_at_level": 3,
            "requires": [skill_id],
            "requires_items": [],
            "note": f"second tier of {character.name}'s talent",
        }
    return skills


def build_rules(
    concept: Mapping[str, Any], cast: Any, *, notes: list[str] | None = None
) -> dict[str, Any]:
    """Deterministic rules.json: system, XP, skills, props, recipes and the location graph."""
    system = detect_system_type(concept)
    thresholds, curve, per_level, max_level = _thresholds(system)
    if notes is not None and system == "none":
        notes.append(
            "no stat system detected from the genre; rules.json records system_type: none"
        )

    rules = {
        "system_type": system,
        "xp": {
            "curve": curve,
            "per_level": per_level,
            "max_level": max_level,
            "thresholds": {str(level): need for level, need in thresholds.items()},
        },
        "skills": _talent_skills(cast) if system != "none" else {},
        "items": copy.deepcopy(STARTER_ITEMS),
        "recipes": copy.deepcopy(list(STARTER_RECIPES)),
        "locations": copy.deepcopy(STARTER_LOCATIONS),
        "start_location": "record-office",
        "notes": [
            "starter props, recipes and location graph: edit rules.json to fit the book",
        ],
    }
    return validate_rules(rules)


def render_bible(
    concept: Mapping[str, Any],
    cast: Any,
    rules: Any,
    *,
    slug: str,
    notes: Sequence[str] = (),
    model_text: str = "",
) -> str:
    """The human-readable bible.md. Everything the ledger checks depends on is printed here."""
    rules = validate_rules(rules)
    title = str(concept.get("working_title") or "").strip() or slug
    genre = str(concept.get("genre") or "").strip() or "(not set)"
    audience = str(concept.get("audience") or "").strip() or "(not set)"
    premise = str(concept.get("premise_seed") or "").strip() or "(not set)"
    must_avoid = [str(item).strip() for item in concept.get("must_avoid") or [] if str(item).strip()]

    lines = [f"# Series bible - {title}", "", "## World rules", ""]
    lines.append(f"- genre: {genre}")
    lines.append(f"- audience: {audience}")
    lines.append(f"- tone dial: {concept.get('tone_dial', 1)}")
    lines.append(f"- premise seed: {premise}")
    lines.append(
        "- setting detail lives in `stages/04-setting_research/output.md`; this bible fixes "
        "the rules the ledger enforces."
    )
    if must_avoid:
        lines.append(f"- off the table: {', '.join(must_avoid)}")

    lines += ["", "## System and progression", ""]
    if rules["system_type"] == "none":
        lines.append(
            "- This story has no stat system (`system_type: none`); XP, level and skill "
            "checks are skipped."
        )
    else:
        xp = rules["xp"]
        lines.append(f"- system: {rules['system_type']}")
        lines.append(f"- XP curve: {xp['curve']}, {xp['per_level']} XP per level step")
        lines.append("- level thresholds:")
        for level, need in sorted(xp["thresholds"].items()):
            lines.append(f"  - level {level}: {need} XP")
        if rules["skills"]:
            lines.append("- skills:")
            for skill_id, node in sorted(rules["skills"].items()):
                requires = ", ".join(node["requires"]) or "none"
                lines.append(
                    f"  - `{skill_id}` ({node['name']}): unlocks at level "
                    f"{node['unlocks_at_level']}; requires {requires}"
                )
        else:
            lines.append("- skills: none defined yet")

    lines.append("- item sources and recipes:")
    recipe_items = {recipe["produces"] for recipe in rules["recipes"]}
    for recipe in rules["recipes"]:
        ingredients = ", ".join(
            f"{item} x{count}" for item, count in recipe["ingredients"].items()
        )
        skill = f" (needs {recipe['requires_skill']})" if recipe["requires_skill"] else ""
        lines.append(
            f"  - `{recipe['produces']}` <- {ingredients} via `{recipe['id']}`"
            f", {recipe['minutes']} minutes{skill}"
        )
    for item_id in sorted(set(rules["items"]) - recipe_items):
        lines.append(f"  - `{item_id}`: no recipe; needs a recorded event as its source")

    lines += ["", "## Cast", ""]
    for character in cast.characters:
        core = character.emotional_core
        lines.append(f"### {character.name} (`{character.id}`, {character.role})")
        lines.append(f"- want: {core.want or '(none)'}")
        lines.append(f"- need: {core.need or '(none)'}")
        lines.append(f"- stakes: {core.stakes or '(none)'}")
        lines.append(f"- talent: {character.talent or '(none)'}")
        lines.append(f"- flaw: {character.flaw or '(none)'}")
        lines.append(f"- voice: {character.voice.rhythm}; {character.voice.vocabulary}")
        lines.append("")

    lines += ["## Locations and travel", ""]
    for location_id, node in rules["locations"].items():
        exits = ", ".join(
            f"`{target}` ({exit_['minutes']} min)" for target, exit_ in node["exits"].items()
        ) or "no exits"
        lines.append(f"- **{node['name']}** (`{location_id}`): {exits}")
    if rules["locations"]:
        lines.append(f"- start: `{rules['start_location']}`")

    lines += ["", "## Timeline", ""]
    protagonist = next(
        (character for character in cast.characters if character.role == "protagonist"),
        cast.characters[0],
    )
    if protagonist.emotional_core.arc_by_act:
        for index, beat in enumerate(protagonist.emotional_core.arc_by_act, start=1):
            label = beat if beat.casefold().startswith("act") else f"act {index}: {beat}"
            lines.append(f"- {label}")
    else:
        lines.append("- no act beats yet: the cast sheet has an empty `arc_by_act`")
    lines.append(
        f"- chapter 0: the story opens at `{rules['start_location']}`, with every character "
        "carrying an empty inventory"
    )

    all_notes = [str(note) for note in notes] + list(rules["notes"])
    if all_notes:
        lines += ["", "## Notes", ""]
        lines.extend(f"- {note}" for note in all_notes)

    if model_text.strip():
        lines += ["", "## Model notes", "", model_text.strip()]

    return "\n".join(lines).rstrip() + "\n"


def bible_prompt(
    skill: Any,
    concept: Mapping[str, Any],
    cast: Any,
    rules: Mapping[str, Any],
    upstream: str,
    notes: Sequence[str],
) -> str:
    sections = "\n\n".join(f"## {name}\n\n{text}" for name, text in skill.sections.items())
    cast_lines = "\n".join(
        f"- {character.id}: {character.name} ({character.role}), "
        f"wants {character.emotional_core.want or '(none)'}"
        for character in cast.characters
    )
    note_text = "\n".join(f"- {note}" for note in notes) or "- none"
    thresholds = ", ".join(
        f"{level}: {need}" for level, need in sorted(rules["xp"]["thresholds"].items())
    ) or "(none)"
    return (
        f"{sections}\n\n"
        "## This project\n\n"
        f"```yaml\n{yaml.safe_dump(dict(concept), sort_keys=False)}```\n\n"
        "## Cast\n"
        f"{cast_lines}\n\n"
        "## Rules already fixed by code\n"
        f"- system_type: {rules['system_type']}\n"
        f"- level thresholds: {thresholds}\n"
        f"- locations: {', '.join(rules['locations']) or '(none)'}\n\n"
        "Earlier stage outputs:\n"
        f"{upstream.strip() or '(none yet)'}\n\n"
        "Notes:\n"
        f"{note_text}\n\n"
        "Reply with prose about the world, the system and the timeline. The rules above are "
        "fixed and are not yours to change.\n"
    )


def model_bible_notes(llm: Any, skill: Any, prompt: str, notes: list[str]) -> str:
    """Model prose for the bible, or '' plus a note; the deterministic bible always stands."""
    try:
        reply = llm.complete(
            prompt,
            system=skill.sections["Purpose"],
            model_tier=skill.model_tier,
            max_tokens=2500,
        )
    except Exception as exc:  # the deterministic sections still stand
        notes.append(f"model call failed: {exc}")
        return ""
    text = (reply or "").strip()
    if not text or text.casefold() == "echo":
        notes.append("model returned no prose (echo adapter); deterministic sections stand")
        return ""
    return text


# --------------------------------------------------------------------------- rules merge

#: `story rules merge` only adds these four sections; everything else is not additive.
ADDITION_KEYS = ("items", "recipes", "locations", "skills")


@dataclass
class MergeResult:
    rules: dict[str, Any]
    added: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "added": list(self.added),
            "kept": list(self.kept),
            "errors": list(self.errors),
        }


def _addition_mapping(additions: Mapping[str, Any], key: str, errors: list[str]) -> Mapping[str, Any]:
    value = additions.get(key)
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        errors.append(f"rules additions: {key} must be an object")
        return {}
    return value


def merge_rules(rules: Any, additions: Any) -> MergeResult:
    """Validate additive entries and merge them without overwriting an existing one."""
    try:
        base = validate_rules(rules)
    except RulesError as exc:
        return MergeResult(rules={}, errors=[str(exc)])

    if not isinstance(additions, Mapping):
        return MergeResult(base, errors=["rules additions must be a JSON object"])

    unknown = sorted(str(key) for key in additions if key not in ADDITION_KEYS)
    if unknown:
        return MergeResult(
            base,
            errors=[
                f"rules additions may only contain {', '.join(ADDITION_KEYS)}; "
                f"found {', '.join(unknown)}"
            ],
        )

    merged = copy.deepcopy(base)
    added: list[str] = []
    kept: list[str] = []
    errors: list[str] = []

    for key in ("items", "skills", "locations"):
        for entry_id, node in _addition_mapping(additions, key, errors).items():
            entry_id = str(entry_id)
            if entry_id in merged[key]:
                kept.append(f"{key[:-1]} {entry_id}")
                continue
            merged[key][entry_id] = node
            added.append(f"{key[:-1]} {entry_id}")

    recipes = additions.get("recipes")
    if recipes is not None and not isinstance(recipes, (list, tuple)):
        errors.append("rules additions: recipes must be a list")
        recipes = None
    known_recipes = {recipe["id"] for recipe in merged["recipes"]}
    for entry in recipes or []:
        if not isinstance(entry, Mapping):
            errors.append("rules additions: every recipe must be an object")
            continue
        recipe_id = str(entry.get("id") or "").strip()
        if not recipe_id:
            errors.append("rules additions: a recipe has no id")
            continue
        if recipe_id in known_recipes:
            kept.append(f"recipe {recipe_id}")
            continue
        merged["recipes"].append(entry)
        known_recipes.add(recipe_id)
        added.append(f"recipe {recipe_id}")

    if errors:
        return MergeResult(base, errors=errors)

    try:
        validated = validate_rules(merged)
    except RulesError as exc:
        return MergeResult(base, errors=[f"rules additions do not validate: {exc}"])
    return MergeResult(rules=validated, added=added, kept=kept)


def format_merge_diff(result: MergeResult) -> str:
    """One line per change for the human to review before the file is written."""
    lines = [f"+ {entry}" for entry in result.added]
    lines.extend(f"= {entry} (kept existing)" for entry in result.kept)
    if not lines:
        lines.append("nothing to merge; every entry already exists")
    else:
        lines.append(f"{len(result.added)} added, {len(result.kept)} kept existing")
    return "\n".join(lines)


def render_ledger(ledger: Any, *, slug: str = "") -> str:
    """Plain-text state for `story ledger show`."""
    story = normalise_ledger(ledger)
    lines: list[str] = []
    if slug:
        lines.append(f"project: {slug}")
    lines.append(f"chapter: {story['chapter']}")
    lines.append(f"deltas:  {len(story['applied_deltas'])} applied")
    lines.append(f"events:  {len(story['events'])}")
    lines.append("")

    width = max((len(entity_id) for entity_id in story["entities"]), default=len("entity"))
    lines.append(f"{'entity':<{width}}  level  xp    location")
    for entity_id, node in story["entities"].items():
        lines.append(
            f"{entity_id:<{width}}  {node['level']:<5}  {node['xp']:<4}  {node['location']}"
        )

    for entity_id, node in story["entities"].items():
        if node["inventory"]:
            counts = Counter(node["inventory"])
            inventory = ", ".join(f"{item} x{count}" for item, count in sorted(counts.items()))
            lines.append(f"\n{entity_id} inventory: {inventory}")
        if node["skills"]:
            lines.append(f"{entity_id} skills: {', '.join(sorted(node['skills']))}")

    if story["events"]:
        lines.append("\nevents:")
        for event in story["events"]:
            summary = f": {event['summary']}" if event["summary"] else ""
            lines.append(f"  {event['id']} (chapter {event['chapter']}){summary}")

    return "\n".join(lines) + "\n"
