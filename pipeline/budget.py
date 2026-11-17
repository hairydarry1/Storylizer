"""Daily model-call counter and the `--max-calls` limit (milestone M6c).

Free providers reset their quota each day, so the pipeline keeps its own tally in
`projects/<slug>/calls.json`:

    {"days": {"2026-11-17": 12}, "updated_at": "..."}

Every `llm.complete` goes through `BudgetedLLMAdapter`, which increments the tally before
the request and saves it immediately, so a crash or a failed stage does not lose the count.
`--max-calls N` caps the calls made by one run; the persisted per-day total keeps counting
across runs.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .adapters.base import AdapterError, LLMAdapter

COUNTER_FILE = "calls.json"
KEEP_DAYS = 90


class BudgetExceeded(AdapterError):
    """The run's model-call budget is used up."""


def _utc_today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


class CallCounter:
    """A per-day call tally for one project, with an optional per-run limit."""

    def __init__(
        self,
        project: Path | str,
        *,
        limit: int | None = None,
        today: str | None = None,
    ) -> None:
        if limit is not None and limit < 1:
            raise ValueError("the model call limit must be at least 1")
        self.path = Path(project) / COUNTER_FILE
        self.limit = limit
        self.today = today or _utc_today()
        self.used = 0
        self.days = self._load()

    def _load(self) -> dict[str, int]:
        if not self.path.is_file():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        days = raw.get("days") if isinstance(raw, dict) else None
        if not isinstance(days, dict):
            return {}
        try:
            cutoff = (date.fromisoformat(self.today) - timedelta(days=KEEP_DAYS)).isoformat()
        except ValueError:
            cutoff = ""
        counts: dict[str, int] = {}
        for day, count in days.items():
            if str(day) < cutoff:
                continue
            if isinstance(count, int) and not isinstance(count, bool) and count > 0:
                counts[str(day)] = count
        return dict(sorted(counts.items(), reverse=True)[:KEEP_DAYS])

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "days": dict(sorted(self.days.items())),
            "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        }
        self.path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    @property
    def today_total(self) -> int:
        return self.days.get(self.today, 0)

    def spend(self) -> None:
        """Account for one model call, or refuse when this run's limit is reached."""
        if self.limit is not None and self.used >= self.limit:
            raise BudgetExceeded(
                f"model call budget of {self.limit} for this run is used up "
                f"({self.today_total} call(s) today across runs)"
            )
        self.used += 1
        self.days[self.today] = self.today_total + 1
        self._save()

    def summary(self, *, started_at: int = 0) -> dict[str, Any]:
        return {
            "run": self.used - started_at,
            "today": self.today_total,
            "limit": self.limit,
        }


class BudgetedLLMAdapter(LLMAdapter):
    """Count every call before delegating to the real adapter."""

    def __init__(self, adapter: LLMAdapter, counter: CallCounter) -> None:
        super().__init__({})
        self.adapter = adapter
        self.counter = counter
        self.name = getattr(adapter, "name", "adapter")

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model_tier: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        self.counter.spend()
        return self.adapter.complete(
            prompt, system=system, model_tier=model_tier, max_tokens=max_tokens
        )

    @property
    def last_quota(self) -> Any:
        return getattr(self.adapter, "last_quota", None)

    def describe(self) -> dict[str, Any]:
        described = self.adapter.describe()
        described["calls_today"] = self.counter.today_total
        if self.counter.limit is not None:
            described["call_limit"] = self.counter.limit
        return described
