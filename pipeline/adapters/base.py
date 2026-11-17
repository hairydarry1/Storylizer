"""Adapter interfaces.

Everything that talks to a model, a search engine or an image tool sits behind one of
these interfaces, so switching providers is a config change (see config.yaml).

LLM and search adapters are implemented. `ImageAdapter` is the interface M8
(illustration) fills in.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit


class AdapterError(RuntimeError):
    """Raised when an adapter cannot produce a result."""


class Adapter(ABC):
    """Common base: every adapter is built from the `options` mapping in config.yaml."""

    name: str = "adapter"

    def __init__(self, options: Mapping[str, Any] | None = None) -> None:
        self.options = dict(options or {})

    def describe(self) -> dict[str, Any]:
        """Metadata safe to write into a stage's meta.json (never secrets)."""
        return {"adapter": self.name}


class LLMAdapter(Adapter, ABC):
    """Text generation. `model_tier` is planner | writer | checker (see skills frontmatter)."""

    @abstractmethod
    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model_tier: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Return the model's reply as text."""


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str

    def to_dict(self) -> dict[str, str]:
        return {"title": self.title, "url": self.url, "snippet": self.snippet}


def is_amazon_url(url: str) -> bool:
    """True for any Amazon storefront or short link.

    The pipeline never scrapes Amazon: market numbers come from notes the user pastes
    into `inputs/market_notes.md`, not from the storefront.
    """
    host = (urlsplit(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return (
        host == "amazon"
        or host.startswith("amazon.")
        or ".amazon." in host
        or host in {"amzn.to", "amzn.eu"}
        or host.endswith(".amzn.to")
    )


def usable_search_results(
    results: Iterable[SearchResult], max_results: int
) -> list[SearchResult]:
    """Drop Amazon and empty URLs, then cap the list."""
    if max_results <= 0:
        return []
    kept: list[SearchResult] = []
    for result in results:
        if not result.url or is_amazon_url(result.url):
            continue
        kept.append(result)
        if len(kept) >= max_results:
            break
    return kept


class SearchAdapter(Adapter, ABC):
    """Web search, always read-only: adapters call APIs and never scrape pages."""

    @abstractmethod
    def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        """Return up to `max_results` results for a query."""


class ImageAdapter(Adapter, ABC):
    """Illustration generation. Interface only until milestone M8."""

    @abstractmethod
    def generate(self, prompt: str, *, out_path: Path) -> Path:
        """Write one image to `out_path` and return it."""
