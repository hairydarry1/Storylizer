"""M6c: the openai_compatible adapter survives rate limits and provider hiccups.

429 and 5xx responses are retried with exponential backoff, `Retry-After` wins over the
backoff, and the rate-limit headers that providers send are kept for the caller.
"""

from __future__ import annotations

import pytest

from pipeline.adapters.base import AdapterError
from pipeline.adapters.openai_compatible import OpenAICompatibleAdapter

QUOTA_HEADERS = {
    "x-ratelimit-remaining-requests": "9",
    "x-ratelimit-remaining-tokens": "120000",
    "x-ratelimit-reset-requests": "1s",
}


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text="", headers=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {
            "choices": [{"message": {"content": "Chapter text."}}]
        }
        self.text = text
        self.headers = dict(headers or {})

    def json(self):
        return self._payload


def make_adapter(*, responses, **options):
    """An adapter whose calls replay `responses` (status, headers) and record sleeps."""
    calls = []
    sleeps = []
    queue = list(responses)

    def post(url, **kwargs):
        calls.append({"url": url, **kwargs})
        status, headers = queue.pop(0)
        if status == 200:
            return FakeResponse(200, headers=headers)
        return FakeResponse(status, text=f"upstream said {status}", headers=headers)

    options.setdefault("base_url", "https://openrouter.ai/api/v1")
    options.setdefault("model", "some/model")
    options.setdefault("api_key_env", "STORY_TEST_KEY")
    options.setdefault("backoff", 2.0)
    options["post"] = post
    options["sleep"] = sleeps.append
    return OpenAICompatibleAdapter(options), calls, sleeps


@pytest.fixture(autouse=True)
def api_key(monkeypatch):
    monkeypatch.setenv("STORY_TEST_KEY", "secret")


def test_a_429_is_retried_after_the_backoff():
    adapter, calls, sleeps = make_adapter(responses=[(429, QUOTA_HEADERS), (200, {})])

    assert adapter.complete("hi") == "Chapter text."

    assert len(calls) == 2
    assert sleeps == [2.0]


def test_a_5xx_is_retried_with_exponential_backoff():
    adapter, calls, sleeps = make_adapter(responses=[(503, {}), (502, {}), (200, {})])

    assert adapter.complete("hi") == "Chapter text."

    assert len(calls) == 3
    assert sleeps == [2.0, 4.0]


def test_retry_after_seconds_wins_over_the_backoff():
    adapter, calls, sleeps = make_adapter(
        responses=[(429, {"Retry-After": "7"}), (200, {})]
    )

    adapter.complete("hi")

    assert sleeps == [7.0]


def test_retry_after_http_date_is_honoured():
    adapter, calls, sleeps = make_adapter(
        responses=[(429, {"retry-after": "Wed, 21 Oct 2015 07:28:00 GMT"}), (200, {})],
        now=lambda: 1445412479.0,  # one second before the stated date
    )

    adapter.complete("hi")

    assert sleeps == [1.0]


def test_a_persistent_5xx_fails_after_the_last_retry():
    adapter, calls, sleeps = make_adapter(
        responses=[(500, QUOTA_HEADERS), (500, QUOTA_HEADERS), (500, QUOTA_HEADERS)]
    )

    with pytest.raises(AdapterError) as excinfo:
        adapter.complete("hi")

    assert len(calls) == 3
    assert sleeps == [2.0, 4.0]
    assert "500" in str(excinfo.value)
    assert "x-ratelimit-remaining-requests=9" in str(excinfo.value)


def test_a_401_is_not_retried():
    adapter, calls, sleeps = make_adapter(responses=[(401, {})])

    with pytest.raises(AdapterError) as excinfo:
        adapter.complete("hi")

    assert len(calls) == 1
    assert sleeps == []
    assert "401" in str(excinfo.value)


def test_remaining_quota_headers_are_surfaced_on_success():
    adapter, _, _ = make_adapter(responses=[(200, QUOTA_HEADERS)])

    adapter.complete("hi")

    assert adapter.last_quota == {
        "x-ratelimit-remaining-requests": "9",
        "x-ratelimit-remaining-tokens": "120000",
        "x-ratelimit-reset-requests": "1s",
    }


def test_no_quota_headers_means_no_quota_report():
    adapter, _, _ = make_adapter(responses=[(200, {})])

    adapter.complete("hi")

    assert adapter.last_quota is None


def test_retries_can_be_configured():
    adapter, calls, sleeps = make_adapter(responses=[(429, {}), (429, {})], retries=1)

    with pytest.raises(AdapterError):
        adapter.complete("hi")

    assert len(calls) == 2
    assert sleeps == [2.0]


def test_the_backoff_wait_is_capped():
    adapter, calls, sleeps = make_adapter(
        responses=[(429, {"Retry-After": "900"}), (200, {})], max_backoff=30
    )

    adapter.complete("hi")

    assert sleeps == [30.0]
