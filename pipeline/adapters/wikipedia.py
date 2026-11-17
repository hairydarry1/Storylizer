"""Wikipedia search through the public MediaWiki API.

No key and no scraping: this is the documented JSON endpoint
(`action=query&list=search`) at `https://en.wikipedia.org/w/api.php`, with a
descriptive User-Agent and a cap of ten results per call.
"""

from __future__ import annotations

import html
import re
from typing import Any, Callable, Mapping
from urllib.parse import quote

import requests

from .base import AdapterError, SearchAdapter, SearchResult, usable_search_results

DEFAULT_API_URL = "https://en.wikipedia.org/w/api.php"
USER_AGENT = "story-pipeline/0.1 (fiction research; https://github.com/)"
_TAGS = re.compile(r"<[^>]+>")


def _plain_text(value: str) -> str:
    return html.unescape(_TAGS.sub("", value or "")).strip()


class WikipediaAdapter(SearchAdapter):
    name = "wikipedia"

    def __init__(self, options: Mapping[str, Any] | None = None) -> None:
        super().__init__(options)
        self.base_url = str(self.options.get("base_url", DEFAULT_API_URL))
        self.language = str(self.options.get("language", "en"))
        self.timeout = float(self.options.get("timeout", 30))
        self.user_agent = str(self.options.get("user_agent", USER_AGENT))
        self._get: Callable[..., Any] = self.options.get("get", requests.get)

    def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        limit = max(1, min(int(max_results), 10))
        params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": limit,
            "srprop": "snippet",
            "format": "json",
            "utf8": 1,
        }
        try:
            response = self._get(
                self.base_url,
                params=params,
                headers={"User-Agent": self.user_agent, "Accept": "application/json"},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:  # pragma: no cover - network path
            raise AdapterError(f"wikipedia search failed: {exc}") from exc

        status = int(getattr(response, "status_code", 0))
        if status != 200:
            raise AdapterError(f"wikipedia search returned HTTP {status}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise AdapterError("wikipedia returned a response that was not JSON") from exc

        items = list(((payload.get("query") or {}).get("search") or []))
        results = [
            SearchResult(
                title=str(item.get("title") or ""),
                url=(
                    f"https://{self.language}.wikipedia.org/wiki/"
                    f"{quote(str(item.get('title') or '').replace(' ', '_'))}"
                ),
                snippet=_plain_text(str(item.get("snippet") or "")),
            )
            for item in items
        ]
        return usable_search_results(results, max_results)

    def describe(self) -> dict[str, Any]:
        return {**super().describe(), "base_url": self.base_url, "language": self.language}
