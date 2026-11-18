"""Trip routes. Each handler stays thin: call the repository (which owns validation and caching),
then shape the result into the response model. Domain rejections
raise TripError, rendered as a ProblemDetail by the app-level handler in main.py.
"""

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.flights_searchapi import derive_flight_legs, get_flight_provider
from app.execution_log import execution_context
from app import config
from app.db import get_session
from app.models import ExecutionEvent, ExecutionRun, ExecutionStep, TripRequest, User
from app.rate_limit import enforce_request_rate_limit
from app.repositories import trips_repository as repository
from app.schemas import (
    ExecutionRunOut,
    ExecutionStepOut,
    ExecutionEventOut,
    ExecutionPanelOut,
    FlightLegOut,
    FlightOfferOut,
    FlightSearchOut,
    GlobalExecutionPanelOut,
    ProblemDetail,
    TripRequestCreate,
    TripRequestOut,
    TripRequestUpdate,
    TripSnapshotOut,
)
from app.services.flight_search import FlightSearchService, flight_provider_name
from app.security_admission import admit_collection_route, admit_trip_route
from app.security_segment import enforce_api_segment

router = APIRouter(
    prefix="/api",
    tags=["trips"],
    dependencies=[Depends(enforce_api_segment)],
)

_VALIDATION: dict[int | str, dict[str, Any]] = {422: {"model": ProblemDetail}}
_NOT_FOUND: dict[int | str, dict[str, Any]] = {404: {"model": ProblemDetail}}
_NOT_FOUND_OR_VALIDATION: dict[int | str, dict[str, Any]] = {
    404: {"model": ProblemDetail},
    422: {"model": ProblemDetail},
}
_NOT_FOUND_OR_RATE_LIMITED: dict[int | str, dict[str, Any]] = {
    404: {"model": ProblemDetail},
    429: {"model": ProblemDetail},
}


@router.post(
    "/trips",
    response_model=TripRequestOut,
    responses=_VALIDATION,
)
async def create_trip(
    body: TripRequestCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(admit_collection_route("trip.create", "trip")),
) -> TripRequestOut:
    assert user.id is not None, "admit_collection_route always returns a persisted user"
    trip = await repository.create_trip(session, user.id, body)
    return TripRequestOut.model_validate(trip)


@router.get(
    "/trips",
    response_model=list[TripRequestOut],
)
async def list_trips(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(admit_collection_route("trip.read", "trips")),
) -> list[TripRequestOut]:
    assert user.id is not None, "admit_collection_route always returns a persisted user"
    trips = await repository.list_trips(session, user.id)
    return [TripRequestOut.model_validate(trip) for trip in trips]


@router.get("/trips/{trip_id}", response_model=TripRequestOut, responses=_NOT_FOUND)
async def get_trip(trip: TripRequest = Depends(admit_trip_route("trip.read"))) -> TripRequestOut:
    return TripRequestOut.model_validate(trip)


@router.patch(
    "/trips/{trip_id}",
    response_model=TripRequestOut,
    responses=_NOT_FOUND_OR_VALIDATION,
    dependencies=[Depends(admit_trip_route("trip.update"))],
)
async def update_trip(
    trip_id: int,
    body: TripRequestUpdate,
    session: AsyncSession = Depends(get_session),
) -> TripRequestOut:
    trip = await repository.update_trip(session, trip_id, body)
    return TripRequestOut.model_validate(trip)


def _to_flight_offer_out(offer: Any) -> FlightOfferOut:
    offer_out = FlightOfferOut.model_validate(offer)
    offer_out.legs = [FlightLegOut(**leg) for leg in derive_flight_legs(offer.raw_offer)]
    return offer_out


@router.get(
    "/trips/{trip_id}/snapshot",
    response_model=TripSnapshotOut,
    responses=_NOT_FOUND,
    dependencies=[Depends(admit_trip_route("trip.read"))],
)
async def get_trip_snapshot(
    trip_id: int,
    session: AsyncSession = Depends(get_session),
) -> TripSnapshotOut:
    trip, offers, is_stale = await repository.get_trip_snapshot(session, trip_id)
    return TripSnapshotOut(
        trip=TripRequestOut.model_validate(trip),
        flight_search=FlightSearchOut(
            offers=[_to_flight_offer_out(offer) for offer in offers],
            is_stale=is_stale,
        )
        if offers
        else None,
    )


@router.post(
    "/trips/{trip_id}/flights/search",
    response_model=FlightSearchOut,
    responses=_NOT_FOUND_OR_RATE_LIMITED,
    dependencies=[
        Depends(admit_trip_route("flight.search")),
        Depends(enforce_request_rate_limit),
    ],
)
async def search_trip_flights(
    trip_id: int, session: AsyncSession = Depends(get_session)
) -> FlightSearchOut:
    provider = get_flight_provider(config.get_settings())
    await repository.get_trip(session, trip_id)
    async with execution_context(
        session, trip_id, provider=flight_provider_name(provider)
    ):
        outcome = await FlightSearchService(session, provider).search(trip_id, record_run=True)
    return FlightSearchOut(
        offers=[_to_flight_offer_out(offer) for offer in outcome.offers],
        unavailable_reason=outcome.unavailable_reason,
    )


def _to_execution_run_out(
    execution_run: ExecutionRun,
    steps: list[ExecutionStep],
    events: list[ExecutionEvent],
) -> ExecutionRunOut:
    execution_run_out = ExecutionRunOut.model_validate(execution_run)
    execution_run_out.steps = [ExecutionStepOut.model_validate(step) for step in steps]
    execution_run_out.events = [ExecutionEventOut.model_validate(event) for event in events]
    return execution_run_out


def _to_panel_out(
    trip_id: int,
    runs_with_details: list[
        tuple[ExecutionRun, list[ExecutionStep], list[ExecutionEvent]]
    ],
    events: list[ExecutionEvent],
) -> ExecutionPanelOut:
    return ExecutionPanelOut(
        trip_request_id=trip_id,
        execution_runs=[
            _to_execution_run_out(run, steps, run_events)
            for run, steps, run_events in runs_with_details
        ],
        events=[ExecutionEventOut.model_validate(event) for event in events],
    )


@router.get(
    "/trips/{trip_id}/execution",
    response_model=ExecutionPanelOut,
    responses=_NOT_FOUND,
    dependencies=[Depends(admit_trip_route("trip.execution.read"))],
)
async def get_trip_execution(
    trip_id: int,
    session: AsyncSession = Depends(get_session),
) -> ExecutionPanelOut:
    runs_with_details, events = await repository.get_execution_panel(session, trip_id)
    return _to_panel_out(trip_id, runs_with_details, events)


@router.get(
    "/execution",
    response_model=GlobalExecutionPanelOut,
    responses={403: {"model": ProblemDetail}},
)
async def get_all_execution(
    page_size: int = Query(default=20, ge=1, le=100),
    before_run_id: int | None = Query(default=None, gt=0),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(admit_collection_route("execution.history.read", "execution")),
) -> GlobalExecutionPanelOut:
    assert user.id is not None, "admit_collection_route always returns a persisted user"
    runs_with_details, next_before_run_id = await repository.list_execution_runs_for_user(
        session, user.id, page_size=page_size, before_run_id=before_run_id
    )
    return GlobalExecutionPanelOut(
        next_before_run_id=next_before_run_id,
        execution_runs=[
            _to_execution_run_out(run, steps, events) for run, steps, events in runs_with_details
        ]
    )
