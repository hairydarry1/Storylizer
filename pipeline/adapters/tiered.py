"""Per-tier providers behind one OpenAI-compatible adapter.

Gemini, Groq and OpenRouter all speak POST /chat/completions, so a project can send the
planner, the writer and the checker to different endpoints by adding a `providers` block to
`adapters.llm.options` in config.yaml. Each tier inherits the base options and overrides
only what it needs.

    options:
      base_url: https://openrouter.ai/api/v1
      model: default/model
      api_key_env: OPENROUTER_API_KEY
      providers:
        planner: {base_url: ..., model: ..., api_key_env: ...}
        writer:  {base_url: ..., model: ..., api_key_env: ...}
        checker: {base_url: ..., model: ..., api_key_env: ...}

The API keys themselves still come from the environment (BUILD_SPEC.md section 2).
"""

from __future__ import annotations

from typing import Any, Mapping

from .base import AdapterError, LLMAdapter

TIER_NAMES = ("planner", "writer", "checker")


class TieredLLMAdapter(LLMAdapter):
    """Route each model tier to its own adapter, with the base adapter as the fallback."""

    name = "openai_compatible"

    def __init__(
        self,
        providers: Mapping[str, LLMAdapter],
        *,
        default: LLMAdapter | None = None,
    ) -> None:
        super().__init__({})
        self.providers = dict(providers)
        self.default = default
        self.last_model: str | None = None

    def _adapter(self, model_tier: str | None) -> LLMAdapter:
        if model_tier and model_tier in self.providers:
            return self.providers[model_tier]
        if self.default is not None:
            return self.default
        known = ", ".join(sorted(self.providers)) or "none"
        raise AdapterError(
            f"no provider configured for model tier {model_tier!r} "
            f"(configured tiers: {known}); add it under adapters.llm.options.providers "
            "or set a default model"
        )

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model_tier: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        adapter = self._adapter(model_tier)
        text = adapter.complete(
            prompt, system=system, model_tier=model_tier, max_tokens=max_tokens
        )
        self.last_model = getattr(adapter, "last_model", None)
        return text

    @property
    def last_quota(self) -> dict[str, Any] | None:
        """Quota headers from the most recent provider response, tagged with its tier."""
        for tier, adapter in self.providers.items():
            quota = getattr(adapter, "last_quota", None)
            if quota:
                return {tier: quota}
        default_quota = getattr(self.default, "last_quota", None) if self.default else None
        if default_quota:
            return {"default": default_quota}
        return None

    def describe(self) -> dict[str, Any]:
        described: dict[str, Any] = {
            "adapter": self.name,
            "tiers": {tier: adapter.describe() for tier, adapter in self.providers.items()},
        }
        if self.default is not None:
            described["default"] = self.default.describe()
        return described
