"""A tiny, dependency-free .env loader (quick task, not a numbered milestone).

The loader reads one file, ``<root>/.env``, and copies entries into the process environment
only when the name is not already set. Values are never printed, logged or returned inside
error messages. Parsing supports blank lines, ``#`` comments, ``KEY=value``,
``KEY="value"``, ``KEY='value'`` and an optional ``export`` prefix.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import MutableMapping

ENV_FILENAME = ".env"
_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


class EnvFileError(RuntimeError):
    """The .env file exists but could not be read. The message never includes values."""


def _parse_value(raw: str) -> str | None:
    """Return the value without its quotes, or None for a malformed quoted value."""
    value = raw.strip()
    if not value:
        return ""
    if value[0] in ("'", '"'):
        quote = value[0]
        end = value.find(quote, 1)
        if end == -1:
            return None
        remainder = value[end + 1 :].strip()
        if remainder and not remainder.startswith("#"):
            return None
        return value[1:end]

    comment = value.find(" #")
    if comment != -1:
        value = value[:comment].rstrip()
    return value


def parse_env(text: str) -> dict[str, str]:
    """Parse .env text. Malformed lines are ignored, never echoed."""
    values: dict[str, str] = {}
    for raw_line in text.lstrip("\ufeff").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export") and len(line) > 6 and line[6].isspace():
            line = line[6:].lstrip()
        if "=" not in line:
            continue

        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not _KEY.fullmatch(key):
            continue
        value = _parse_value(raw_value)
        if value is not None:
            values[key] = value
    return values


def load_env(
    root: Path | str,
    environ: MutableMapping[str, str] | None = None,
) -> dict[str, str]:
    """Read ``<root>/.env`` and set only names that are absent from the environment.

    Returns the entries that were applied. A missing file is not an error.
    """
    path = Path(root) / ENV_FILENAME
    if not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise EnvFileError(f"could not read {path}") from exc

    target = os.environ if environ is None else environ
    applied: dict[str, str] = {}
    for key, value in parse_env(text).items():
        if key in target:
            continue
        target[key] = value
        applied[key] = value
    return applied
