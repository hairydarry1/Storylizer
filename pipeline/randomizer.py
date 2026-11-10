"""Seeded randomizer (BUILD_SPEC.md section 6).

Design points:

* Determinism never relies on Python's `hash()`, which is salted per process. Every RNG
  seed is `int(sha256(f"{seed}|{stage}|{key}").hexdigest(), 16)`.
* Tables are JSON files under `tables/`. Any table may be a weighted entry list; the name
  tables instead carry a `phonetic` block and generate names from syllables.
* `projects/<slug>/rolls.json` is the audit log: one record per pick, newest last.
* `tables/used.json` remembers picks across projects so the pipeline does not hand the
  same quirk or name to two books.
* A checker-tier model may accept, adapt or reject each roll; rejected rolls are rerolled
  (at most three times).
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from . import runner
from .adapters.base import LLMAdapter

MAX_FIT_REROLLS = 3
MAX_NAME_TRIES = 200
MIN_NAME_LENGTH = 3
MAX_NAME_LENGTH = 14

#: Name generation refuses strings a reader would stumble over. Syllables can meet at a
#: seam, so without this the pools happily produce "Zeiustgreald" or "Tothouffcuys".
VOWEL_LETTERS = "aeiouy"
VOWEL_RUNS = frozenset({"ae", "ai", "au", "ea", "ee", "ei", "ia", "ie", "oa", "oo", "ou", "ue", "ui"})
MAX_CONSONANT_RUN = 2


def _pronounceable(name: str) -> bool:
    lowered = name.casefold()
    consonant_run = 0
    for char in lowered:
        if char.isalpha() and char not in VOWEL_LETTERS:
            consonant_run += 1
            if consonant_run > MAX_CONSONANT_RUN:
                return False
        else:
            consonant_run = 0
    for match in re.finditer(r"[aeiouy]+", lowered):
        run = match.group(0)
        if len(run) > 2 or (len(run) == 2 and run not in VOWEL_RUNS):
            return False
    return True

FIT_SYSTEM = (
    "You are the checker for a story randomizer. Judge each rolled constraint on whether a "
    "writing skill can use it for this book. Reply with JSON only."
)


class RandomizerError(runner.StoryError):
    """A roll, table or lock problem the user has to fix."""


class FitCheckError(RandomizerError):
    """The checker model did not return usable verdicts."""


# --------------------------------------------------------------------------- seeding


def seed_int(seed: int, stage: str, key: str, attempt: int = 0) -> int:
    """Derive an integer RNG seed from the run seed, stage and key.

    Attempt 0 is the first roll; later attempts (rerolls) get a different seed so they
    are both deterministic and different from the pick they replace.
    """
    material = f"{seed}|{stage}|{key}"
    if attempt:
        material = f"{material}|{attempt}"
    return int(hashlib.sha256(material.encode("utf-8")).hexdigest(), 16)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# --------------------------------------------------------------------------- stages


@dataclass(frozen=True)
class KeySpec:
    key: str
    table: str


@dataclass(frozen=True)
class StagePlan:
    essentials: tuple[KeySpec, ...]
    extras: tuple[KeySpec, ...]

    @property
    def all_specs(self) -> tuple[KeySpec, ...]:
        return self.essentials + self.extras


STAGE_PLANS: dict[int, StagePlan] = {
    8: StagePlan(
        essentials=(
            KeySpec("protagonist_given_name", "names_given"),
            KeySpec("protagonist_family_name", "names_family"),
            KeySpec("quirk", "quirks"),
            KeySpec("flaw", "flaws"),
            KeySpec("talent", "talents"),
        ),
        extras=(
            KeySpec("blind_spot", "blind_spots"),
            KeySpec("physical_mark", "physical_marks"),
            KeySpec("emotional_start", "emotional_starts"),
            KeySpec("speech_tic", "speech_tics"),
            KeySpec("complication", "complications"),
            KeySpec("setting_custom", "setting_customs"),
        ),
    ),
    11: StagePlan(
        essentials=(
            KeySpec("chapter_shape", "chapter_shapes"),
            KeySpec("complication", "complications"),
            KeySpec("imagery_domain", "imagery_domains"),
        ),
        extras=(
            KeySpec("weather", "weather"),
            KeySpec("setting_custom", "setting_customs"),
            KeySpec("smell_taste", "smells_tastes"),
            KeySpec("emotional_start", "emotional_starts"),
            KeySpec("ending_type", "ending_types"),
        ),
    ),
}


def resolve_stage(reference: str | int) -> runner.Stage:
    """Accept 8, '08', 'character_creation' or '08-character_creation'."""
    try:
        return runner.resolve_stage(reference)
    except runner.StoryError as exc:
        raise RandomizerError(str(exc)) from None


def _plan_for(stage: runner.Stage) -> StagePlan:
    try:
        return STAGE_PLANS[stage.number]
    except KeyError:
        usable = ", ".join(f"{number:02d}-{runner.STAGES[number - 1].name}" for number in sorted(STAGE_PLANS))
        raise RandomizerError(
            f"stage {stage.dir_name} does not use the randomizer; only {usable} do"
        ) from None


def _spec_for(stage: runner.Stage, key: str) -> KeySpec:
    for spec in _plan_for(stage).all_specs:
        if spec.key == key:
            return spec
    raise RandomizerError(f"stage {stage.dir_name} has no roll key {key!r}")


# --------------------------------------------------------------------------- tables


@dataclass(frozen=True)
class Entry:
    value: str
    weight: int = 1
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class Table:
    name: str
    entries: tuple[Entry, ...] = ()
    phonetic: Mapping[str, Any] | None = None
    path: Path | None = None


class Tables:
    """All JSON files in one tables/ directory, minus the used.json memory file."""

    def __init__(self, directory: Path | str) -> None:
        self.directory = Path(directory)
        if not self.directory.is_dir():
            raise RandomizerError(
                f"tables directory not found: {self.directory} (expected tables/*.json next to config.yaml)"
            )

        self._tables: dict[str, Table] = {}
        for path in sorted(self.directory.glob("*.json")):
            if path.name == "used.json":
                continue
            self._tables[self._read_name(path, path.stem)] = self._read_table(path)

    def names(self) -> list[str]:
        return sorted(self._tables)

    def table(self, name: str) -> Table:
        try:
            return self._tables[name]
        except KeyError:
            known = ", ".join(self.names()) or "none"
            raise RandomizerError(f"unknown table {name!r} (known tables: {known})") from None

    def banned_names(self) -> frozenset[str]:
        table = self._tables.get("banned_names")
        return frozenset(entry.value.casefold() for entry in table.entries) if table else frozenset()

    def banned_plots(self) -> tuple[str, ...]:
        table = self._tables.get("ai_default_plots")
        return tuple(entry.value.casefold() for entry in table.entries) if table else ()

    @staticmethod
    def _read_name(path: Path, fallback: str) -> str:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RandomizerError(f"table {path.name} is not valid JSON: {exc}") from exc
        if not isinstance(raw, dict):
            raise RandomizerError(f"table {path.name} must contain a JSON object")
        return str(raw.get("name") or fallback)

    @staticmethod
    def _read_table(path: Path) -> Table:
        raw = json.loads(path.read_text(encoding="utf-8"))
        name = str(raw.get("name") or path.stem)

        entries = []
        for item in raw.get("entries") or []:
            if not isinstance(item, dict) or not str(item.get("value", "")).strip():
                raise RandomizerError(f"table {path.name} has an entry without a value")
            weight = item.get("weight", 1)
            entries.append(
                Entry(
                    value=str(item["value"]),
                    weight=weight if isinstance(weight, int) and weight > 0 else 1,
                    tags=tuple(str(tag) for tag in item.get("tags") or ()),
                )
            )

        phonetic = raw.get("phonetic")
        if phonetic is not None and not isinstance(phonetic, dict):
            raise RandomizerError(f"table {path.name}: 'phonetic' must be an object")

        return Table(name=name, entries=tuple(entries), phonetic=phonetic, path=path)


class NameGenerator:
    """Phonetic names: syllable pools are mixed, so the output is not a fixed list."""

    def __init__(self, tables: Tables) -> None:
        self.tables = tables
        self.banned = tables.banned_names()

    def given(self, rng: random.Random, *, exclude: Iterable[str] = ()) -> str:
        return self._generate(rng, self._phonetic_spec("names_given"), exclude)

    def family(self, rng: random.Random, *, exclude: Iterable[str] = ()) -> str:
        return self._generate(rng, self._phonetic_spec("names_family"), exclude)

    def _phonetic_spec(self, table_name: str) -> Mapping[str, Any]:
        table = self.tables.table(table_name)
        if not table.phonetic:
            raise RandomizerError(f"table {table_name} has no 'phonetic' block to generate names from")
        for pool in ("onset", "nucleus"):
            if not table.phonetic.get(pool):
                raise RandomizerError(f"table {table_name}: 'phonetic.{pool}' is missing or empty")
        return table.phonetic

    def _generate(self, rng: random.Random, spec: Mapping[str, Any], exclude: Iterable[str]) -> str:
        excluded = {value.casefold() for value in exclude}
        for _ in range(MAX_NAME_TRIES):
            name = self._compose(rng, spec)
            key = name.casefold()
            if not MIN_NAME_LENGTH <= len(name) <= MAX_NAME_LENGTH:
                continue
            if key in self.banned or key in excluded:
                continue
            if not _pronounceable(name):
                continue
            return name
        raise RandomizerError(
            f"could not generate a name that avoids the banned list ({len(self.banned)} entries) "
            f"and the names already used; widen the phonetic pools in tables/names_*.json"
        )

    @staticmethod
    def _compose(rng: random.Random, spec: Mapping[str, Any]) -> str:
        patterns = spec.get("syllable_patterns") or ["{onset}{nucleus}"]
        low = int(spec.get("min_syllables", 1))
        high = max(low, int(spec.get("max_syllables", low)))
        syllables = [NameGenerator._fill(rng, str(rng.choice(patterns)), spec) for _ in range(rng.randint(low, high))]
        suffixes = spec.get("suffixes") or [""]
        name = "".join(syllables) + str(rng.choice(suffixes))
        return name[:1].upper() + name[1:]

    @staticmethod
    def _fill(rng: random.Random, pattern: str, spec: Mapping[str, Any]) -> str:
        for token, pool in (("{onset}", "onset"), ("{nucleus}", "nucleus"), ("{coda}", "coda")):
            while token in pattern:
                options = spec.get(pool)
                if not options:
                    pattern = pattern.replace(token, "")
                    break
                pattern = pattern.replace(token, str(rng.choice(list(options))), 1)
        return pattern


# --------------------------------------------------------------------------- rolls


@dataclass(frozen=True)
class Roll:
    stage: str
    key: str
    table: str
    value: str
    seed: int
    locked: bool
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Roll":
        try:
            return cls(
                stage=str(data["stage"]),
                key=str(data["key"]),
                table=str(data["table"]),
                value=str(data["value"]),
                seed=int(data["seed"]),
                locked=bool(data["locked"]),
                timestamp=str(data["timestamp"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RandomizerError(f"rolls.json has a malformed record: {data!r}") from exc


@dataclass
class FitDecision:
    key: str
    verdict: str
    reason: str = ""


@dataclass
class FitCheck:
    decisions: dict[str, FitDecision] = field(default_factory=dict)
    rerolled: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class RollResult:
    stage: runner.Stage
    rolls: list[Roll]
    created: list[Roll] = field(default_factory=list)
    fit: FitCheck | None = None


# --------------------------------------------------------------------------- fit check


def _extract_json(reply: str) -> Any:
    text = (reply or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise FitCheckError(f"fit check reply was not JSON: {reply[:120]!r}")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise FitCheckError(f"fit check reply was not usable JSON ({exc}): {reply[:120]!r}") from exc


def fit_rolls(llm: LLMAdapter, rolls: Sequence[Roll]) -> FitCheck:
    """Ask a checker-tier model about the rolls: accept, adapt or reject each one."""
    if not rolls:
        raise FitCheckError("fit check needs at least one roll")

    listing = "\n".join(f"{roll.key} | {roll.table} | {roll.value}" for roll in rolls)
    prompt = (
        "For each rolled constraint below decide whether it can be used as-is, used with small "
        "wording changes by the writing skill, or must be replaced.\n"
        "Reply with JSON only, in this shape:\n"
        '{"decisions": [{"key": "...", "verdict": "accept|adapt|reject", "reason": "one line"}]}\n\n'
        f"Stage: {rolls[0].stage}\n"
        "Rolls:\n"
        f"{listing}"
    )
    reply = llm.complete(prompt, system=FIT_SYSTEM, model_tier="checker", max_tokens=800)
    payload = _extract_json(reply)

    items = payload.get("decisions") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise FitCheckError("fit check reply has no 'decisions' list")

    decisions: dict[str, FitDecision] = {}
    for item in items:
        if not isinstance(item, dict) or not item.get("key"):
            raise FitCheckError("fit check reply has a decision without a key")
        key = str(item["key"]).strip()
        verdict = str(item.get("verdict") or "").strip().lower()
        if verdict not in {"accept", "adapt", "reject"}:
            raise FitCheckError(f"fit check gave an unknown verdict {verdict!r} for {key!r}")
        decisions[key] = FitDecision(key=key, verdict=verdict, reason=str(item.get("reason") or "").strip())

    for roll in rolls:
        decisions.setdefault(roll.key, FitDecision(key=roll.key, verdict="accept", reason="no verdict from the checker"))
    return FitCheck(decisions=decisions)


# --------------------------------------------------------------------------- randomizer


class Randomizer:
    def __init__(
        self,
        root: Path | str,
        slug: str,
        config: runner.Config | None = None,
        *,
        tables_dir: Path | str | None = None,
        used_path: Path | str | None = None,
        now=None,
    ) -> None:
        self.root = Path(root)
        self.slug = slug
        self.config = config or runner.load_config(self.root)
        self.project = runner.project_path(self.root, self.slug)
        if not self.project.is_dir():
            raise runner.StoryError(f"project not found: {self.project} (run `story init {slug}`)")

        self.rolls_path = self.project / "rolls.json"
        self.tables = Tables(tables_dir or self.root / "tables")
        self.used_path = Path(used_path) if used_path else self.tables.directory / "used.json"
        self.names = NameGenerator(self.tables)
        self._now = now or _utc_now
        self._records = self._load()

    # -- state -----------------------------------------------------------------

    def _load(self) -> list[Roll]:
        if not self.rolls_path.is_file():
            return []
        try:
            raw = json.loads(self.rolls_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RandomizerError(f"{self.rolls_path} is not valid JSON: {exc}") from exc

        records = raw.get("rolls") if isinstance(raw, dict) else raw
        if not isinstance(records, list):
            raise RandomizerError(f"{self.rolls_path} must contain a 'rolls' list")
        return [Roll.from_dict(item) for item in records]

    def _save(self) -> None:
        self.rolls_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"rolls": [record.to_dict() for record in self._records]}
        self.rolls_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def _used(self) -> dict[str, list[dict[str, Any]]]:
        if not self.used_path.is_file():
            return {}
        try:
            raw = json.loads(self.used_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        used = raw.get("used") if isinstance(raw, dict) else None
        if not isinstance(used, dict):
            return {}
        return {
            str(table): [record for record in records if isinstance(record, dict)]
            for table, records in used.items()
            if isinstance(records, list)
        }

    def _used_values(self, table: str) -> set[str]:
        return {str(record.get("value", "")).casefold() for record in self._used().get(table, [])}

    def _record_used(self, table: str, value: str, stage: runner.Stage) -> None:
        used = self._used()
        records = used.setdefault(table, [])
        if any(
            record.get("value") == value and record.get("project") == self.slug for record in records
        ):
            return
        records.append(
            {
                "value": value,
                "project": self.slug,
                "stage": stage.dir_name,
                "timestamp": self._now(),
            }
        )
        self.used_path.parent.mkdir(parents=True, exist_ok=True)
        self.used_path.write_text(json.dumps({"used": used}, indent=2) + "\n", encoding="utf-8")

    def current_rolls(self) -> list[Roll]:
        """Latest record per key, in the order the keys were first rolled."""
        latest: dict[str, Roll] = {}
        for record in self._records:
            latest[record.key] = record
        return list(latest.values())

    # -- rolling ---------------------------------------------------------------

    def _is_banned(self, value: str) -> bool:
        folded = value.casefold()
        if folded in self.tables.banned_names():
            return True
        return any(plot in folded for plot in self.tables.banned_plots())

    def _pick_entry(self, table: Table, rng: random.Random, exclude: set[str]) -> str:
        candidates = [entry for entry in table.entries if not self._is_banned(entry.value)]
        fresh = [entry for entry in candidates if entry.value.casefold() not in exclude]
        pool = fresh or candidates
        if not pool:
            raise RandomizerError(f"table {table.name!r} has no entries left after the banned and used checks")
        weights = [entry.weight for entry in pool]
        return rng.choices(pool, weights=weights, k=1)[0].value

    def _roll_spec(
        self,
        spec: KeySpec,
        stage: runner.Stage,
        *,
        attempt: int = 0,
        exclude: Iterable[str] = (),
    ) -> Roll:
        rng = random.Random(seed_int(self.config.seed, stage.dir_name, spec.key, attempt))
        table = self.tables.table(spec.table)

        excluded = set(exclude) | self._used_values(spec.table)
        if table.phonetic is not None:
            generator = self.names.given if spec.table == "names_given" else self.names.family
            value = generator(rng, exclude=excluded)
        else:
            value = self._pick_entry(table, rng, {item.casefold() for item in excluded})

        roll = Roll(
            stage=stage.dir_name,
            key=spec.key,
            table=spec.table,
            value=value,
            seed=seed_int(self.config.seed, stage.dir_name, spec.key, attempt),
            locked=False,
            timestamp=self._now(),
        )
        self._record_used(spec.table, value, stage)
        return roll

    def _specs_for(self, stage: runner.Stage, plan: StagePlan) -> list[KeySpec]:
        chaos = max(0, min(3, self.config.chaos_dial))
        if not chaos or not plan.extras:
            return list(plan.essentials)

        rng = random.Random(seed_int(self.config.seed, stage.dir_name, "__chaos__"))
        keys = [spec.key for spec in plan.extras]
        chosen = set(rng.sample(keys, k=min(chaos, len(keys))))
        return list(plan.essentials) + [spec for spec in plan.extras if spec.key in chosen]

    def roll_stage(
        self,
        stage_reference: str | int,
        *,
        llm: LLMAdapter | None = None,
        fit: bool = True,
    ) -> RollResult:
        stage = resolve_stage(stage_reference)
        plan = _plan_for(stage)

        latest = {(record.stage, record.key): record for record in self._records}
        rolls: list[Roll] = []
        created: list[Roll] = []
        for spec in self._specs_for(stage, plan):
            roll = latest.get((stage.dir_name, spec.key))
            if roll is None:
                roll = self._roll_spec(spec, stage)
                self._records.append(roll)
                created.append(roll)
            rolls.append(roll)

        if created:
            self._save()

        report = None
        if fit and llm is not None and rolls:
            rolls, report = self._apply_fit(stage, rolls, llm)

        return RollResult(stage=stage, rolls=rolls, created=created, fit=report)

    def _apply_fit(self, stage: runner.Stage, rolls: list[Roll], llm: LLMAdapter) -> tuple[list[Roll], FitCheck]:
        current = list(rolls)
        decisions: dict[str, FitDecision] = {}
        rerolled: list[str] = []
        notes: list[str] = []
        attempts = {roll.key: 0 for roll in current}
        pending = [roll.key for roll in current]

        while pending:
            by_key = {roll.key: roll for roll in current}
            report = fit_rolls(llm, [by_key[key] for key in pending])

            for key in list(pending):
                decision = report.decisions[key]
                decisions[key] = decision
                if decision.verdict in ("accept", "adapt"):
                    pending.remove(key)
                    continue
                if attempts[key] >= MAX_FIT_REROLLS:
                    notes.append(f"{key}: still rejected after {MAX_FIT_REROLLS} rerolls; kept the last value")
                    pending.remove(key)
                    continue

                attempts[key] += 1
                previous = by_key[key]
                logged = sum(1 for record in self._records if record.stage == stage.dir_name and record.key == key)
                replacement = self._roll_spec(
                    _spec_for(stage, key), stage, attempt=logged, exclude={previous.value}
                )
                self._records.append(replacement)
                self._save()
                current = [replacement if roll.key == key else roll for roll in current]
                if key not in rerolled:
                    rerolled.append(key)

        return current, FitCheck(decisions=decisions, rerolled=rerolled, notes=notes)

    # -- locks and rerolls -----------------------------------------------------

    def _records_for(self, key: str) -> list[Roll]:
        return [record for record in self._records if record.key == key]

    def _locked(self, key: str) -> bool:
        return any(record.locked for record in self._records_for(key))

    def lock(self, key: str) -> list[Roll]:
        records = self._records_for(key)
        if not records:
            raise RandomizerError(f"no roll for key {key!r}; run `story roll <stage>` first")

        self._records = [replace(record, locked=True) if record.key == key else record for record in self._records]
        self._save()
        return [record for record in self._records if record.key == key]

    def reroll(self, key: str) -> Roll:
        records = self._records_for(key)
        if not records:
            raise RandomizerError(f"no roll for key {key!r}; run `story roll <stage>` first")
        if self._locked(key):
            raise RandomizerError(f"key {key!r} is locked and will not change")

        previous = records[-1]
        stage = resolve_stage(previous.stage)
        replacement = self._roll_spec(
            _spec_for(stage, key), stage, attempt=len(records), exclude={previous.value}
        )
        self._records.append(replacement)
        self._save()
        return replacement
