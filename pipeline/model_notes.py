"""Ask the model for prose, or keep the deterministic text.

Every M6 stage writes its structure in code and treats the model as an optional prose layer.
A model that returns nothing, the `echo` adapter, or an error is a note, never a failure.
"""

from __future__ import annotations

from typing import Any


def prose(
    llm: Any,
    skill: Any,
    prompt: str,
    notes: list[str],
    *,
    max_tokens: int = 2500,
) -> str:
    """The model's prose for a stage, or '' plus a note explaining why there is none."""
    try:
        reply = llm.complete(
            prompt,
            system=skill.sections["Purpose"],
            model_tier=skill.model_tier,
            max_tokens=max_tokens,
        )
    except Exception as exc:  # the deterministic sections still stand
        notes.append(f"model call failed: {exc}")
        return ""
    text = (reply or "").strip()
    if not text or text.casefold() == "echo":
        notes.append("model returned no prose (echo adapter); deterministic sections stand")
        return ""
    return text
