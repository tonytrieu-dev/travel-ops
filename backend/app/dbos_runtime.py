"""DBOS durable-execution wiring: booking execute and the agent run replay-safe across crashes.

Both entry points take only serializable arguments (a DBOS constraint) and rebuild whatever
session/provider they need internally, rather than receiving them injected — this is the only
change from the plain, already-tested versions of the functions they call.
"""

from dbos import DBOS, DBOSConfig
from app.adapters.flights_searchapi import get_flight_provider
from app.config import get_settings
from app.db import get_session_factory
from app.models import FlightSearchResult, TripRequest
from app.request_context import bind_correlation_id
from app.repositories import booking_repository as repository
from app.schemas import (
    BookingLogOut,
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
