"""Manual adapter: works with any chat tool.

Each call writes the prompt to `<directory>/<prefix>NNNN.prompt.md` and then waits for
the user to paste the model's reply into `<directory>/<prefix>NNNN.reply.md`. Nothing
leaves the machine and no API key is needed.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Mapping

from .base import AdapterError, LLMAdapter


class ManualPending(AdapterError):
    """No reply file yet. Carries both paths so the caller can tell the user what to do."""

    def __init__(self, prompt_path: Path, reply_path: Path, timeout: float) -> None:
        self.prompt_path = Path(prompt_path)
        self.reply_path = Path(reply_path)
        self.timeout = timeout
        super().__init__(
            f"no reply at {self.reply_path} after waiting {timeout:g}s "
            f"(prompt saved at {self.prompt_path}); paste the model reply into the reply file and run again"
        )


class ManualAdapter(LLMAdapter):
    name = "manual"

    def __init__(self, options: Mapping[str, Any] | None = None) -> None:
        super().__init__(options)
        self.directory = Path(str(self.options.get("directory", ".manual")))
        self.timeout = float(self.options.get("timeout", 3600))
        self.poll_interval = float(self.options.get("poll_interval", 2.0))
        self.prefix = str(self.options.get("prefix", ""))
        #: (prompt_path, reply_path) of the most recent exchange, set before waiting.
        self.last_paths: tuple[Path, Path] | None = None

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model_tier: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        prompt_path, reply_path = self._next_paths()
        self.last_paths = (prompt_path, reply_path)
        prompt_path.write_text(self._prompt_text(prompt, system), encoding="utf-8")

        deadline = time.monotonic() + max(self.timeout, 0.0)
        while True:
            reply = self._read_reply(reply_path)
            if reply is not None:
                return reply
            if time.monotonic() >= deadline:
                raise ManualPending(prompt_path, reply_path, self.timeout)
            time.sleep(self.poll_interval)

    def describe(self) -> dict[str, Any]:
        return {**super().describe(), "directory": str(self.directory)}

    def _next_paths(self) -> tuple[Path, Path]:
        self.directory.mkdir(parents=True, exist_ok=True)
        index = sum(1 for _ in self.directory.glob("*.prompt.md")) + 1
        stem = f"{self.prefix}{index:04d}"
        return self.directory / f"{stem}.prompt.md", self.directory / f"{stem}.reply.md"

    @staticmethod
    def _prompt_text(prompt: str, system: str | None) -> str:
        body = prompt if system is None else f"SYSTEM:\n{system}\n\nPROMPT:\n{prompt}"
        return body if body.endswith("\n") else body + "\n"

    @staticmethod
    def _read_reply(reply_path: Path) -> str | None:
        if not reply_path.is_file():
            return None
        text = reply_path.read_text(encoding="utf-8").strip()
        return text or None
