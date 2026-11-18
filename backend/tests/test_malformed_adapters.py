import functools

import httpx
import pytest

from app.adapters.activities_tavily import TavilyActivityProvider

pytestmark = pytest.mark.no_database


@pytest.mark.asyncio
async def test_tavily_malformed_successful_response_returns_no_results(monkeypatch: pytest.MonkeyPatch) -> None:
    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [{"title": "broken", "score": "not-a-number"}]})

    monkeypatch.setattr(httpx, "AsyncClient", functools.partial(
        httpx.AsyncClient, transport=httpx.MockTransport(respond),
    ))
    assert await TavilyActivityProvider("test-key").search("beaches") == []


@pytest.mark.asyncio
async def test_tavily_discards_non_https_source_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [
            {"title": "unsafe", "url": "javascript:alert(1)", "content": "x", "score": 1},
            {"title": "safe", "url": "https://example.test/activity", "content": "x", "score": 1},
        ]})

    monkeypatch.setattr(httpx, "AsyncClient", functools.partial(
        httpx.AsyncClient, transport=httpx.MockTransport(respond),
    ))
    results = await TavilyActivityProvider("test-key").search("beaches")
    assert [result.url for result in results] == ["https://example.test/activity"]
