"""Adapter registry. Add a provider here, then select it in config.yaml."""

from __future__ import annotations

from typing import Any, Mapping

from .base import Adapter, AdapterError, ImageAdapter, LLMAdapter, SearchAdapter, SearchResult
from .echo import EchoAdapter
from .generic_json import GenericJSONSearchAdapter
from .manual import ManualAdapter, ManualPending
from .manual_search import ManualSearchAdapter, SearchPending
from .openai_compatible import OpenAICompatibleAdapter
from .stub_search import StubSearchAdapter
from .wikipedia import WikipediaAdapter

LLM_ADAPTERS: dict[str, type[LLMAdapter]] = {
    "echo": EchoAdapter,
    "manual": ManualAdapter,
    "openai_compatible": OpenAICompatibleAdapter,
}

SEARCH_ADAPTERS: dict[str, type[SearchAdapter]] = {
    "stub": StubSearchAdapter,
    "manual": ManualSearchAdapter,
    "wikipedia": WikipediaAdapter,
    "generic_json": GenericJSONSearchAdapter,
}


def create_llm_adapter(type_name: str, options: Mapping[str, Any] | None = None) -> LLMAdapter:
    """Build an LLM adapter by the name used in config.yaml."""
    try:
        adapter_class = LLM_ADAPTERS[type_name]
    except KeyError:
        known = ", ".join(sorted(LLM_ADAPTERS))
        raise AdapterError(f"unknown LLM adapter type {type_name!r} (known types: {known})") from None
    return adapter_class(options)


def create_search_adapter(
    type_name: str, options: Mapping[str, Any] | None = None
) -> SearchAdapter:
    """Build a search adapter by the name used in config.yaml."""
    try:
        adapter_class = SEARCH_ADAPTERS[type_name]
    except KeyError:
        known = ", ".join(sorted(SEARCH_ADAPTERS))
        raise AdapterError(
            f"unknown search adapter type {type_name!r} (known types: {known})"
        ) from None
    return adapter_class(options)


__all__ = [
    "Adapter",
    "AdapterError",
    "EchoAdapter",
    "GenericJSONSearchAdapter",
    "ImageAdapter",
    "LLMAdapter",
    "LLM_ADAPTERS",
    "ManualAdapter",
    "ManualPending",
    "ManualSearchAdapter",
    "OpenAICompatibleAdapter",
    "SEARCH_ADAPTERS",
    "SearchAdapter",
    "SearchPending",
    "SearchResult",
    "StubSearchAdapter",
    "WikipediaAdapter",
    "create_llm_adapter",
    "create_search_adapter",
]
