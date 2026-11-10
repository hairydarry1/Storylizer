"""OpenAI-compatible adapter: any endpoint that speaks POST /chat/completions.

Works with OpenRouter, Together, vLLM, LM Studio and similar. The API key is read from
an environment variable named in config.yaml and is never written to disk or to meta.json.

Config options:
    base_url      e.g. https://openrouter.ai/api/v1
    model         default model name
    api_key_env   environment variable holding the key (default OPENAI_API_KEY)
    models        optional tier -> model mapping, e.g. {writer: big/model}
    timeout       request timeout in seconds (default 120)
    post          optional callable used instead of requests.post (tests)
"""

from __future__ import annotations

import os
from typing import Any, Mapping

import requests

from .base import AdapterError, LLMAdapter


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
        self._post = self.options.get("post") or requests.post
        self.last_model: str | None = None

    def resolve_model(self, model_tier: str | None = None) -> str:
        if model_tier and self.models.get(model_tier):
            return str(self.models[model_tier])
        return self.model

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

        response = self._post(
            f"{self.base_url}/chat/completions",
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=self.timeout,
        )
        if response.status_code != 200:
            detail = (getattr(response, "text", "") or "")[:300]
            raise AdapterError(f"model request to {self.base_url} failed: HTTP {response.status_code} {detail}".strip())

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
