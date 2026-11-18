"""Trip lifecycle: create/update a trip and search flights against it.

Mirrors booking_repository's shape (a domain error carrying code/status/detail, thin functions
taking an already-open session) so the two repositories read the same way.
"""

from collections import defaultdict
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.config import FLIGHT_CACHE_TTL_MINUTES
from app.models import (
    ExecutionRun,
    ExecutionStep,
    ExecutionEvent,
    FlightSearchResult,
    HITLBookingLog,
    TripRequest,
    TripStatus,
    utcnow,
)
from app.schemas import (
    ErrorCode,
    TripRequestCreate,
    TripRequestUpdate,
    validate_trip_dates,
)

class TripError(Exception):
    """A domain rejection carrying the client-facing code, HTTP status, and root-cause detail."""

    def __init__(self, code: ErrorCode, status_code: int, detail: str) -> None:
        self.code = code
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


async def create_trip(session: AsyncSession, user_id: int, data: TripRequestCreate) -> TripRequest:
    trip = TripRequest(user_id=user_id, **data.model_dump())
    session.add(trip)
    await session.commit()
    return trip


async def get_trip(session: AsyncSession, trip_id: int) -> TripRequest:
    """Fetch a persisted trip so the frontend can recover it after a page refresh."""
    trip = await session.get(TripRequest, trip_id)
    if trip is None:
        raise TripError(ErrorCode.TRIP_NOT_FOUND, 404, f"No trip {trip_id}.")
    return trip


async def list_trips(session: AsyncSession, user_id: int) -> list[TripRequest]:
    """Every trip this user has created, newest first. This lets the UI recover a trip that a newer
    one has since overwritten as the client's "active" pointer."""
    return list(
        await session.scalars(
            select(TripRequest)
            .where(col(TripRequest.user_id) == user_id)
            .order_by(col(TripRequest.created_at).desc(), col(TripRequest.id).desc())
            .limit(100)
        )
    )


# Route/date changes invalidate cached flight offers.
_CRITERIA_FIELDS = ("origin", "destination", "destination_airport", "depart_date", "return_date")


async def _invalidate_trip_derived_data(session: AsyncSession, trip_id: int) -> None:
    """Drop cached flight offers so a later search can't return old criteria."""
    stale_flight_results = await session.scalars(
        select(FlightSearchResult).where(col(FlightSearchResult.trip_request_id) == trip_id)
    )
    for flight_result in stale_flight_results:
        await session.delete(flight_result)


async def update_trip(session: AsyncSession, trip_id: int, data: TripRequestUpdate) -> TripRequest:
    trip = await session.scalar(
        select(TripRequest).where(col(TripRequest.id) == trip_id)
        .with_for_update().execution_options(populate_existing=True)
    )
    if trip is None:
        raise TripError(ErrorCode.TRIP_NOT_FOUND, 404, f"No trip {trip_id}.")

    criteria_before = {field_name: getattr(trip, field_name) for field_name in _CRITERIA_FIELDS}
    patch = data.model_dump(exclude_unset=True)
    route_changed = any(
        field_name in patch and patch[field_name] != criteria_before[field_name]
        for field_name in _CRITERIA_FIELDS
    )
    # A booking references an offer by foreign key; deleting the offer to invalidate it would
    # break the FK and destroy audit history. Reject before any mutation.
    if route_changed and await _trip_has_booking(session, trip_id):
        raise TripError(
            ErrorCode.INVALID_TRANSITION,
            409,
            "This trip has a booking tied to its flight offers; start a new trip "
            "before changing the route or dates.",
        )

    for field_name, value in patch.items():
        setattr(trip, field_name, value)

    try:
        validate_trip_dates(trip.depart_date, trip.return_date)
    except ValueError as error:
        await session.rollback()
        raise TripError(ErrorCode.VALIDATION_ERROR, 422, str(error)) from error

    criteria_changed = any(
        getattr(trip, field_name) != criteria_before[field_name] for field_name in _CRITERIA_FIELDS
    )
    if criteria_changed:
        await _invalidate_trip_derived_data(session, trip_id)
        trip.status = TripStatus.CREATED
    await session.commit()
    return trip


async def _trip_has_booking(session: AsyncSession, trip_id: int) -> bool:
    return (
        await session.scalar(
            select(HITLBookingLog.id).where(col(HITLBookingLog.trip_request_id) == trip_id).limit(1)
        )
    ) is not None


def cheapest_first(offers: list[FlightSearchResult]) -> list[FlightSearchResult]:
    """The take-home requires surfacing the cheapest flights, and the frontend lists offers in
    the order the API returns them, so ascending price order is a backend guarantee, held on
    every path (fresh live search, own-trip reuse, cross-trip cache) so all three agree. Shared
    with services/flight_search.py, which is the only other caller."""
    return sorted(offers, key=lambda offer: offer.price_usd)


async def get_trip_snapshot(
    session: AsyncSession, trip_id: int
) -> tuple[TripRequest, list[FlightSearchResult], bool]:
    trip = await get_trip(session, trip_id)
    batch_started_at = await session.scalar(
        select(FlightSearchResult.created_at)
        .where(
            col(FlightSearchResult.trip_request_id) == trip_id,
            col(FlightSearchResult.offer_index) == 0,
        )
        .order_by(col(FlightSearchResult.created_at).desc())
        .limit(1)
    )
    offers = (
        list(
            await session.scalars(
                select(FlightSearchResult).where(
                    col(FlightSearchResult.trip_request_id) == trip_id,
                    col(FlightSearchResult.created_at) >= batch_started_at,
                )
            )
        )
        if batch_started_at is not None
        else []
    )
    is_stale = (
        batch_started_at < utcnow() - timedelta(minutes=FLIGHT_CACHE_TTL_MINUTES)
        if batch_started_at is not None
        else False
    )
    return trip, cheapest_first(offers), is_stale


async def _execution_runs_for_trips(
    session: AsyncSession, trip_ids: list[int]
) -> list[tuple[ExecutionRun, list[ExecutionStep], list[ExecutionEvent]]]:
    """Every run across the given trips, newest first, each with its own steps/events."""
    if not trip_ids:
        return []
    execution_runs = list(
        await session.scalars(
            select(ExecutionRun)
            .where(col(ExecutionRun.trip_request_id).in_(trip_ids))
            .order_by(col(ExecutionRun.started_at).desc())
        )
    )
    return await _execution_run_details(session, execution_runs)


async def _execution_run_details(
    session: AsyncSession, execution_runs: list[ExecutionRun]
) -> list[tuple[ExecutionRun, list[ExecutionStep], list[ExecutionEvent]]]:
    if not execution_runs:
        return []
    run_ids = [run.id for run in execution_runs]
    all_steps = list(
        await session.scalars(
            select(ExecutionStep)
            .where(col(ExecutionStep.execution_run_id).in_(run_ids))
            .order_by(col(ExecutionStep.seq))
        )
    )
    steps_by_run_id: dict[int, list[ExecutionStep]] = defaultdict(list)
    for step in all_steps:
        steps_by_run_id[step.execution_run_id].append(step)
    all_events = list(
        await session.scalars(
            select(ExecutionEvent)
            .where(col(ExecutionEvent.execution_run_id).in_(run_ids))
            .order_by(col(ExecutionEvent.seq))
            .limit(1000)
        )
    )
    events_by_run_id: dict[int, list[ExecutionEvent]] = defaultdict(list)
    for event in all_events:
        if event.execution_run_id is not None:
            events_by_run_id[event.execution_run_id].append(event)
    return [
        (run, steps_by_run_id[run.id], events_by_run_id[run.id])
        for run in execution_runs
        if run.id
    ]


async def get_execution_panel(
    session: AsyncSession, trip_id: int
) -> tuple[
    list[tuple[ExecutionRun, list[ExecutionStep], list[ExecutionEvent]]],
    list[ExecutionEvent],
]:
    """Every run with its own steps/events, plus the same event stream for LiveActivity."""
    trip = await session.get(TripRequest, trip_id)
    if trip is None:
        raise TripError(ErrorCode.TRIP_NOT_FOUND, 404, f"No trip {trip_id}.")

    runs_with_details = await _execution_runs_for_trips(session, [trip_id])
    events = list(
        await session.scalars(
            select(ExecutionEvent)
            .where(col(ExecutionEvent.trip_request_id) == trip_id)
            .order_by(col(ExecutionEvent.seq))
            .limit(1000)
        )
    )
    return runs_with_details, events


async def list_execution_runs_for_user(
    session: AsyncSession, user_id: int, *, page_size: int = 20, before_run_id: int | None = None
) -> tuple[list[tuple[ExecutionRun, list[ExecutionStep], list[ExecutionEvent]]], int | None]:
    statement = select(ExecutionRun).join(TripRequest).where(col(TripRequest.user_id) == user_id)
    if before_run_id is not None:
        statement = statement.where(col(ExecutionRun.id) < before_run_id)
    runs = list(await session.scalars(
        statement.order_by(col(ExecutionRun.id).desc()).limit(page_size + 1)
    ))
    page = runs[:page_size]
    next_before_run_id = page[-1].id if len(runs) > page_size else None
    return await _execution_run_details(session, page), next_before_run_id
