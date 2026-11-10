"""M1: the openai_compatible adapter builds a chat request without touching the network."""

from __future__ import annotations

import pytest

from pipeline.adapters.base import AdapterError
from pipeline.adapters.openai_compatible import OpenAICompatibleAdapter


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def make_adapter(**options):
    calls = []

    def post(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return FakeResponse(200, {"choices": [{"message": {"content": "  Chapter text.  "}}]})

    options.setdefault("base_url", "https://openrouter.ai/api/v1")
    options.setdefault("model", "some/model")
    options.setdefault("api_key_env", "STORY_TEST_KEY")
    options["post"] = post
    return OpenAICompatibleAdapter(options), calls


def test_complete_returns_stripped_text_and_calls_chat_completions(monkeypatch):
    monkeypatch.setenv("STORY_TEST_KEY", "secret-value")
    adapter, calls = make_adapter()

    assert adapter.complete("Write chapter one.", system="You are a novelist.") == "Chapter text."

    call = calls[0]
    assert call["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer secret-value"
    assert call["json"]["model"] == "some/model"
    assert call["json"]["messages"] == [
        {"role": "system", "content": "You are a novelist."},
        {"role": "user", "content": "Write chapter one."},
    ]
    assert call["timeout"] == 120


def test_trailing_slash_in_base_url_is_handled(monkeypatch):
    monkeypatch.setenv("STORY_TEST_KEY", "k")
    adapter, calls = make_adapter(base_url="https://example.test/v1/")

    adapter.complete("hi")

    assert calls[0]["url"] == "https://example.test/v1/chat/completions"


def test_model_tier_mapping_overrides_the_default_model(monkeypatch):
    monkeypatch.setenv("STORY_TEST_KEY", "k")
    adapter, calls = make_adapter(models={"writer": "big/writer-model", "checker": "small/checker"})

    adapter.complete("write", model_tier="writer")
    adapter.complete("check", model_tier="checker")
    adapter.complete("plan", model_tier="planner")

    assert [c["json"]["model"] for c in calls] == ["big/writer-model", "small/checker", "some/model"]


def test_max_tokens_is_forwarded(monkeypatch):
    monkeypatch.setenv("STORY_TEST_KEY", "k")
    adapter, calls = make_adapter()

    adapter.complete("hi", max_tokens=256)

    assert calls[0]["json"]["max_tokens"] == 256


def test_missing_api_key_env_var_is_an_adapter_error(monkeypatch, tmp_path):
    monkeypatch.delenv("STORY_TEST_KEY", raising=False)
    adapter, calls = make_adapter()

    with pytest.raises(AdapterError) as excinfo:
        adapter.complete("hi")

    assert "STORY_TEST_KEY" in str(excinfo.value)
    assert calls == []


def test_http_error_is_an_adapter_error(monkeypatch):
    monkeypatch.setenv("STORY_TEST_KEY", "k")

    def post(url, **kwargs):
        return FakeResponse(401, {"error": "bad key"}, text='{"error": "bad key"}')

    adapter = OpenAICompatibleAdapter(
        {"base_url": "https://example.test/v1", "model": "m", "api_key_env": "STORY_TEST_KEY", "post": post}
    )

    with pytest.raises(AdapterError) as excinfo:
        adapter.complete("hi")

    assert "401" in str(excinfo.value)


def test_response_without_choices_is_an_adapter_error(monkeypatch):
    monkeypatch.setenv("STORY_TEST_KEY", "k")

    adapter = OpenAICompatibleAdapter(
        {
            "base_url": "https://example.test/v1",
            "model": "m",
            "api_key_env": "STORY_TEST_KEY",
            "post": lambda url, **kwargs: FakeResponse(200, {"error": "nope"}),
        }
    )

    with pytest.raises(AdapterError):
        adapter.complete("hi")


def test_non_json_response_is_an_adapter_error(monkeypatch):
    monkeypatch.setenv("STORY_TEST_KEY", "k")

    adapter = OpenAICompatibleAdapter(
        {
            "base_url": "https://example.test/v1",
            "model": "m",
            "api_key_env": "STORY_TEST_KEY",
            "post": lambda url, **kwargs: FakeResponse(200, None, text="<html>"),
        }
    )

    with pytest.raises(AdapterError):
        adapter.complete("hi")


def test_model_is_required_at_construction():
    with pytest.raises(AdapterError):
        OpenAICompatibleAdapter({"base_url": "https://example.test/v1"})


def test_describe_never_exposes_the_api_key(monkeypatch):
    monkeypatch.setenv("STORY_TEST_KEY", "secret-value")
    adapter, _ = make_adapter()

    described = adapter.describe()

    assert described["adapter"] == "openai_compatible"
    assert described["base_url"] == "https://openrouter.ai/api/v1"
    assert "secret-value" not in repr(described)
    assert "secret-value" not in repr(adapter.options)
