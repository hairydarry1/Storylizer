"""Adapter registry. Add a provider here, then select it in config.yaml."""

from __future__ import annotations

from typing import Any, Mapping

from .base import Adapter, AdapterError, ImageAdapter, LLMAdapter, SearchAdapter, SearchResult
from .echo import EchoAdapter
from .manual import ManualAdapter, ManualPending
from .openai_compatible import OpenAICompatibleAdapter

LLM_ADAPTERS: dict[str, type[LLMAdapter]] = {
    "echo": EchoAdapter,
    "manual": ManualAdapter,
    "openai_compatible": OpenAICompatibleAdapter,
}


def create_llm_adapter(type_name: str, options: Mapping[str, Any] | None = None) -> LLMAdapter:
    """Build an LLM adapter by the name used in config.yaml."""
    try:
        adapter_class = LLM_ADAPTERS[type_name]
    except KeyError:
        known = ", ".join(sorted(LLM_ADAPTERS))
        raise AdapterError(f"unknown LLM adapter type {type_name!r} (known types: {known})") from None
    return adapter_class(options)


__all__ = [
    "Adapter",
    "AdapterError",
    "EchoAdapter",
    "ImageAdapter",
    "LLMAdapter",
    "LLM_ADAPTERS",
    "ManualAdapter",
    "ManualPending",
    "OpenAICompatibleAdapter",
    "SearchAdapter",
    "SearchResult",
    "create_llm_adapter",
]
