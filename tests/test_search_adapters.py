"""M4: the search adapter interface and its four implementations.

No test talks to the network: Wikipedia gets a fake `get` and generic_json a fake
`request`, which is also how a user can exercise them without burning API quota.
"""

from __future__ import annotations

import json

import pytest

from pipeline.adapters import AdapterError, SearchResult, create_search_adapter
from pipeline.adapters.generic_json import GenericJSONSearchAdapter
from pipeline.adapters.manual_search import ManualSearchAdapter, SearchPending
from pipeline.adapters.stub_search import StubSearchAdapter
from pipeline.adapters.wikipedia import WikipediaAdapter


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload) if not isinstance(payload, str) else payload

    def json(self):
        if isinstance(self.payload, str):
            raise ValueError("not json")
        return self.payload


def test_the_registry_builds_every_search_adapter():
    assert isinstance(create_search_adapter("stub"), StubSearchAdapter)
    assert isinstance(create_search_adapter("manual", {"directory": ".x"}), ManualSearchAdapter)
    assert isinstance(create_search_adapter("wikipedia"), WikipediaAdapter)
    assert isinstance(
        create_search_adapter(
            "generic_json", {"base_url": "https://example.test/search", "api_key_env": "X_KEY"}
        ),
        GenericJSONSearchAdapter,
    )


def test_an_unknown_search_adapter_is_a_clear_error():
    with pytest.raises(AdapterError, match="unknown search adapter"):
        create_search_adapter("no-such-search")


def test_the_stub_records_queries_and_returns_canned_results():
    adapter = StubSearchAdapter(
        {
            "results": [
                {"title": "Comparable", "url": "https://example.com/a", "snippet": "a snippet"},
                {"title": "Another", "url": "https://example.com/b", "snippet": "another"},
            ]
        }
    )

    results = adapter.search("ledger mystery", max_results=1)

    assert adapter.calls == ["ledger mystery"]
    assert results == [SearchResult("Comparable", "https://example.com/a", "a snippet")]


def test_the_stub_can_answer_different_queries_differently():
    adapter = StubSearchAdapter(
        {
            "results": [],
            "by_query": {
                "market": [{"title": "Market book", "url": "https://example.com/m", "snippet": "m"}]
            },
        }
    )

    assert adapter.search("market")[0].title == "Market book"
    assert adapter.search("other") == []


def test_search_results_never_include_amazon():
    adapter = StubSearchAdapter(
        {
            "results": [
                {"title": "Amazon listing", "url": "https://www.amazon.com/dp/123", "snippet": "buy"},
                {"title": "UK listing", "url": "https://amazon.co.uk/dp/123", "snippet": "buy"},
                {"title": "Short link", "url": "https://amzn.to/abc", "snippet": "buy"},
                {"title": "Review", "url": "https://example.com/review", "snippet": "read"},
            ]
        }
    )

    results = adapter.search("anything")

    assert [result.title for result in results] == ["Review"]


def test_manual_search_writes_the_query_and_reads_pasted_results(tmp_path):
    adapter = ManualSearchAdapter({"directory": str(tmp_path), "timeout": 0})
    (tmp_path / "0001.results.json").write_text(
        json.dumps(
            {
                "results": [
                    {"title": "Pasted", "url": "https://example.com/p", "snippet": "pasted snippet"}
                ]
            }
        ),
        encoding="utf-8",
    )

    results = adapter.search("cozy mystery comparables")

    assert results == [SearchResult("Pasted", "https://example.com/p", "pasted snippet")]
    query_path, results_path = adapter.last_paths
    assert query_path.name == "0001.query.md"
    assert results_path.name == "0001.results.json"
    assert "cozy mystery comparables" in query_path.read_text(encoding="utf-8")


def test_manual_search_timeout_leaves_the_query_on_disk(tmp_path):
    adapter = ManualSearchAdapter({"directory": str(tmp_path), "timeout": 0})

    with pytest.raises(SearchPending) as excinfo:
        adapter.search("setting details")

    pending = excinfo.value
    assert pending.query_path.exists()
    assert "setting details" in pending.query_path.read_text(encoding="utf-8")
    assert str(pending.results_path) in str(pending)


def test_manual_search_accepts_pipe_separated_lines(tmp_path):
    adapter = ManualSearchAdapter({"directory": str(tmp_path), "timeout": 0})
    (tmp_path / "0001.results.json").write_text(
        "Some Title | https://example.com/t | a short snippet\n", encoding="utf-8"
    )

    assert adapter.search("q") == [SearchResult("Some Title", "https://example.com/t", "a short snippet")]


def test_manual_search_rejects_an_empty_or_broken_results_file(tmp_path):
    adapter = ManualSearchAdapter({"directory": str(tmp_path), "timeout": 0})
    (tmp_path / "0001.results.json").write_text("not json and no pipes", encoding="utf-8")

    with pytest.raises(AdapterError, match="results"):
        adapter.search("q")


def test_wikipedia_uses_the_mediawiki_api_and_strips_html():
    calls = {}

    def fake_get(url, **kwargs):
        calls["url"] = url
        calls["params"] = kwargs["params"]
        calls["headers"] = kwargs.get("headers", {})
        return FakeResponse(
            {
                "query": {
                    "search": [
                        {
                            "title": "Lighthouse keeper",
                            "snippet": 'A <span class="searchmatch">keeper</span> &amp; his log.',
                        }
                    ]
                }
            }
        )

    adapter = WikipediaAdapter({"get": fake_get})
    results = adapter.search("lighthouse keeper", max_results=3)

    assert calls["params"]["action"] == "query"
    assert calls["params"]["list"] == "search"
    assert calls["params"]["srsearch"] == "lighthouse keeper"
    assert calls["params"]["srlimit"] == 3
    assert "User-Agent" in calls["headers"]
    assert results == [
        SearchResult(
            "Lighthouse keeper",
            "https://en.wikipedia.org/wiki/Lighthouse_keeper",
            "A keeper & his log.",
        )
    ]


def test_wikipedia_handles_a_missing_query_block_and_http_errors():
    assert WikipediaAdapter({"get": lambda *a, **k: FakeResponse({})}).search("nothing") == []

    def failing_get(*args, **kwargs):
        return FakeResponse("upstream is down", status_code=503)

    with pytest.raises(AdapterError, match="wikipedia"):
        WikipediaAdapter({"get": failing_get}).search("anything")


def test_generic_json_reads_the_key_from_the_environment_and_maps_brave_fields(monkeypatch):
    monkeypatch.setenv("BRAVE_API_KEY", "secret-value")
    calls = {}

    def fake_request(method, url, **kwargs):
        calls.update({"method": method, "url": url, **kwargs})
        return FakeResponse(
            {
                "web": {
                    "results": [
                        {
                            "title": "A comparable",
                            "url": "https://example.com/a",
                            "description": "short description",
                        }
                    ]
                }
            }
        )

    adapter = GenericJSONSearchAdapter(
        {
            "base_url": "https://api.search.brave.com/res/v1/web/search",
            "api_key_env": "BRAVE_API_KEY",
            "api_key_header": "X-Subscription-Token",
            "results_path": "web.results",
            "fields": {"title": "title", "url": "url", "snippet": "description"},
            "request": fake_request,
        }
    )

    results = adapter.search("ledger mystery", max_results=4)

    assert results == [
        SearchResult("A comparable", "https://example.com/a", "short description")
    ]
    assert calls["method"] == "GET"
    assert calls["params"]["q"] == "ledger mystery"
    assert calls["params"]["count"] == 4
    assert calls["headers"]["X-Subscription-Token"] == "secret-value"
    assert "secret-value" not in json.dumps(adapter.describe())


def test_generic_json_can_post_the_key_in_the_body_for_tavily(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tavily-secret")
    calls = {}

    def fake_request(method, url, **kwargs):
        calls.update({"method": method, **kwargs})
        return FakeResponse(
            {
                "results": [
                    {
                        "title": "Tavily result",
                        "url": "https://example.com/t",
                        "content": "longer content",
                    }
                ]
            }
        )

    adapter = GenericJSONSearchAdapter(
        {
            "base_url": "https://api.tavily.com/search",
            "api_key_env": "TAVILY_API_KEY",
            "method": "POST",
            "auth": "body",
            "api_key_field": "api_key",
            "query_param": "query",
            "max_results_param": "max_results",
            "results_path": "results",
            "fields": {"title": "title", "url": "url", "snippet": "content"},
            "request": fake_request,
        }
    )

    results = adapter.search("cozy fantasy", max_results=2)

    assert results[0].snippet == "longer content"
    assert calls["method"] == "POST"
    assert calls["json"]["query"] == "cozy fantasy"
    assert calls["json"]["max_results"] == 2
    assert calls["json"]["api_key"] == "tavily-secret"
    assert "Authorization" not in calls["headers"]


def test_generic_json_requires_its_environment_key(monkeypatch):
    monkeypatch.delenv("SOME_SEARCH_KEY", raising=False)
    adapter = GenericJSONSearchAdapter(
        {"base_url": "https://example.test/search", "api_key_env": "SOME_SEARCH_KEY"}
    )

    with pytest.raises(AdapterError, match="SOME_SEARCH_KEY"):
        adapter.search("q")


def test_generic_json_reports_bad_responses():
    adapter = GenericJSONSearchAdapter(
        {
            "base_url": "https://example.test/search",
            "api_key_env": "ANY_KEY",
            "request": lambda *a, **k: FakeResponse("bad request", status_code=400),
        }
    )
    import os

    os.environ["ANY_KEY"] = "x"
    try:
        with pytest.raises(AdapterError, match="400"):
            adapter.search("q")
    finally:
        os.environ.pop("ANY_KEY", None)


def test_generic_json_filters_amazon(monkeypatch):
    monkeypatch.setenv("ANY_KEY", "x")

    def fake_request(*args, **kwargs):
        return FakeResponse(
            {
                "results": [
                    {"title": "Amazon", "url": "https://smile.amazon.com/dp/1", "snippet": "x"},
                    {"title": "Elsewhere", "url": "https://example.com/e", "snippet": "y"},
                ]
            }
        )

    adapter = GenericJSONSearchAdapter(
        {"base_url": "https://example.test/search", "api_key_env": "ANY_KEY", "request": fake_request}
    )

    assert [result.title for result in adapter.search("q")] == ["Elsewhere"]
