"""DBOS durable-execution wiring: booking execute and the agent run replay-safe across crashes.

Both entry points take only serializable arguments (a DBOS constraint) and rebuild whatever
session/provider they need internally, rather than receiving them injected — this is the only
change from the plain, already-tested versions of the functions they call.
"""

from dbos import DBOS, DBOSConfig
from pydantic_ai.models import Model

from app.adapters.activities_tavily import TavilyActivityProvider
from app.adapters.flights_searchapi import get_flight_provider
from app.agent import execution
from app.agent.planner import agent
from app.config import get_settings
from app.db import get_session_factory
from app.models import FitnessLevel, FlightSearchResult, TripRequest
from app.rate_limit import acquire_agent_run_slot, release_agent_run_slot
from app.request_context import bind_correlation_id, correlation_id
from app.repositories import booking_repository as repository
from app.repositories import trips_repository
from app.schemas import (
    BookingLogOut,
    ItineraryOut,
    PlannerOutput,
)


def _as_durable_step(step_name: str, bound_method):
    # DBOS.step setattrs registration metadata onto its target; bound methods can't hold
    # arbitrary attributes, so wrap in a plain function that delegates to the bound method.
    @DBOS.step(name=step_name)
    async def _step(*args, **kwargs):
        return await bound_method(*args, **kwargs)

    return _step


# Patched once at import (not in launch_dbos(), which fires once per test via the
# function-scoped `client` fixture and would double-wrap on every call).
assert isinstance(agent.model, Model), "agent must be built with a real Model instance"
agent.model.request = _as_durable_step("cerebras_request", agent.model.request)


def launch_dbos() -> None:
    settings = get_settings()
    DBOS(config=DBOSConfig(name="travel-agent", system_database_url=settings.dbos_database_url))
    DBOS.launch()


def shutdown_dbos() -> None:
    DBOS.destroy()


@DBOS.step(name="fetch_booking_options")
async def _fetch_booking_options_step(flight: FlightSearchResult) -> list[dict]:
    provider = get_flight_provider(get_settings())
    flights = flight.raw_offer["flights"]
    async with get_session_factory()() as session:
        trip = await session.get(TripRequest, flight.trip_request_id)
    assert trip is not None, "flight references a trip that no longer exists"
    return await provider.fetch_booking_options(
        flight.booking_token,
        departure_id=flights[0]["departure_airport"]["id"],
        arrival_id=flights[-1]["arrival_airport"]["id"],
        outbound_date=flights[0]["departure_airport"]["date"],
        return_date=trip.return_date,
        booking_token_is_resolved=flight.raw_offer.get("booking_token") == flight.booking_token,
    )


@DBOS.workflow(name="execute_booking")
async def execute_booking_durable(
    log_id: int,
    actor_user_id: int,
    tenant_id: str,
    session_id: str,
    trace_id: str | None = None,
) -> BookingLogOut:
    with bind_correlation_id(trace_id):
        async with get_session_factory()() as session:
            booking = await repository.execute_booking(
                session,
                log_id,
                _fetch_booking_options_step,
                actor_user_id=actor_user_id,
                tenant_id=tenant_id,
                session_id=session_id,
            )
            return BookingLogOut.model_validate(booking)


@DBOS.step(name="persist_itinerary")
async def _persist_itinerary_step(trip_id: int, prompt: str, output: ItineraryOut) -> None:
    async with get_session_factory()() as session:
        await trips_repository.persist_itinerary_if_current(session, trip_id, prompt, output)


@DBOS.workflow(name="run_planner")
async def _run_planner_workflow(
    trip_id: int, prompt: str, fitness_level: FitnessLevel, trace_id: str
) -> PlannerOutput:
    settings = get_settings()
    flight_provider = get_flight_provider(settings)
    flight_provider.search_offers = _as_durable_step("search_flights_offers", flight_provider.search_offers)
    activity_provider = TavilyActivityProvider(settings.tavily_api_key.get_secret_value())
    activity_provider.search = _as_durable_step("web_search", activity_provider.search)
    output = await execution.run_planner(
        trip_id, prompt, trace_id, fitness_level, flight_provider, activity_provider
    )
    if isinstance(output, ItineraryOut):
        await _persist_itinerary_step(trip_id, prompt, output)
    return output


async def run_planner_durable(
    trip_id: int, prompt: str, fitness_level: FitnessLevel, trace_id: str | None = None
) -> PlannerOutput:
    """Not itself a DBOS workflow: the concurrency slot is plain in-process state, and acquiring
    it inside a replayable workflow body risks a double-acquire if DBOS re-enters that body
    during its own internal record/persist resolution (observed empirically) — so the slot wraps
    the durable call from the outside instead."""
    await acquire_agent_run_slot()
    try:
        return await _run_planner_workflow(
            trip_id, prompt, fitness_level, trace_id or correlation_id()
        )
    finally:
        release_agent_run_slot()
