"""Pipeline state: config, projects, the stage registry, skills, runs and approvals.

M1 built `init_project`, `load_config` and `project_status`. M3 adds the generic stage
runner (`run_stage`), skill loading and `approve_gate`. Only stages with a skill file can
run; the rest keep reporting which milestone builds them.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from . import schemas
from .adapters import LLMAdapter, create_llm_adapter

GATE_STAGE_NUMBERS = {1: 9, 2: 11, 3: 17}
GATE_MILESTONES = {2: "M6", 3: "M8"}


class StoryError(RuntimeError):
    """A user-facing pipeline error: bad slug, missing project, unusable config."""


# --------------------------------------------------------------------------- stages


@dataclass(frozen=True)
class Stage:
    """One pipeline stage; `number` matches the skill number in BUILD_SPEC.md section 5."""

    number: int
    name: str
    title: str
    human_gate: int | None = None

    @property
    def dir_name(self) -> str:
        return f"{self.number:02d}-{self.name}"


STAGES: tuple[Stage, ...] = (
    Stage(1, "intake", "Intake"),
    Stage(2, "market_research", "Market research"),
    Stage(3, "reference_analysis", "Reference analysis"),
    Stage(4, "setting_research", "Setting research"),
    Stage(5, "premise_inversion", "Premise inversion"),
    Stage(6, "theme_premise", "Theme and premise"),
    Stage(7, "tone_ceiling", "Tone ceiling"),
    Stage(8, "character_creation", "Character creation"),
    Stage(9, "ensemble_check", "Ensemble check", human_gate=1),
    Stage(10, "series_bible", "Series bible"),
    Stage(11, "outline", "Outline", human_gate=2),
    Stage(12, "scene_card", "Scene cards"),
    Stage(13, "narrator_voice", "Narrator voice"),
    Stage(14, "chapter_writer", "Chapter writer"),
    Stage(15, "quality_gates", "Quality gates"),
    Stage(16, "opening_ending_polish", "Opening and ending polish"),
    Stage(17, "reader_test_pack", "Reader test pack", human_gate=3),
    Stage(18, "illustration_prompts", "Illustration prompts"),
    Stage(19, "packaging", "Packaging"),
)

PENDING = "pending"
DONE = "done"
NEEDS_APPROVAL = "needs approval"
FAILED = "failed"


def resolve_stage(reference: str | int) -> Stage:
    """Accept 8, '08', 'character_creation' or '08-character_creation'."""
    text = str(reference).strip()
    for stage in STAGES:
        if text in (stage.dir_name, stage.name, str(stage.number), f"{stage.number:02d}"):
            return stage
    raise StoryError(
        f"unknown stage {reference!r}: use a number (8), a name (outline) or a folder name (11-outline)"
    )


# --------------------------------------------------------------------------- skills

SKILLS_DIRNAME = "skills"
REQUIRED_SKILL_KEYS = (
    "name",
    "stage",
    "model_tier",
    "inputs",
    "outputs",
    "human_gate",
    "uses_search",
    "uses_randomizer",
)
REQUIRED_SKILL_SECTIONS = ("Purpose", "Inputs", "Steps", "Output format", "Do not", "Self-check")
MODEL_TIERS = ("planner", "writer", "checker", "none")


@dataclass(frozen=True)
class Skill:
    name: str
    stage: int
    model_tier: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    human_gate: bool
    uses_search: bool
    uses_randomizer: bool
    frontmatter: dict[str, Any]
    sections: dict[str, str]
    body: str
    path: Path


def _parse_sections(body: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    matches = list(re.finditer(r"^##\s+(.+?)\s*$", body, re.MULTILINE))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        sections[match.group(1).strip()] = body[match.end() : end].strip()
    return sections


def load_skill(root: Path | str, name: str) -> Skill:
    """Read one skills/<name>.md and enforce the frontmatter and sections of section 5."""
    path = Path(root) / SKILLS_DIRNAME / f"{name}.md"
    if not path.is_file():
        raise StoryError(f"skill not found: {path}")

    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        raise StoryError(f"skill {name} must start with YAML frontmatter between --- lines")
    try:
        end = next(index for index in range(1, len(lines)) if lines[index].strip() == "---")
    except StopIteration:
        raise StoryError(f"skill {name} has no closing --- for its frontmatter") from None

    frontmatter = yaml.safe_load("\n".join(lines[1:end])) or {}
    if not isinstance(frontmatter, dict):
        raise StoryError(f"skill {name} frontmatter must be a YAML mapping")
    missing = [key for key in REQUIRED_SKILL_KEYS if key not in frontmatter]
    if missing:
        raise StoryError(f"skill {name} is missing frontmatter: {', '.join(missing)}")

    stage = next((candidate for candidate in STAGES if candidate.name == name), None)
    if stage is None:
        raise StoryError(f"skill {name} does not match any stage in the registry")
    try:
        declared = int(frontmatter["stage"])
    except (TypeError, ValueError):
        raise StoryError(f"skill {name}: frontmatter 'stage' must be a number") from None
    if declared != stage.number:
        raise StoryError(
            f"skill {name} declares stage {declared} but the stage registry expects {stage.number}"
        )

    model_tier = str(frontmatter["model_tier"]).strip().lower()
    if model_tier not in MODEL_TIERS:
        raise StoryError(f"skill {name}: 'model_tier' must be one of {', '.join(MODEL_TIERS)}")

    body = "\n".join(lines[end + 1 :])
    sections = _parse_sections(body)
    missing_sections = [section for section in REQUIRED_SKILL_SECTIONS if not sections.get(section, "").strip()]
    if missing_sections:
        raise StoryError(f"skill {name} is missing sections: {', '.join(missing_sections)}")

    def _string_tuple(value: Any) -> tuple[str, ...]:
        if value is None:
            return ()
        if isinstance(value, str):
            return (value,)
        return tuple(str(item) for item in value)

    return Skill(
        name=name,
        stage=declared,
        model_tier=model_tier,
        inputs=_string_tuple(frontmatter["inputs"]),
        outputs=_string_tuple(frontmatter["outputs"]),
        human_gate=bool(frontmatter["human_gate"]),
        uses_search=bool(frontmatter["uses_search"]),
        uses_randomizer=bool(frontmatter["uses_randomizer"]),
        frontmatter=frontmatter,
        sections=sections,
        body=body,
        path=path,
    )


# --------------------------------------------------------------------------- config


@dataclass(frozen=True)
class Config:
    path: Path
    seed: int
    chaos_dial: int
    adapters: dict[str, Any]


def load_config(root: Path | str, path: Path | str | None = None) -> Config:
    """Load and validate config.yaml. Adapters and models are chosen here, not in code."""
    config_path = Path(path) if path is not None else Path(root) / "config.yaml"
    if not config_path.is_file():
        raise StoryError(f"config file not found: {config_path}")

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise StoryError(f"{config_path} must contain a YAML mapping")

    seed = raw.get("seed", 0)
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise StoryError(f"{config_path}: 'seed' must be an integer")

    chaos_dial = raw.get("chaos_dial", 1)
    if isinstance(chaos_dial, bool) or not isinstance(chaos_dial, int) or not 0 <= chaos_dial <= 3:
        raise StoryError(f"{config_path}: 'chaos_dial' must be an integer from 0 to 3")

    adapters = raw.get("adapters") or {}
    if not isinstance(adapters, dict):
        raise StoryError(f"{config_path}: 'adapters' must be a mapping")

    return Config(path=config_path, seed=seed, chaos_dial=chaos_dial, adapters=adapters)


def load_llm_adapter(config: Config, **overrides: Any) -> LLMAdapter:
    """Build the LLM adapter named in config.yaml, with optional per-run option overrides."""
    spec = config.adapters.get("llm")
    if not isinstance(spec, dict) or not spec.get("type"):
        raise StoryError("config needs adapters.llm.type (echo, manual or openai_compatible)")

    options = dict(spec.get("options") or {})
    options.update(overrides)
    return create_llm_adapter(str(spec["type"]), options)


# --------------------------------------------------------------------------- projects

SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")

CONCEPT_TEMPLATE = """\
# Concept brief. Fill this in, then let the pipeline stages run in order.
slug: {slug}
working_title: ""
genre: ""
tone_dial: 1          # 0 cozy .. 3 action-comedy
audience: ""
target_words: 60000
pen_name: ""
premise_seed: ""
must_include: []
must_avoid: []
"""

EMPTY_ROLLS = {"rolls": []}
EMPTY_LEDGER = {"chapter": 0, "entities": {}, "events": []}


def validate_slug(slug: str) -> str:
    if not slug or not SLUG_PATTERN.fullmatch(slug):
        raise StoryError(
            f"invalid project slug {slug!r}: use lowercase letters, digits and single hyphens (e.g. 'my-book')"
        )
    return slug


def projects_root(root: Path | str) -> Path:
    return Path(root) / "projects"


def project_path(root: Path | str, slug: str) -> Path:
    return projects_root(root) / validate_slug(slug)


@dataclass
class InitResult:
    project: Path
    created: list[Path] = field(default_factory=list)
    kept: list[Path] = field(default_factory=list)


def init_project(root: Path | str, slug: str, *, force: bool = False) -> InitResult:
    """Create the project tree. Idempotent: existing files are kept unless `force`."""
    slug = validate_slug(slug)
    project = project_path(root, slug)
    result = InitResult(project=project)

    for name in ("stages", "chapters", "reports"):
        directory = project / name
        if not directory.exists():
            directory.mkdir(parents=True)
            result.created.append(directory)

    project.mkdir(parents=True, exist_ok=True)

    files = {
        project / "concept.yaml": CONCEPT_TEMPLATE.format(slug=slug),
        project / "rolls.json": json.dumps(EMPTY_ROLLS, indent=2) + "\n",
        project / "ledger.json": json.dumps(EMPTY_LEDGER, indent=2) + "\n",
    }
    for path, content in files.items():
        if path.exists() and not force:
            result.kept.append(path)
            continue
        path.write_text(content, encoding="utf-8")
        result.created.append(path)

    return result


def list_projects(root: Path | str) -> list[str]:
    """Project slugs with a concept.yaml, sorted."""
    root_path = projects_root(root)
    if not root_path.is_dir():
        return []
    return sorted(
        path.name for path in root_path.iterdir() if path.is_dir() and (path / "concept.yaml").is_file()
    )


def read_concept(project: Path | str) -> dict[str, Any]:
    concept_path = Path(project) / "concept.yaml"
    if not concept_path.is_file():
        raise StoryError(f"missing concept file: {concept_path}")
    data = yaml.safe_load(concept_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise StoryError(f"{concept_path} must contain a YAML mapping")
    return data


# --------------------------------------------------------------------------- status


@dataclass
class StageState:
    stage: Stage
    status: str
    output: bool
    approved: bool
    error: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProjectStatus:
    slug: str
    path: Path
    title: str
    target_words: int
    stages: list[StageState]


def stage_state(project: Path | str, stage: Stage) -> StageState:
    """Read one stage directory: output.md plus optional meta.json."""
    directory = Path(project) / "stages" / stage.dir_name
    output_path = directory / "output.md"
    meta_path = directory / "meta.json"

    meta: dict[str, Any] = {}
    if meta_path.is_file():
        try:
            loaded = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            loaded = {}
        if isinstance(loaded, dict):
            meta = loaded

    has_output = output_path.is_file()
    approved = bool(meta.get("approved"))
    error = meta.get("error")
    error_text = str(error) if error else None

    if not has_output:
        status = PENDING
    elif meta.get("status") == "failed":
        status = FAILED
    elif stage.human_gate is not None and not approved:
        status = NEEDS_APPROVAL
    else:
        status = DONE

    return StageState(stage=stage, status=status, output=has_output, approved=approved, error=error_text, meta=meta)


def project_status(root: Path | str, slug: str) -> ProjectStatus:
    project = project_path(root, slug)
    if not project.is_dir():
        raise StoryError(f"project not found: {project} (run `story init {slug}`)")

    concept = read_concept(project)
    target_words = concept.get("target_words", 0)
    return ProjectStatus(
        slug=slug,
        path=project,
        title=str(concept.get("working_title") or ""),
        target_words=target_words if isinstance(target_words, int) else 0,
        stages=[stage_state(project, stage) for stage in STAGES],
    )


def format_status(status: ProjectStatus) -> str:
    """Plain-text stage table: stage, gate, status."""
    done = sum(1 for state in status.stages if state.status == DONE)
    lines = [f"Project: {status.slug}", f"Path:    {status.path}"]
    if status.title:
        lines.append(f"Title:   {status.title}")
    if status.target_words:
        lines.append(f"Target:  {status.target_words} words")
    lines.append(f"Stages:  {done}/{len(status.stages)} done")
    lines.append("")

    width = max((len(state.stage.dir_name) for state in status.stages), default=len("stage"))
    lines.append(f"{'stage':<{width}}  gate  status")
    for state in status.stages:
        gate = "-" if state.stage.human_gate is None else str(state.stage.human_gate)
        lines.append(f"{state.stage.dir_name:<{width}}  {gate:<4}  {state.status}")

    failed = [state for state in status.stages if state.status == FAILED]
    for state in failed:
        detail = f": {state.error}" if state.error else ""
        lines.append(f"\nfailed {state.stage.dir_name}{detail}")

    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- running


@dataclass
class RunResult:
    stage: Stage
    status: str
    output_path: Path
    meta_path: Path
    meta: dict[str, Any]
    notes: list[str] = field(default_factory=list)
    issues: list[Any] = field(default_factory=list)


@dataclass
class ApproveResult:
    gate: int
    stage: Stage
    status: str
    meta: dict[str, Any]
    warnings: list[str] = field(default_factory=list)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _stage_directory(project: Path, stage: Stage) -> Path:
    return project / "stages" / stage.dir_name


def _write_meta(directory: Path, meta: dict[str, Any]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "meta.json"
    path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return path


def _upstream_outputs(project: Path, stage: Stage) -> tuple[str, list[str]]:
    """Earlier stage outputs, plus a note for every one that does not exist yet."""
    texts: list[str] = []
    notes: list[str] = []
    for earlier in STAGES:
        if earlier.number >= stage.number:
            break
        path = _stage_directory(project, earlier) / "output.md"
        if path.is_file():
            texts.append(f"### {earlier.dir_name}\n\n{path.read_text(encoding='utf-8')}")
        else:
            notes.append(f"missing upstream output: {earlier.dir_name} (treated as empty)")
    return "\n\n".join(texts), notes


def _adapter_description(llm: LLMAdapter) -> dict[str, Any]:
    describe = getattr(llm, "describe", None)
    if callable(describe):
        return describe()
    return {"adapter": getattr(llm, "name", "unknown")}


def _merge_previous_locks(previous: schemas.Cast, candidate: schemas.Cast) -> tuple[schemas.Cast, list[str]]:
    """Keep locked fields from the cast already on disk when a stage is regenerated."""
    previous_by_id = previous.by_id
    characters: list[schemas.Character] = []
    notes: list[str] = []
    for character in candidate.characters:
        old = previous_by_id.get(character.id)
        if old is not None and old.locked:
            merged, kept = schemas.merge_locked(old, character)
            if kept:
                notes.append(f"kept locked fields on {character.id}: {', '.join(kept)}")
            characters.append(merged)
        else:
            characters.append(character)
    return schemas.cast_from_dict({"characters": [item.to_dict() for item in characters]}), notes


def run_stage(
    root: Path | str,
    slug: str,
    reference: str | int,
    *,
    force: bool = False,
    llm: LLMAdapter | None = None,
    config: Config | None = None,
) -> RunResult:
    """Run one stage that has a skill file, writing output.md, meta.json and its artifacts.

    Missing upstream stages are passed in as empty with a note. An approved stage is never
    overwritten without `force`.
    """
    from . import character_creation, ensemble, randomizer

    root = Path(root)
    stage = resolve_stage(reference)
    project = project_path(root, slug)
    if not project.is_dir():
        raise StoryError(f"project not found: {project} (run `story init {slug}`)")

    skill_path = root / SKILLS_DIRNAME / f"{stage.name}.md"
    if not skill_path.is_file():
        raise StoryError(
            f"stage {stage.dir_name} is not built yet (no skill at {skill_path}); "
            "see BUILD_SPEC.md section 10"
        )
    skill = load_skill(root, stage.name)

    existing = stage_state(project, stage)
    if existing.approved and not force:
        raise StoryError(
            f"stage {stage.dir_name} is approved; re-run with --force to overwrite it"
        )

    config = config or load_config(root)
    llm = llm if llm is not None else load_llm_adapter(config)
    concept = read_concept(project)
    upstream, notes = _upstream_outputs(project, stage)

    directory = _stage_directory(project, stage)
    directory.mkdir(parents=True, exist_ok=True)
    started = _utc_now()
    meta: dict[str, Any] = {
        "stage": stage.dir_name,
        "skill": skill.name,
        "model_tier": skill.model_tier,
        "human_gate": stage.human_gate,
        "approved": False,
        "started_at": started,
        "adapter": _adapter_description(llm),
        "notes": notes,
    }
    status = DONE
    issues: list[Any] = []
    output_text = ""

    if stage.name == "character_creation":
        rnd = randomizer.Randomizer(root, slug, config)
        roll_result = rnd.roll_stage(8)
        meta["rolls"] = [roll.to_dict() for roll in roll_result.rolls]

        draft = character_creation.draft_cast(
            roll_result.rolls, concept, seed=config.seed, names=rnd.names
        )
        prompt = character_creation.creation_prompt(
            skill, concept, roll_result.rolls, upstream, notes
        )
        reply = llm.complete(
            prompt, system=skill.sections["Purpose"], model_tier=skill.model_tier, max_tokens=4000
        )
        cast, model_note = character_creation.cast_from_reply(reply, draft)
        if model_note:
            notes.append(model_note)

        cast_path = directory / "cast.json"
        if cast_path.is_file():
            try:
                previous = schemas.load_cast(cast_path)
                cast, lock_notes = _merge_previous_locks(previous, cast)
                notes.extend(lock_notes)
            except schemas.SchemaError as exc:
                notes.append(f"previous cast ignored when merging locks: {exc}")

        schemas.save_cast(cast, cast_path)
        output_text = character_creation.render_cast(cast, concept, notes, reply)
        meta["files"] = ["output.md", "cast.json", "meta.json"]

    elif stage.name == "ensemble_check":
        cast_path = _stage_directory(project, STAGES[7]) / "cast.json"
        if not cast_path.is_file():
            raise StoryError(
                "run `story run character_creation` first: " f"no cast at {cast_path}"
            )
        try:
            cast = schemas.load_cast(cast_path)
        except schemas.SchemaError as exc:
            raise StoryError(f"invalid cast at {cast_path}: {exc}") from exc

        report = ensemble.check_ensemble(cast, llm)
        issues = list(report.issues)
        notes.extend(report.notes)
        output_text = ensemble.render_ensemble(cast, report, notes)
        meta["issues"] = [
            {"code": issue.code, "detail": issue.detail, "characters": list(issue.characters)}
            for issue in issues
        ]
        if issues:
            status = FAILED
            meta["error"] = "; ".join(f"{issue.code}: {issue.detail}" for issue in issues)
        meta["files"] = ["output.md", "meta.json"]

    else:
        prompt = (
            f"{skill.body}\n\n## This project\n\n"
            f"```yaml\n{yaml.safe_dump(dict(concept), sort_keys=False)}```\n\n"
            f"Earlier stage outputs:\n{upstream or '(none yet)'}\n"
        )
        output_text = llm.complete(
            prompt, system=skill.sections["Purpose"], model_tier=skill.model_tier, max_tokens=4000
        )
        meta["files"] = ["output.md", "meta.json"]

    output_path = directory / "output.md"
    output_path.write_text(output_text.rstrip() + "\n", encoding="utf-8")

    meta["status"] = status
    meta["finished_at"] = _utc_now()
    meta["notes"] = notes
    meta_path = _write_meta(directory, meta)

    state = stage_state(project, stage)
    return RunResult(
        stage=stage,
        status=state.status,
        output_path=output_path,
        meta_path=meta_path,
        meta=meta,
        notes=notes,
        issues=issues,
    )


def approve_gate(
    root: Path | str,
    slug: str,
    gate: str | int,
    *,
    force: bool = False,
) -> ApproveResult:
    """Pass a human gate. Gate 1 is the cast gate after stage 9."""
    try:
        number = int(str(gate).strip())
    except ValueError:
        raise StoryError(f"unknown gate {gate!r}: use 1, 2 or 3") from None
    if number not in GATE_STAGE_NUMBERS:
        raise StoryError(f"unknown gate {gate!r}: use 1, 2 or 3")

    project = project_path(root, slug)
    if not project.is_dir():
        raise StoryError(f"project not found: {project} (run `story init {slug}`)")

    stage = next(candidate for candidate in STAGES if candidate.number == GATE_STAGE_NUMBERS[number])
    if stage.number > 9:
        raise StoryError(
            f"gate {number} waits on stage {stage.dir_name} ({GATE_MILESTONES[number]}); not built yet"
        )

    state = stage_state(project, stage)
    if not state.output:
        raise StoryError(
            f"gate {number} has nothing to approve: run `story run {stage.name}` first"
        )

    warnings: list[str] = []
    meta = dict(state.meta)
    if state.status == FAILED:
        if not force:
            raise StoryError(
                f"stage {stage.dir_name} failed ({state.error or 'checks flagged the cast'}); "
                "fix it and re-run, or approve with --force"
            )
        meta["status"] = DONE
        meta["approved_with_force"] = True
        warnings.append(f"approved {stage.dir_name} even though its checks failed")

    meta["approved"] = True
    meta["approved_at"] = _utc_now()
    _write_meta(_stage_directory(project, stage), meta)

    new_state = stage_state(project, stage)
    return ApproveResult(
        gate=number, stage=stage, status=new_state.status, meta=meta, warnings=warnings
    )
