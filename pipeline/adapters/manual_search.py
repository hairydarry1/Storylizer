"""Manual search adapter: works with any browser and any search engine.

Each call writes the query to `<directory>/<prefix>NNNN.query.md` and waits for
`<directory>/<prefix>NNNN.results.json`. Paste results as a JSON array (or one
`Title | URL | snippet` per line); nothing leaves the machine and no key is needed.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Mapping

from .base import AdapterError, SearchAdapter, SearchResult, usable_search_results


class SearchPending(AdapterError):
    """No results file yet. Carries both paths so the caller can tell the user what to do."""

    def __init__(self, query_path: Path, results_path: Path, timeout: float) -> None:
        self.query_path = Path(query_path)
        self.results_path = Path(results_path)
        self.timeout = timeout
        super().__init__(
            f"no search results at {self.results_path} after waiting {timeout:g}s "
            f"(query saved at {self.query_path}); paste results into the results file and run again"
        )


class ManualSearchAdapter(SearchAdapter):
    name = "manual"

    def __init__(self, options: Mapping[str, Any] | None = None) -> None:
        super().__init__(options)
        self.directory = Path(str(self.options.get("directory", ".manual")))
        self.timeout = float(self.options.get("timeout", 3600))
        self.poll_interval = float(self.options.get("poll_interval", 2.0))
        self.prefix = str(self.options.get("prefix", ""))
        #: (query_path, results_path) of the most recent exchange, set before waiting.
        self.last_paths: tuple[Path, Path] | None = None

    def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        query_path, results_path = self._next_paths()
        self.last_paths = (query_path, results_path)
        query_path.write_text(self._query_text(query, max_results), encoding="utf-8")

        deadline = time.monotonic() + max(self.timeout, 0.0)
        while True:
            results = self._read_results(results_path, max_results)
            if results is not None:
                return results
            if time.monotonic() >= deadline:
                raise SearchPending(query_path, results_path, self.timeout)
            time.sleep(self.poll_interval)

    def describe(self) -> dict[str, Any]:
        return {**super().describe(), "directory": str(self.directory)}

    def _next_paths(self) -> tuple[Path, Path]:
        self.directory.mkdir(parents=True, exist_ok=True)
        index = sum(1 for _ in self.directory.glob("*.query.md")) + 1
        stem = f"{self.prefix}{index:04d}"
        return self.directory / f"{stem}.query.md", self.directory / f"{stem}.results.json"

    @staticmethod
    def _query_text(query: str, max_results: int) -> str:
        return (
            "# Search query\n\n"
            f"{query}\n\n"
            "---\n\n"
            f"Paste up to {max_results} results into the matching `.results.json` file as:\n\n"
            '[\n  {"title": "...", "url": "...", "snippet": "..."}\n]\n\n'
            "or one `Title | URL | snippet` per line. Amazon links are ignored.\n"
        )

    @classmethod
    def _read_results(cls, path: Path, max_results: int) -> list[SearchResult] | None:
        if not path.is_file():
            return None
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return None

        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            results = cls._parse_lines(text)
            if results is None:
                raise AdapterError(
                    f"{path} is neither JSON nor `Title | URL | snippet` lines"
                ) from None
            return usable_search_results(results, max_results)

        items = payload.get("results") if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            raise AdapterError(f"{path} must contain a JSON list or a 'results' list")
        results = [
            SearchResult(
                title=str(item.get("title") or ""),
                url=str(item.get("url") or ""),
                snippet=str(item.get("snippet") or ""),
            )
            for item in items
            if isinstance(item, dict)
        ]
        return usable_search_results(results, max_results)

    @staticmethod
    def _parse_lines(text: str) -> list[SearchResult] | None:
        results: list[SearchResult] = []
        for line in text.splitlines():
            line = line.strip().lstrip("-*").strip()
            if not line or "|" not in line:
                continue
            parts = [part.strip() for part in line.split("|")]
            if len(parts) < 2 or not parts[1].startswith("http"):
                continue
            title = parts[0]
            snippet = " | ".join(parts[2:]) if len(parts) > 2 else ""
            results.append(SearchResult(title=title, url=parts[1], snippet=snippet))
        return results or None
