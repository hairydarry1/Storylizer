"""`story` command line (see BUILD_SPEC.md section 9).

M1 built `init`/`status`, M2 the randomizer commands, M3 `run` for stages with a skill
file and `approve` for human gate 1, M5 the series bible and `ledger show|validate`. The
remaining commands name the milestone that will build them.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from . import ledger, randomizer, runner
from .adapters import AdapterError

#: command -> milestone that implements it
PLANNED_IN: dict[str, str] = {
    "check": "M7",
    "export": "M8",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="story",
        description="Turn a concept brief into a finished novel through staged, resumable runs.",
    )
    parser.add_argument(
        "--root",
        default=".",
        help="folder holding config.yaml and projects/ (default: the current folder)",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="path to config.yaml (default: <root>/config.yaml)",
    )

    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="create a project and a concept template")
    init.add_argument("slug", help="project slug, e.g. my-book")
    init.add_argument("--force", action="store_true", help="overwrite concept.yaml, rolls.json and ledger.json")

    status = commands.add_parser("status", help="stage table: done / needs approval / failed")
    status.add_argument("--project", "-p", default=None, help="project slug (default: the only project)")

    run = commands.add_parser("run", help="run one stage, or all stages until the next gate")
    run.add_argument(
        "stage",
        help="stage number, name, folder name (8, character_creation) or all",
    )
    run.add_argument("--force", action="store_true", help="allow re-running an approved stage")
    run.add_argument(
        "--skeleton",
        action="store_true",
        help="stages 11-12: use the deterministic skeleton instead of model JSON (tests and dry runs)",
    )
    run.add_argument(
        "--max-calls",
        type=int,
        default=None,
        help=(
            "cap the model calls this run may make; the per-day total is saved in the project "
            "(projects/<slug>/calls.json)"
        ),
    )
    run.add_argument("--project", "-p", default=None, help="project slug (default: the only project)")

    approve = commands.add_parser("approve", help="pass a human gate")
    approve.add_argument("gate", help="1 (concept + cast), 2 (outline) or 3 (final read)")
    approve.add_argument("--force", action="store_true", help="approve even if the stage's checks failed")
    approve.add_argument("--project", "-p", default=None, help="project slug (default: the only project)")

    ledger_parser = commands.add_parser(
        "ledger", help="show the story ledger or validate a chapter delta"
    )
    ledger_commands = ledger_parser.add_subparsers(dest="ledger_command", required=True)

    ledger_show = ledger_commands.add_parser(
        "show", help="entities, inventory, skills and recorded events"
    )
    ledger_show.add_argument(
        "--project", "-p", default=None, help="project slug (default: the only project)"
    )

    ledger_validate = ledger_commands.add_parser(
        "validate", help="check a delta file against ledger.json and rules.json"
    )
    ledger_validate.add_argument("delta", help="path to a delta JSON file")
    ledger_validate.add_argument(
        "--project", "-p", default=None, help="project slug (default: the only project)"
    )

    rules_parser = commands.add_parser(
        "rules", help="inspect or merge the series-bible rules"
    )
    rules_commands = rules_parser.add_subparsers(dest="rules_command", required=True)

    rules_merge = rules_commands.add_parser(
        "merge", help="merge additive rules and print the diff"
    )
    rules_merge.add_argument(
        "additions",
        nargs="?",
        default=None,
        help="additions JSON (default: the outline's rules_additions.json)",
    )
    rules_merge.add_argument(
        "--project", "-p", default=None, help="project slug (default: the only project)"
    )

    roll = commands.add_parser("roll", help="roll and log randomizer picks for a stage")
    roll.add_argument("stage", help="stage number, name or folder name (8, outline, 11-outline)")
    roll.add_argument("--project", "-p", default=None, help="project slug (default: the only project)")

    lock = commands.add_parser("lock", help="lock a rolled key so it never changes")
    lock.add_argument("key")
    lock.add_argument("--project", "-p", default=None, help="project slug (default: the only project)")

    reroll = commands.add_parser("reroll", help="reroll a key that is not locked")
    reroll.add_argument("key")
    reroll.add_argument("--project", "-p", default=None, help="project slug (default: the only project)")

    check = commands.add_parser("check", help="run the quality gates on one chapter")
    check.add_argument("chapter")

    commands.add_parser("export", help="build the EPUB and KDP_DISCLOSURE.md")

    return parser


def _cmd_init(root: Path, args: argparse.Namespace) -> int:
    result = runner.init_project(root, args.slug, force=args.force)
    print(f"project: {result.project}")

    if result.created:
        print("created:")
        for path in result.created:
            print(f"  {path}")
    if result.kept:
        print("kept (already existed):")
        for path in result.kept:
            print(f"  {path}")

    concept = result.project / "concept.yaml"
    print(f"\nnext: fill in {concept}, then run `story status`")
    return 0


def _resolve_slug(root: Path, requested: str | None) -> str:
    if requested:
        return requested

    projects = runner.list_projects(root)
    if not projects:
        raise runner.StoryError(f"no projects in {runner.projects_root(root)}; run `story init <slug>` first")
    if len(projects) > 1:
        raise runner.StoryError(f"several projects found ({', '.join(projects)}); pick one with --project")
    return projects[0]


def _cmd_status(root: Path, args: argparse.Namespace) -> int:
    status = runner.project_status(root, _resolve_slug(root, args.project))
    print(runner.format_status(status), end="")
    return 0


def _print_rolls(rolls) -> None:
    key_width = max(len(roll.key) for roll in rolls)
    table_width = max(len(roll.table) for roll in rolls)
    print(f"{'key':<{key_width}}  {'table':<{table_width}}  value")
    for roll in rolls:
        print(f"{roll.key:<{key_width}}  {roll.table:<{table_width}}  {roll.value}")


def _print_fit(fit) -> None:
    counts: dict[str, int] = {}
    for decision in fit.decisions.values():
        counts[decision.verdict] = counts.get(decision.verdict, 0) + 1
    summary = ", ".join(f"{count} {verdict}" for verdict, count in sorted(counts.items()))
    print(f"\nfit check: {summary}")
    for key, decision in fit.decisions.items():
        if decision.verdict != "accept" and decision.reason:
            print(f"  {key}: {decision.verdict} - {decision.reason}")
    for note in fit.notes:
        print(f"  note: {note}")


def _cmd_roll(root: Path, args: argparse.Namespace) -> int:
    config = runner.load_config(root, args.config)
    rnd = randomizer.Randomizer(root, _resolve_slug(root, args.project), config)

    warning = None
    try:
        result = rnd.roll_stage(args.stage, llm=runner.load_llm_adapter(config))
    except randomizer.FitCheckError as exc:
        # The rolls are already logged; a checker that cannot answer must not block the run.
        warning = str(exc)
        result = rnd.roll_stage(args.stage)

    print(f"stage: {result.stage.dir_name}")
    print(f"chaos: {config.chaos_dial} ({len(result.rolls)} constraints)")
    given = next((roll for roll in result.rolls if roll.key == "protagonist_given_name"), None)
    family = next((roll for roll in result.rolls if roll.key == "protagonist_family_name"), None)
    if given and family:
        print(f"name:  {given.value} {family.value}")
    print()
    _print_rolls(result.rolls)
    if result.fit is not None:
        _print_fit(result.fit)
    if warning:
        print(f"warning: fit check skipped: {warning}", file=sys.stderr)
    return 0


def _cmd_lock(root: Path, args: argparse.Namespace) -> int:
    config = runner.load_config(root, args.config)
    records = randomizer.Randomizer(root, _resolve_slug(root, args.project), config).lock(args.key)
    for record in records:
        print(f"locked: {record.key} ({record.stage}) = {record.value}")
    return 0


def _cmd_run_all(root: Path, args: argparse.Namespace) -> int:
    config = runner.load_config(root, args.config)
    result = runner.run_all(
        root,
        _resolve_slug(root, args.project),
        force=args.force,
        config=config,
        skeleton=args.skeleton,
        max_calls=args.max_calls,
    )

    for run in result.results:
        print(f"{run.stage.dir_name}: {run.status} -> {run.output_path}")
        calls = run.meta.get("calls") or {}
        if calls:
            print(f"  model calls: {calls.get('run', 0)} (today: {calls.get('today', 0)})")
        if run.status == runner.FAILED:
            print(f"  see {run.meta_path}", file=sys.stderr)
    if not result.results:
        print("nothing to run: done stages and the next gate are already recorded")

    if result.stopped_at is not None:
        print(f"stopped: {result.reason}")
        if result.stopped_at.human_gate is not None:
            print(f"next: story approve {result.stopped_at.human_gate}")

    if any(run.status == runner.FAILED for run in result.results):
        return 1
    return 0


def _cmd_run(root: Path, args: argparse.Namespace) -> int:
    if str(args.stage).strip().lower() == "all":
        return _cmd_run_all(root, args)

    config = runner.load_config(root, args.config)
    result = runner.run_stage(
        root,
        _resolve_slug(root, args.project),
        args.stage,
        force=args.force,
        config=config,
        skeleton=args.skeleton,
        max_calls=args.max_calls,
    )

    print(f"stage:  {result.stage.dir_name}")
    print(f"status: {result.status}")
    print(f"output: {result.output_path}")
    calls = result.meta.get("calls") or {}
    if calls:
        limit = calls.get("limit")
        print(
            f"model calls: {calls.get('run', 0)} (today: {calls.get('today', 0)},"
            f" limit: {limit if limit is not None else 'none'})"
        )
    for note in result.notes:
        print(f"note: {note}")
    for issue in result.issues:
        print(f"issue: {issue.code}: {issue.detail}")

    if result.status == runner.FAILED:
        detail = result.meta.get("error")
        if detail:
            print(f"reason: {detail}", file=sys.stderr)
        print(
            f"error: stage {result.stage.dir_name} failed; see {result.meta_path}",
            file=sys.stderr,
        )
        return 1
    return 0


def _cmd_approve(root: Path, args: argparse.Namespace) -> int:
    result = runner.approve_gate(
        root,
        _resolve_slug(root, args.project),
        args.gate,
        force=args.force,
    )
    for warning in result.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    print(f"approved: gate {result.gate} ({result.stage.dir_name})")
    print(f"status: {result.status}")
    return 0


def _cmd_reroll(root: Path, args: argparse.Namespace) -> int:
    config = runner.load_config(root, args.config)
    rnd = randomizer.Randomizer(root, _resolve_slug(root, args.project), config)
    before = next((roll.value for roll in rnd.current_rolls() if roll.key == args.key), None)

    rolled = rnd.reroll(args.key)

    print(f"rerolled: {rolled.key} ({rolled.stage})")
    print(f"  was: {before}")
    print(f"  now: {rolled.value}")
    return 0


def _cmd_ledger(root: Path, args: argparse.Namespace) -> int:
    from .gates import ledger_check

    project = runner.project_path(root, _resolve_slug(root, args.project))
    story, rules = ledger_check.load_story_state(project)

    if args.ledger_command == "show":
        print(ledger.render_ledger(story, slug=project.name), end="")
        return 0

    delta_path = Path(args.delta)
    if not delta_path.is_file():
        raise runner.StoryError(f"delta file not found: {delta_path}")
    try:
        delta = json.loads(delta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise runner.StoryError(f"{delta_path} is not valid JSON: {exc}") from exc

    result = ledger_check.check_delta(story, rules, delta)
    for note in result.notes:
        print(f"note: {note}")
    if not result.ok:
        for error in result.errors:
            print(f"error: {error}", file=sys.stderr)
        print(f"delta rejected: {len(result.errors)} error(s)", file=sys.stderr)
        return 1

    print(f"ok: delta {result.delta_id} validated against chapter {story['chapter']}")
    return 0


def _cmd_rules(root: Path, args: argparse.Namespace) -> int:
    from .gates import ledger_check

    project = runner.project_path(root, _resolve_slug(root, args.project))
    rules_file = ledger_check.rules_path(project)
    if not rules_file.is_file():
        raise runner.StoryError(
            f"no series bible at {rules_file}; run `story run series_bible` first"
        )

    if args.additions:
        additions_path = Path(args.additions)
    else:
        rules_additions = runner.resolve_stage("outline").dir_name
        additions_path = project / "stages" / rules_additions / "rules_additions.json"
    if not additions_path.is_file():
        raise runner.StoryError(
            f"rules additions not found: {additions_path}; run `story run outline` first"
        )
    try:
        additions = json.loads(additions_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise runner.StoryError(f"{additions_path} is not valid JSON: {exc}") from exc

    result = ledger.merge_rules(ledger.load_rules(rules_file), additions)
    if not result.ok:
        for error in result.errors:
            print(f"error: {error}", file=sys.stderr)
        return 1

    print(ledger.format_merge_diff(result))
    ledger.save_rules(result.rules, rules_file)
    print(f"rules: {rules_file}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = Path(args.root)

    try:
        if args.command == "init":
            return _cmd_init(root, args)
        if args.command == "status":
            return _cmd_status(root, args)
        if args.command == "roll":
            return _cmd_roll(root, args)
        if args.command == "lock":
            return _cmd_lock(root, args)
        if args.command == "reroll":
            return _cmd_reroll(root, args)
        if args.command == "run":
            return _cmd_run(root, args)
        if args.command == "approve":
            return _cmd_approve(root, args)
        if args.command == "ledger":
            return _cmd_ledger(root, args)
        if args.command == "rules":
            return _cmd_rules(root, args)
    except (runner.StoryError, AdapterError, ledger.LedgerError, ledger.RulesError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    milestone = PLANNED_IN.get(args.command, "a later milestone")
    print(
        f"story {args.command} is not implemented yet (planned for {milestone}); "
        "M3 covers `init`, `status`, `roll`, `lock`, `reroll`, `run` and `approve`. "
        "See BUILD_SPEC.md section 10.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
