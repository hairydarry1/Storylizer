"""OpenAI-compatible adapter: any endpoint that speaks POST /chat/completions.

Works with OpenRouter, Together, Gemini, Groq, vLLM, LM Studio and similar. The API key is
read from an environment variable named in config.yaml and is never written to disk or to
meta.json.

Config options:
    base_url        e.g. https://openrouter.ai/api/v1
    model           default model name
    api_key_env     environment variable holding the key (default OPENAI_API_KEY)
    models          optional tier -> model mapping, e.g. {writer: big/model}
    timeout         request timeout in seconds (default 120)
    retries         retries after the first attempt for 429/5xx (default 2)
    backoff         first wait in seconds; doubles on each retry (default 1.0)
    max_backoff     ceiling for one wait, including Retry-After (default 60)
    post            optional callable used instead of requests.post (tests)
    sleep           optional callable used instead of time.sleep (tests)
    now             optional clock for parsing Retry-After dates (tests)

Rate limits: 429 and 5xx responses are retried; `Retry-After` (seconds or an HTTP date) wins
over the exponential backoff. The provider's remaining-quota headers are kept in
`last_quota` and appended to the error when a request finally fails.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Mapping

import requests

from .base import AdapterError, LLMAdapter

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
QUOTA_HEADERS = (
    "x-ratelimit-remaining-requests",
    "x-ratelimit-remaining-tokens",
    "x-ratelimit-limit-requests",
    "x-ratelimit-limit-tokens",
    "x-ratelimit-reset-requests",
    "x-ratelimit-reset-tokens",
    "retry-after",
)


def _header(headers: Mapping[str, Any] | None, name: str) -> str | None:
    """Case-insensitive header lookup that also works with plain dicts in tests."""
    if not headers:
        return None
    lowered = name.casefold()
    for key, value in headers.items():
        if str(key).casefold() == lowered:
            return str(value)
    return None


def _is_retryable(status_code: int) -> bool:
    return status_code == 429 or status_code in RETRY_STATUSES or status_code >= 500


class OpenAICompatibleAdapter(LLMAdapter):
    name = "openai_compatible"

    def __init__(self, options: Mapping[str, Any] | None = None) -> None:
        super().__init__(options)
        self.base_url = str(self.options.get("base_url") or "https://api.openai.com/v1").rstrip("/")
        model = self.options.get("model")
        if not model:
            raise AdapterError("openai_compatible adapter needs a 'model' in its config options")
        self.model = str(model)
        self.api_key_env = str(self.options.get("api_key_env", "OPENAI_API_KEY"))
        self.models = dict(self.options.get("models") or {})
        self.timeout = float(self.options.get("timeout", 120))
        self.retries = max(0, int(self.options.get("retries", 2)))
        self.backoff = max(0.0, float(self.options.get("backoff", 1.0)))
        self.max_backoff = max(0.0, float(self.options.get("max_backoff", 60)))
        self._post = self.options.get("post") or requests.post
        self._sleep = self.options.get("sleep") or time.sleep
        self._now = self.options.get("now") or (lambda: datetime.now(timezone.utc).timestamp())
        self.last_model: str | None = None
        #: Rate-limit headers from the most recent response, when the provider sent any.
        self.last_quota: dict[str, str] | None = None

    def resolve_model(self, model_tier: str | None = None) -> str:
        if model_tier and self.models.get(model_tier):
            return str(self.models[model_tier])
        return self.model

    # -- retries ---------------------------------------------------------------

    def _capture_quota(self, response: Any) -> None:
        headers = getattr(response, "headers", None)
        found: dict[str, str] = {}
        for name in QUOTA_HEADERS:
            value = _header(headers, name)
            if value is not None:
                found[name] = value
        self.last_quota = found or None

    def _retry_after(self, response: Any) -> float | None:
        value = _header(getattr(response, "headers", None), "retry-after")
        if not value:
            return None
        text = value.strip()
        try:
            return max(0.0, float(text))
        except ValueError:
            pass
        try:
            when = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return max(0.0, when.timestamp() - self._now())

    def _wait(self, response: Any, attempt: int) -> float:
        delay = self._retry_after(response)
        if delay is None:
            delay = self.backoff * (2 ** (attempt - 1))
        return min(delay, self.max_backoff)

    def _quota_suffix(self) -> str:
        if not self.last_quota:
            return ""
        pairs = ", ".join(f"{name}={value}" for name, value in self.last_quota.items())
        return f" (quota: {pairs})"

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model_tier: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        api_key = os.environ.get(self.api_key_env)
        if not api_key:
            raise AdapterError(
                f"environment variable {self.api_key_env} is not set; "
                "API keys come from the environment and are never stored in config files"
            )

        model = self.resolve_model(model_tier)
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {"model": model, "messages": messages}
        if max_tokens is not None:
            payload["max_tokens"] = int(max_tokens)

        attempts = self.retries + 1
        response = None
        for attempt in range(1, attempts + 1):
            response = self._post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self.timeout,
            )
            self._capture_quota(response)
            if response.status_code == 200:
                break
            if _is_retryable(response.status_code) and attempt < attempts:
                self._sleep(self._wait(response, attempt))
                continue
            detail = (getattr(response, "text", "") or "")[:300]
            raise AdapterError(
                f"model request to {self.base_url} failed: HTTP {response.status_code} "
                f"{detail}{self._quota_suffix()}".strip()
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise AdapterError(f"model response from {self.base_url} was not JSON") from exc

        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AdapterError("model response had no choices[0].message.content") from exc
        if not isinstance(text, str):
            raise AdapterError("model response content was not text")

        self.last_model = model
        return text.strip()

    def describe(self) -> dict[str, Any]:
        return {
            **super().describe(),
            "base_url": self.base_url,
            "model": self.model,
            "api_key_env": self.api_key_env,
        }
