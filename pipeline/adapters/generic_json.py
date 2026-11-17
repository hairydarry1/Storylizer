"""Generic JSON search adapter for hosted search APIs (Brave, Tavily, ...).

The key is read from an environment variable named in config, never from config
itself, and never written to meta.json. The response shape is configurable:

    adapters:
      search:
        type: generic_json
        options:
          base_url: https://api.search.brave.com/res/v1/web/search
          api_key_env: BRAVE_API_KEY
          api_key_header: X-Subscription-Token
          results_path: web.results
          fields: {title: title, url: url, snippet: description}

For Tavily set `method: POST`, `auth: body`, `api_key_field: api_key`,
`query_param: query`, `max_results_param: max_results` and `results_path: results`.
Only JSON is read; pages are never fetched.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Mapping

import requests

from .base import AdapterError, SearchAdapter, SearchResult, usable_search_results

DEFAULT_FIELDS = {"title": "title", "url": "url", "snippet": "snippet"}


def _nested(payload: Any, path: str) -> Any:
    if not path:
        return payload
    current = payload
    for part in path.split("."):
        if not isinstance(current, Mapping):
            return None
        current = current.get(part)
    return current


class GenericJSONSearchAdapter(SearchAdapter):
    name = "generic_json"

    def __init__(self, options: Mapping[str, Any] | None = None) -> None:
        super().__init__(options)
        self.base_url = str(self.options.get("base_url") or "").strip()
        if not self.base_url:
            raise AdapterError("generic_json search needs options.base_url")
        self.api_key_env = str(self.options.get("api_key_env") or "SEARCH_API_KEY")
        self.method = str(self.options.get("method", "GET")).upper()
        if self.method not in {"GET", "POST"}:
            raise AdapterError("generic_json options.method must be GET or POST")
        self.auth = str(self.options.get("auth", "header"))
        if self.auth not in {"header", "body"}:
            raise AdapterError("generic_json options.auth must be header or body")
        self.api_key_header = str(self.options.get("api_key_header", "X-Subscription-Token"))
        self.api_key_field = str(self.options.get("api_key_field", "api_key"))
        self.api_key_prefix = str(self.options.get("api_key_prefix", ""))
        self.query_param = str(self.options.get("query_param", "q"))
        self.max_results_param = str(self.options.get("max_results_param", "count"))
        self.results_path = str(self.options.get("results_path", "results"))
        self.fields = {**DEFAULT_FIELDS, **dict(self.options.get("fields") or {})}
        self.extra_params = dict(self.options.get("params") or {})
        self.timeout = float(self.options.get("timeout", 30))
        self._request: Callable[..., Any] = self.options.get("request", requests.request)

    def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        api_key = os.environ.get(self.api_key_env, "").strip()
        if not api_key:
            raise AdapterError(
                f"generic_json search needs the environment variable {self.api_key_env}"
            )

        payload: dict[str, Any] = {
            **self.extra_params,
            self.query_param: query,
            self.max_results_param: max_results,
        }
        headers = {"Accept": "application/json"}
        kwargs: dict[str, Any] = {"headers": headers, "timeout": self.timeout}

        if self.auth == "header":
            headers[self.api_key_header] = f"{self.api_key_prefix}{api_key}"
        else:
            payload[self.api_key_field] = api_key

        if self.method == "GET":
            kwargs["params"] = payload
        else:
            kwargs["json"] = payload

        try:
            response = self._request(self.method, self.base_url, **kwargs)
        except requests.RequestException as exc:  # pragma: no cover - network path
            raise AdapterError(f"generic_json search failed: {exc}") from exc

        status = int(getattr(response, "status_code", 0))
        if status != 200:
            raise AdapterError(f"generic_json search returned HTTP {status}")

        try:
            body = response.json()
        except ValueError as exc:
            raise AdapterError("generic_json returned a response that was not JSON") from exc

        items = _nested(body, self.results_path)
        if items is None:
            raise AdapterError(
                f"generic_json response has no {self.results_path!r} list; check results_path"
            )
        if isinstance(items, Mapping):
            items = [items]
        if not isinstance(items, list):
            raise AdapterError(f"generic_json {self.results_path!r} is not a list")

        results = []
        for item in items:
            if not isinstance(item, Mapping):
                continue
            results.append(
                SearchResult(
                    title=str(item.get(self.fields["title"]) or ""),
                    url=str(item.get(self.fields["url"]) or ""),
                    snippet=str(item.get(self.fields["snippet"]) or ""),
                )
            )
        return usable_search_results(results, max_results)

    def describe(self) -> dict[str, Any]:
        return {
            **super().describe(),
            "base_url": self.base_url,
            "method": self.method,
            "results_path": self.results_path,
            "api_key_env": self.api_key_env,
        }
