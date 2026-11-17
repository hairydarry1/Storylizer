"""`craft_targets.json`: the ranges Addendum A writes, sampled with the run seed.

The file is optional. A value is a number or a `[min, max]` range; the stage samples one point
inside it with the same `sha256(seed|stage|key)` scheme the randomizer uses, so the same config
always produces the same book.

Recognised keys:

* `chapters.words` - words per chapter (stage 11)
* `chapters.scenes` - scenes per chapter (stage 12)
* `sentences.words` - mean words per sentence (stage 13)
* `paragraphs.sentences` - sentences per paragraph (stage 13)
* `dialogue_ratio` - share of the page that is dialogue (stage 13)
* `pov`, `tense` - plain strings (stage 13)
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

DEFAULTS: dict[str, Any] = {
    "chapters.words": 2500,
    "chapters.scenes": 3,
    "sentences.words": 14,
    "paragraphs.sentences": 3,
    "dialogue_ratio": 0.3,
    "pov": "third person limited",
    "tense": "past",
}


class CraftTargetError(ValueError):
    """A craft_targets.json the stages cannot sample from."""


@dataclass(frozen=True)
class Targets:
    path: Path
    data: dict[str, Any]


def find_targets(project: Path | str, root: Path | str | None = None) -> Path | None:
    """The project's craft_targets.json, else the pipeline root's, else None."""
    candidates = [Path(project) / "craft_targets.json"]
    if root is not None:
        candidates.append(Path(root) / "craft_targets.json")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def load_targets(path: Path | str | None) -> Targets | None:
    if path is None:
        return None
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise CraftTargetError(f"craft targets file {path} is unreadable: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise CraftTargetError(f"craft targets file {path} is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise CraftTargetError(f"craft targets file {path} must contain a JSON object")
    return Targets(path=path, data=raw)


def _lookup(targets: Mapping[str, Any] | None, dotted: str) -> Any:
    current: Any = targets or {}
    for part in dotted.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def _range(raw: Any, dotted: str) -> tuple[float, float, bool]:
    if isinstance(raw, bool):
        raise CraftTargetError(f"craft_targets.json: {dotted} must be a number or a [min, max] range")
    if isinstance(raw, (int, float)):
        return float(raw), float(raw), isinstance(raw, int)
    if (
        isinstance(raw, (list, tuple))
        and len(raw) == 2
        and all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in raw)
    ):
        low, high = sorted(float(value) for value in raw)
        is_int = all(isinstance(value, int) for value in raw)
        return low, high, is_int
    raise CraftTargetError(f"craft_targets.json: {dotted} must be a number or a [min, max] range")


def sample(
    targets: Targets | None,
    dotted: str,
    *,
    seed: int,
    stage: str,
    key: str,
    default: Any = None,
) -> tuple[Any, bool]:
    """Sample one point inside the target range. Returns (value, came_from_targets)."""
    fallback = DEFAULTS.get(dotted) if default is None else default
    raw = _lookup(targets.data if targets else None, dotted)
    if raw is None:
        return fallback, False

    low, high, is_int = _range(raw, dotted)
    from .randomizer import seed_int  # imported here so this module stays import-free of runner

    rng = random.Random(seed_int(seed, stage, key))
    if is_int:
        return rng.randint(int(low), int(high)), True
    return round(rng.uniform(low, high), 3), True


def text(targets: Targets | None, dotted: str, *, default: str = "") -> tuple[str, bool]:
    """A plain string target such as `pov`; falls back to the default."""
    fallback = DEFAULTS.get(dotted, default) if not default else default
    raw = _lookup(targets.data if targets else None, dotted)
    if not isinstance(raw, str) or not raw.strip():
        return fallback, False
    return raw.strip(), True
