"""Stub search adapter: returns canned results and records queries.

It is the default in config.yaml, so `story run all` works offline, and it is what the
tests use. No network, no API key, no scraping.
"""

from __future__ import annotations

from typing import Any, Mapping

from .base import SearchAdapter, SearchResult, usable_search_results


class StubSearchAdapter(SearchAdapter):
    name = "stub"

    def __init__(self, options: Mapping[str, Any] | None = None) -> None:
        super().__init__(options)
        self.results = self._parse(self.options.get("results") or [])
        self.by_query = {
            str(query): self._parse(items or [])
            for query, items in dict(self.options.get("by_query") or {}).items()
        }
        self.calls: list[str] = []

    @staticmethod
    def _parse(items) -> list[SearchResult]:
        parsed: list[SearchResult] = []
        for item in items:
            if isinstance(item, SearchResult):
                parsed.append(item)
            elif isinstance(item, Mapping):
                parsed.append(
                    SearchResult(
                        title=str(item.get("title") or ""),
                        url=str(item.get("url") or ""),
                        snippet=str(item.get("snippet") or ""),
                    )
                )
        return parsed

    def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        self.calls.append(query)
        items = self.by_query.get(query, self.results)
        return usable_search_results(items, max_results)

    def describe(self) -> dict[str, Any]:
        return {
            **super().describe(),
            "canned_results": len(self.results),
            "queries": len(self.by_query),
        }
