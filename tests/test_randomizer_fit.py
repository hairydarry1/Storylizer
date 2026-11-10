"""M2: the fit check asks a checker-tier model to accept, adapt or reject each roll."""

from __future__ import annotations

import json
import re

import pytest

from pipeline import randomizer, runner
from pipeline.adapters.echo import EchoAdapter


def make(workspace):
    return randomizer.Randomizer(workspace, "demo", runner.load_config(workspace))


def echo(payload):
    return EchoAdapter({"response": json.dumps(payload)})


def decisions(*items):
    return {"decisions": [{"key": key, "verdict": verdict, "reason": reason} for key, verdict, reason in items]}


def rolls_for(root):
    return json.loads((root / "projects" / "demo" / "rolls.json").read_text(encoding="utf-8"))["rolls"]


def test_the_fit_check_uses_the_checker_tier_and_names_the_rolls(workspace):
    rnd = make(workspace)
    rolls = rnd.roll_stage(8).rolls
    llm = echo(decisions(*[(r.key, "accept", "fits") for r in rolls]))

    report = randomizer.fit_rolls(llm, rolls)

    assert len(llm.calls) == 1
    assert llm.calls[0]["model_tier"] == "checker"
    prompt = llm.calls[0]["prompt"]
    assert "08-character_creation" in prompt
    assert rolls[0].key in prompt and rolls[0].value in prompt
    assert {key: d.verdict for key, d in report.decisions.items()} == {
        roll.key: "accept" for roll in rolls
    }


def test_accepted_rolls_are_not_rerolled(workspace):
    rnd = make(workspace)
    rolls = rnd.roll_stage(8).rolls
    llm = echo(decisions(*[(r.key, "accept", "fits") for r in rolls]))
    before = {r.key: r.value for r in rolls}

    result = rnd.roll_stage(8, llm=llm)

    assert {r.key: r.value for r in result.rolls} == before
    assert result.fit is not None
    assert result.fit.rerolled == []
    assert len(rolls_for(workspace)) == len(before)


def test_adapted_rolls_keep_their_value_and_carry_the_reason(workspace):
    rnd = make(workspace)
    rolls = rnd.roll_stage(8).rolls
    payload = decisions(*[(r.key, "adapt", "soften the wording") for r in rolls])
    before = {r.key: r.value for r in rolls}

    result = rnd.roll_stage(8, llm=echo(payload))

    assert {r.key: r.value for r in result.rolls} == before
    assert result.fit.decisions["flaw"].verdict == "adapt"
    assert result.fit.decisions["flaw"].reason == "soften the wording"


def test_a_rejected_roll_is_rerolled_until_the_checker_accepts(workspace):
    rnd = make(workspace)
    rolls = rnd.roll_stage(8).rolls
    reasons = {}

    class PickyChecker(EchoAdapter):
        """Rejects the original flaw, then accepts whatever value it sees."""

        def complete(self, prompt, **kwargs):
            values = {key: value for key, _table, value in re.findall(r"^\s*(\S+)\s*\|\s*(\S+)\s*\|\s*(.+)$", prompt, re.M)}
            self.calls.append({"prompt": prompt, **kwargs})
            if values.get("flaw") == rejected:
                return json.dumps({"decisions": [{"key": "flaw", "verdict": "reject", "reason": "too bleak"}]})
            return json.dumps(decisions(*[(k, "accept", "fits") for k in values]))

    rejected = {r.key: r.value for r in rolls}["flaw"]
    llm = PickyChecker({"response": "unused"})

    result = rnd.roll_stage(8, llm=llm)

    assert result.fit.rerolled == ["flaw"]
    assert {r.key: r.value for r in result.rolls}["flaw"] != rejected
    assert result.fit.decisions["flaw"].verdict == "accept"
    flaw_records = [r for r in rolls_for(workspace) if r["key"] == "flaw"]
    assert len(flaw_records) == 2


def test_a_stubborn_rejection_stops_after_three_rerolls(workspace):
    rnd = make(workspace)
    rolls = rnd.roll_stage(8).rolls
    before = {r.key: r.value for r in rolls}
    llm = echo(decisions(*[(r.key, "reject", "no good") for r in rolls]))

    result = rnd.roll_stage(8, llm=llm)

    assert set(result.fit.rerolled) == set(before)
    assert result.fit.decisions["flaw"].verdict == "reject"
    assert any("3" in note for note in result.fit.notes)
    flaw_records = [r for r in rolls_for(workspace) if r["key"] == "flaw"]
    assert len(flaw_records) == 1 + randomizer.MAX_FIT_REROLLS


def test_a_reply_that_is_not_json_raises_a_fit_check_error(workspace):
    rnd = make(workspace)
    rolls = rnd.roll_stage(8).rolls

    with pytest.raises(randomizer.FitCheckError, match="JSON"):
        randomizer.fit_rolls(EchoAdapter(), rolls)


def test_a_reply_with_code_fences_is_still_read(workspace):
    rnd = make(workspace)
    rolls = rnd.roll_stage(8).rolls
    fenced = "```json\n" + json.dumps(decisions(*[(r.key, "accept", "fine") for r in rolls])) + "\n```"

    report = randomizer.fit_rolls(EchoAdapter({"response": fenced}), rolls)

    assert all(d.verdict == "accept" for d in report.decisions.values())


def test_missing_verdicts_default_to_accept(workspace):
    rnd = make(workspace)
    rolls = rnd.roll_stage(8).rolls

    report = randomizer.fit_rolls(echo(decisions(("flaw", "accept", "fine"))), rolls)

    assert report.decisions["flaw"].verdict == "accept"
    assert report.decisions["quirk"].verdict == "accept"
