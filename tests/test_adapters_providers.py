"""M6c: planner, writer and checker may each have their own provider.

The config keeps one `openai_compatible` adapter, but `options.providers` overrides base_url,
model and api_key_env per tier, because Gemini, Groq and OpenRouter all expose OpenAI-shaped
endpoints.
"""

from __future__ import annotations

import pytest

from pipeline import runner
from pipeline.adapters.base import AdapterError
from pipeline.adapters.tiered import TieredLLMAdapter


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text="", headers=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.headers = headers or {}

    def json(self):
        return self._payload


def write_config(root, text):
    (root / "config.yaml").write_text(text, encoding="utf-8")


def base_config(providers: str, *, base_model: bool = True) -> str:
    model_line = "      model: default/model\n" if base_model else ""
    return (
        "seed: 1\n"
        "chaos_dial: 1\n"
        "adapters:\n"
        "  llm:\n"
        "    type: openai_compatible\n"
        "    options:\n"
        "      base_url: https://openrouter.ai/api/v1\n"
        f"{model_line}"
        "      api_key_env: OPENROUTER_KEY\n"
        "      providers:\n"
        f"{providers}"
    )


PLANNER = (
    "        planner:\n"
    "          base_url: https://generativelanguage.googleapis.com/v1beta/openai\n"
    "          model: gemini-2.0-flash\n"
    "          api_key_env: GEMINI_KEY\n"
)
WRITER = (
    "        writer:\n"
    "          base_url: https://api.groq.com/openai/v1\n"
    "          model: llama-3.3-70b-versatile\n"
    "          api_key_env: GROQ_KEY\n"
)
CHECKER = (
    "        checker:\n"
    "          model: small/checker\n"
    "          api_key_env: OPENROUTER_KEY\n"
)


def install_post(monkeypatch):
    calls = []

    def post(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return FakeResponse(200, {"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr("pipeline.adapters.openai_compatible.requests.post", post)
    return calls


def test_each_tier_uses_its_own_base_url_model_and_key(tmp_path, monkeypatch):
    for name in ("GEMINI_KEY", "GROQ_KEY", "OPENROUTER_KEY"):
        monkeypatch.setenv(name, f"{name.lower()}-value")
    write_config(tmp_path, base_config(PLANNER + WRITER + CHECKER, base_model=False))
    calls = install_post(monkeypatch)

    adapter = runner.load_llm_adapter(runner.load_config(tmp_path))
    assert isinstance(adapter, TieredLLMAdapter)

    adapter.complete("plan", model_tier="planner")
    adapter.complete("write", model_tier="writer")
    adapter.complete("check", model_tier="checker")

    assert [call["url"] for call in calls] == [
        "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "https://api.groq.com/openai/v1/chat/completions",
        "https://openrouter.ai/api/v1/chat/completions",
    ]
    assert [call["json"]["model"] for call in calls] == [
        "gemini-2.0-flash",
        "llama-3.3-70b-versatile",
        "small/checker",
    ]
    assert [call["headers"]["Authorization"] for call in calls] == [
        "Bearer gemini_key-value",
        "Bearer groq_key-value",
        "Bearer openrouter_key-value",
    ]


def test_a_tier_without_a_provider_falls_back_to_the_default(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_KEY", "g")
    monkeypatch.setenv("OPENROUTER_KEY", "o")
    write_config(tmp_path, base_config(PLANNER))
    calls = install_post(monkeypatch)

    adapter = runner.load_llm_adapter(runner.load_config(tmp_path))
    adapter.complete("plan", model_tier="planner")
    adapter.complete("check", model_tier="checker")

    assert calls[0]["url"].startswith("https://generativelanguage.googleapis.com")
    assert calls[0]["json"]["model"] == "gemini-2.0-flash"
    assert calls[1]["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert calls[1]["json"]["model"] == "default/model"


def test_a_missing_key_names_the_tiers_own_environment_variable(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_KEY", "o")
    monkeypatch.delenv("GROQ_KEY", raising=False)
    write_config(tmp_path, base_config(WRITER))
    install_post(monkeypatch)

    adapter = runner.load_llm_adapter(runner.load_config(tmp_path))

    with pytest.raises(AdapterError) as excinfo:
        adapter.complete("write", model_tier="writer")

    assert "GROQ_KEY" in str(excinfo.value)


def test_describe_lists_the_providers_without_secrets(tmp_path, monkeypatch):
    for name in ("GEMINI_KEY", "GROQ_KEY", "OPENROUTER_KEY"):
        monkeypatch.setenv(name, f"{name.lower()}-secret")
    write_config(tmp_path, base_config(PLANNER + WRITER + CHECKER, base_model=False))

    described = runner.load_llm_adapter(runner.load_config(tmp_path)).describe()

    assert described["adapter"] == "openai_compatible"
    assert described["tiers"]["planner"]["base_url"].startswith("https://generativelanguage")
    assert described["tiers"]["planner"]["model"] == "gemini-2.0-flash"
    assert described["tiers"]["writer"]["api_key_env"] == "GROQ_KEY"
    assert "secret" not in repr(described)


def test_an_unknown_tier_name_is_a_config_error(tmp_path):
    write_config(
        tmp_path,
        base_config(
            "        narrator:\n"
            "          base_url: https://example.test/v1\n"
            "          model: m\n"
            "          api_key_env: KEY\n"
        ),
    )

    with pytest.raises(runner.StoryError) as excinfo:
        runner.load_llm_adapter(runner.load_config(tmp_path))

    assert "narrator" in str(excinfo.value)


def test_providers_are_only_for_openai_compatible_configs(tmp_path):
    write_config(
        tmp_path,
        "seed: 1\nchaos_dial: 1\nadapters:\n  llm:\n    type: echo\n    options:\n"
        "      providers:\n        writer: {}\n",
    )

    with pytest.raises(runner.StoryError):
        runner.load_llm_adapter(runner.load_config(tmp_path))
