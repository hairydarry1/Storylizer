"""Planner doubles for the model-authored stages 11 and 12.

Each one is an `EchoAdapter` that reads the constraint block out of the prompt and answers
with JSON, so the tests exercise the real prompt, the real checks and the real retry loop.
"""

from __future__ import annotations

import json
import random
from typing import Any

from pipeline.adapters.echo import EchoAdapter

#: Distinct words that make each faked chapter's text genuinely different from the last one,
#: so the near-duplicate check is exercised on purpose rather than by accident.
FLAVOUR = (
    "river", "ledger", "sluice", "lantern", "salt", "rope", "tin", "varnish",
    "crane", "wool", "ink", "brass", "flour", "nails", "chalk", "glass",
    "oakum", "peat", "tallow", "copper", "brick", "canvas", "grit", "honey",
    "loom", "marrow", "onion", "pitch", "resin", "sail", "twine", "wax",
    "ashes", "bell", "cinder", "drift", "ember", "fog", "grind", "hollow",
    "iron", "juniper", "keel", "loam", "moss", "nettle", "ochre", "plum",
)


def flavour(number: int, count: int = 6) -> str:
    return " ".join(random.Random(number).sample(FLAVOUR, count))


def constraint_block(prompt: str, header: str) -> dict[str, Any]:
    tail = prompt.split(header, 1)[1]
    return json.loads(tail.split("```json", 1)[1].split("```", 1)[0])


class ChapterWriter(EchoAdapter):
    """A planner that answers every chapter prompt with a schema-valid chapter."""

    def __init__(self, *, phrase: str = "") -> None:
        super().__init__({})
        self.phrase = phrase

    def payload(self, data: dict[str, Any]) -> dict[str, Any]:
        number = data["number"]
        protagonist = data["protagonist"]
        closing = data.get("closing_actor") or protagonist
        actor = data["actor"]
        imagery = data["imagery"]
        detail = flavour(number)
        return {
            "title": f"Model chapter {number}",
            "hook": f"Hook {number}: {imagery} at dawn over {detail}{self.phrase}",
            "beats": [
                {
                    "actor": actor,
                    "action": f"{number}: {actor} opens the day among {imagery}, carrying {detail}",
                    "obstacle": f"the count in {imagery} is wrong about the {detail}",
                    "outcome": "the plan slips before it starts",
                },
                {
                    "actor": protagonist,
                    "action": f"{number}: {protagonist} asks for the record of {imagery} and the {detail}",
                    "obstacle": f"the clerk prices {detail} out of reach",
                    "outcome": "the price is accepted",
                },
                {
                    "actor": closing,
                    "action": f"{number}: {closing} chooses in front of the witnesses of {imagery}",
                    "obstacle": f"the choice costs {detail} and more",
                    "outcome": f"she pays it and keeps {detail}",
                },
            ],
            "ends_on": f"Ends {number}: the record of {imagery} is still sealed",
        }

    def complete(self, prompt, **kwargs):
        super().complete(prompt, **kwargs)
        data = constraint_block(prompt, "## Chapter constraints")
        return json.dumps(self.payload(data))


class RepeatedChapterWriter(ChapterWriter):
    """Always the same beats, so chapter 2 repeats chapter 1."""

    def payload(self, data):
        return {
            "title": "The same chapter",
            "hook": "The same hook",
            "beats": [
                {
                    "actor": data["protagonist"],
                    "action": "The protagonist asks for the record",
                    "obstacle": "the answer is priced",
                    "outcome": "the price is accepted",
                },
                {
                    "actor": data["protagonist"],
                    "action": "The protagonist chooses in front of witnesses",
                    "obstacle": "the choice costs what she cannot spare",
                    "outcome": "she pays it and keeps the record",
                },
                {
                    "actor": data.get("closing_actor") or data["protagonist"],
                    "action": "The protagonist signs the entry anyway",
                    "obstacle": "the ink is a witness",
                    "outcome": "the record is sealed",
                },
            ],
            "ends_on": "The same ending",
        }


class ShortChapterWriter(ChapterWriter):
    """Two beats, one short of the minimum."""

    def payload(self, data):
        payload = super().payload(data)
        payload["beats"] = payload["beats"][:2]
        return payload


class BadActorWriter(ChapterWriter):
    """A beat naming someone who is not in the cast."""

    def payload(self, data):
        payload = super().payload(data)
        payload["beats"][0]["actor"] = "nobody"
        return payload


class IgnoringClosingActorWriter(ChapterWriter):
    """Ends every chapter with the protagonist, whatever closing actor was assigned."""

    def payload(self, data):
        payload = super().payload(data)
        payload["beats"][-1]["actor"] = data["protagonist"]
        return payload


class FailAtChapterWriter(ChapterWriter):
    """Invalid reply from one chapter on, so a run stops with a partial file worth resuming."""

    def __init__(self, fail_at: int) -> None:
        super().__init__()
        self.fail_at = fail_at

    def complete(self, prompt, **kwargs):
        EchoAdapter.complete(self, prompt, **kwargs)
        data = constraint_block(prompt, "## Chapter constraints")
        if data["number"] == self.fail_at:
            return "no JSON today"
        return json.dumps(self.payload(data))


class SceneWriter(EchoAdapter):
    """A planner that answers every scene prompt with the requested number of scenes."""

    def __init__(
        self,
        *,
        phrase: str = "",
        short: bool = False,
        repeat: bool = False,
        fail_at: int | None = None,
    ) -> None:
        super().__init__({})
        self.phrase = phrase
        self.short = short
        self.repeat = repeat
        self.fail_at = fail_at

    def complete(self, prompt, **kwargs):
        super().complete(prompt, **kwargs)
        data = constraint_block(prompt, "## Scene constraints")
        if self.fail_at is not None and data["number"] == self.fail_at:
            return "no JSON today"
        number = data["number"]
        count = int(data["scenes"]) - (1 if self.short else 0)
        tag = "same" if self.repeat else f"ch{number}"
        seeds = [index if self.repeat else number * 10 + index for index in range(count)]
        scenes = [
            {
                "goal": f"{tag} scene {index + 1}: get the ledger and {flavour(seeds[index], 4)}{self.phrase}",
                "conflict": f"{tag} scene {index + 1}: the clerk stalls over {flavour(seeds[index] + 1000, 4)}",
                "turn": f"{tag} scene {index + 1}: the price rises on {flavour(seeds[index] + 2000, 4)}",
            }
            for index in range(count)
        ]
        return json.dumps({"scenes": scenes})
