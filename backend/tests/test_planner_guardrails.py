"""The low-fitness guard must reject high intensity without rejecting moderate activity."""

from types import SimpleNamespace
from typing import Literal

import pytest
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from app.adapters.activities_tavily import NormalizedActivityResult
from app.adapters.flights_searchapi import FlightSearchOutcome
from app.agent.planner import (
    MAX_WEB_SEARCH_CALLS,
    PlannerDeps,
    reject_unsafe_intensity,
    search_flights,
    web_search,
)
from app.models import FitnessLevel
from app.schemas import ActivityOut, ItineraryDayOut, ItineraryOut

pytestmark = pytest.mark.no_database


class StubFlightProvider:
    async def search_offers(
        self,
        departure_id: str,
        arrival_id: str,
        outbound_date: str,
        return_date: str | None,
    ) -> FlightSearchOutcome:
        return FlightSearchOutcome()

    async def fetch_booking_options(
        self,
        booking_token: str,
        *,
        departure_id: str,
        arrival_id: str,
        outbound_date: str,
        return_date: str | None,
        booking_token_is_resolved: bool = False,
    ) -> list[dict[str, object]]:
        return []


class StubActivityProvider:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def search(self, query: str, max_results: int = 5) -> list[NormalizedActivityResult]:
        self.queries.append(query)
        return []


@pytest.mark.parametrize("intensity", ["high", "moderate"])
def test_low_fitness_intensity_boundary(intensity: Literal["high", "moderate"]) -> None:
    context = RunContext(
        deps=PlannerDeps(
            flight_provider=StubFlightProvider(),
            activity_provider=StubActivityProvider(),
            fitness_level=FitnessLevel.LOW,
        ),
        model=TestModel(),
        usage=RunUsage(),
    )
    itinerary = ItineraryOut(days=[ItineraryDayOut(
        day_number=1,
        summary="Explore",
        activities=[ActivityOut(
            name="Summit hike",
            description="A mountain trail.",
            intensity=intensity,
            source_url="https://example.test/hike",
        )],
    )])
    if intensity == "high":
        with pytest.raises(ModelRetry, match="Summit hike"):
            reject_unsafe_intensity(context, itinerary)
        return
    assert reject_unsafe_intensity(context, itinerary) is itinerary


@pytest.mark.parametrize(
    "departure_id,arrival_id,outbound_date,return_date",
    [
        ("JFK", "LHR", "2030-08-01", None),
        ("JFK", "CDG", "2030-08-02", None),
    ],
)
@pytest.mark.asyncio
async def test_flight_tool_rejects_route_or_date_that_does_not_match_trip(
    monkeypatch: pytest.MonkeyPatch,
    departure_id: str,
    arrival_id: str,
    outbound_date: str,
    return_date: str | None,
) -> None:
    class Session:
        async def get(self, _model: object, _trip_id: int) -> object:
            return SimpleNamespace(
                origin="JFK",
                destination_airport="CDG",
                depart_date="2030-08-01",
                return_date=None,
            )

    monkeypatch.setattr("app.agent.planner.current_trip", lambda _name: (Session(), 1))
    context = RunContext(
        deps=PlannerDeps(
            flight_provider=StubFlightProvider(),
            activity_provider=StubActivityProvider(),
        ),
        model=TestModel(),
        usage=RunUsage(),
    )
    with pytest.raises(ModelRetry, match="do not match"):
        await search_flights(context, departure_id, arrival_id, outbound_date, return_date)


@pytest.mark.asyncio
async def test_web_search_allows_three_calls_then_rejects_the_fourth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Session:
        async def get(self, _model: object, _trip_id: int) -> object:
            return SimpleNamespace(destination_airport="CDG")

    activity_provider = StubActivityProvider()

    async def record_event(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr("app.agent.planner.current_trip", lambda _name: (Session(), 1))
    monkeypatch.setattr("app.agent.planner.record_event", record_event)
    context = RunContext(
        deps=PlannerDeps(
            flight_provider=StubFlightProvider(),
            activity_provider=activity_provider,
        ),
        model=TestModel(),
        usage=RunUsage(),
    )

    for index in range(MAX_WEB_SEARCH_CALLS):
        assert await web_search(context, f"things to do {index}") == []

    with pytest.raises(ModelRetry, match=str(MAX_WEB_SEARCH_CALLS)):
        await web_search(context, "things to do final")
    assert activity_provider.queries == [
        f"things to do {index} near CDG airport" for index in range(MAX_WEB_SEARCH_CALLS)
    ]
