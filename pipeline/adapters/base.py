"""Adapter interfaces.

Everything that talks to a model, a search engine or an image tool sits behind one of
these interfaces, so switching providers is a config change (see config.yaml).

Only the LLM adapters are implemented in milestone M1. `SearchAdapter` and
`ImageAdapter` are the interfaces that M4 (search) and M8 (illustration) fill in.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


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


class SearchAdapter(Adapter, ABC):
    """Web search. Interface only until milestone M4."""

    @abstractmethod
    def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        """Return up to `max_results` results for a query."""


class ImageAdapter(Adapter, ABC):
    """Illustration generation. Interface only until milestone M8."""

    @abstractmethod
    def generate(self, prompt: str, *, out_path: Path) -> Path:
        """Write one image to `out_path` and return it."""
