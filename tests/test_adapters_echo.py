"""M1: the echo adapter returns a fixed string and is selectable by name."""

from __future__ import annotations

import pytest

from pipeline.adapters import create_llm_adapter
from pipeline.adapters.base import AdapterError, LLMAdapter
from pipeline.adapters.echo import EchoAdapter


def test_echo_returns_a_fixed_string():
    assert EchoAdapter().complete("Write chapter one.") == "echo"


def test_echo_response_is_configurable():
    adapter = EchoAdapter({"response": "A fixed answer."})
    assert adapter.complete("anything at all") == "A fixed answer."


def test_echo_records_every_call():
    adapter = EchoAdapter()
    adapter.complete("one", system="sys", model_tier="writer", max_tokens=50)
    adapter.complete("two")

    assert [call["prompt"] for call in adapter.calls] == ["one", "two"]
    assert adapter.calls[0]["system"] == "sys"
    assert adapter.calls[0]["model_tier"] == "writer"
    assert adapter.calls[0]["max_tokens"] == 50


def test_echo_is_an_llm_adapter():
    assert isinstance(EchoAdapter(), LLMAdapter)


def test_echo_describe_names_the_adapter():
    assert EchoAdapter().describe()["adapter"] == "echo"


def test_factory_builds_the_echo_adapter():
    assert isinstance(create_llm_adapter("echo"), EchoAdapter)


def test_factory_rejects_an_unknown_adapter_type():
    with pytest.raises(AdapterError):
        create_llm_adapter("telepathy")
