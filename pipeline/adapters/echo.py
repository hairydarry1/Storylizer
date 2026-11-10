"""Echo adapter: returns a fixed string. Used by tests and dry runs, never for real writing."""

from __future__ import annotations

from typing import Any, Mapping

from .base import LLMAdapter


class EchoAdapter(LLMAdapter):
    name = "echo"

    def __init__(self, options: Mapping[str, Any] | None = None) -> None:
        super().__init__(options)
        self.response = str(self.options.get("response", "echo"))
        self.calls: list[dict[str, Any]] = []

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model_tier: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        self.calls.append(
            {
                "prompt": prompt,
                "system": system,
                "model_tier": model_tier,
                "max_tokens": max_tokens,
            }
        )
        return self.response

    def describe(self) -> dict[str, Any]:
        return {**super().describe(), "response_length": len(self.response)}
