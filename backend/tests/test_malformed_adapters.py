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
