"""The ledger gate (BUILD_SPEC.md section 7): a chapter's delta has to be earned.

`ledger.validate_delta` does the checking; this module is the gate wrapper that finds the
project's `ledger.json` and the bible's `rules.json`, runs the check and renders the report a
chapter revision loop can attach to its feedback.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .. import ledger

STAGE_DIRNAME = "10-series_bible"


class MissingBibleError(ledger.LedgerError):
    """The project has no series bible yet, so there are no rules to check against."""


def stage_directory(project: Path | str) -> Path:
    return Path(project) / "stages" / STAGE_DIRNAME


def rules_path(project: Path | str) -> Path:
    return stage_directory(project) / "rules.json"


def ledger_path(project: Path | str) -> Path:
    return Path(project) / "ledger.json"


@dataclass
class CheckResult:
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


def load_story_state(project: Path | str) -> tuple[dict[str, Any], dict[str, Any]]:
    """The project's ledger and the bible's rules, with a readable error when either is missing."""
    rules_file = rules_path(project)
    ledger_file = ledger_path(project)
    missing = [path for path in (rules_file, ledger_file) if not path.is_file()]
    if missing:
        raise MissingBibleError(
            f"no series bible at {rules_file}; run `story run series_bible` first"
        )
    return ledger.load_ledger(ledger_file), ledger.load_rules(rules_file)


def check_delta(
    story: Mapping[str, Any], rules: Mapping[str, Any], delta: Mapping[str, Any]
) -> CheckResult:
    report = ledger.validate_delta(story, rules, delta)
    return CheckResult(
        delta_id=report.delta_id, errors=list(report.errors), notes=list(report.notes)
    )


def render_check(delta: Mapping[str, Any], result: CheckResult) -> str:
    """Markdown report for one delta, in the same shape as the other gate reports."""
    chapter = delta.get("chapter", "?") if isinstance(delta, Mapping) else "?"
    lines = [
        "# Ledger check",
        "",
        f"- delta: {result.delta_id or '(unnamed)'}",
        f"- chapter: {chapter}",
        f"- status: {'ok' if result.ok else 'failed'}",
        "",
    ]
    if result.errors:
        lines += ["## Errors", ""]
        lines.extend(f"- {error}" for error in result.errors)
    else:
        lines.append("No errors.")
    if result.notes:
        lines += ["", "## Notes", ""]
        lines.extend(f"- {note}" for note in result.notes)
    return "\n".join(lines) + "\n"
