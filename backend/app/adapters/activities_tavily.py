"""Tavily activity-research adapter. Tolerant: errors/empty results return [], never fabricated."""

import logging
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from app.config import EXCLUDED_ACTIVITY_SEARCH_DOMAINS

logger = logging.getLogger(__name__)

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
TAVILY_TIMEOUT_SECONDS = 60.0


@dataclass
class NormalizedActivityResult:
    """One Tavily search result — ``url`` is the citation that grounds an itinerary activity."""

    title: str
    url: str
    content: str
    score: float


class ActivityProvider(Protocol):
    async def search(
        self, query: str, max_results: int = 5
    ) -> list[NormalizedActivityResult]: ...


class TavilyActivityProvider:
    """Calls the Tavily REST search endpoint directly — one request, no SDK needed."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def search(self, query: str, max_results: int = 5) -> list[NormalizedActivityResult]:
        try:
            async with httpx.AsyncClient(timeout=TAVILY_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    TAVILY_SEARCH_URL,
                    json={
                        "api_key": self._api_key,
                        "query": query,
                        "max_results": max_results,
                        "search_depth": "advanced",
                        "exclude_domains": EXCLUDED_ACTIVITY_SEARCH_DOMAINS,
                    },
                )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, TypeError, ValueError, KeyError) as error:
            logger.warning("tavily web_search failed: %r for query=%r", error, query)
            return []

        results = body.get("results", []) if isinstance(body, dict) else []
        if not isinstance(results, list):
            return []
        try:
            return [
                NormalizedActivityResult(
                    title=result.get("title", ""),
                    url=result.get("url", ""),
                    content=result.get("content", "").strip(),
                    score=float(result.get("score", 0.0)),
                )
                for result in results
                if isinstance(result, dict) and _is_safe_source_url(result.get("url"))
            ]
        except (AttributeError, TypeError, ValueError):
            logger.warning("tavily web_search returned malformed results for query=%r", query)
            return []


def _is_safe_source_url(value: object) -> bool:
    return isinstance(value, str) and urlsplit(value).scheme == "https" and bool(urlsplit(value).netloc)
