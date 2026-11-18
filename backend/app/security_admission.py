"""Protected-resource admission: policy, ownership, hiding, and one decision.

Routes attach admission as a dependency, not a call: `Depends(admit_trip_route("trip.read"))`
and `Depends(admit_booking_route("booking.approve", require_mfa=True))` declare the action and
MFA requirement once per route and return the owned object, so handlers never thread
request/session/context/correlation plumbing themselves.
"""

from collections.abc import Awaitable, Callable

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app import security_posture as posture
from app.db import get_session
from app.dependencies import get_security_context
from app.models import HITLBookingLog, TripRequest, User
from app.repositories.booking_repository import BookingError
from app.repositories.trips_repository import TripError
from app.schemas import ErrorCode
from app.security_evidence import record_security_event
from app.security_identity import SecurityContext

_ROLE_ACTIONS = {
    "traveler": {
        "trip.read", "trip.create", "trip.update", "trip.plan", "trip.execution.read",
        "flight.search", "booking.read", "booking.request", "booking.approve",
        "booking.cancel", "booking.execute",
    },
    "trip-planner": {
        "trip.read", "trip.create", "trip.update", "trip.plan", "trip.execution.read",
        "flight.search", "booking.read", "execution.history.read", "booking.history.read",
    },
    "platform-operator": {"security.read"},
    "security-operator": {"security.read", "connector.configure"},
    "admin": {
        "trip.read", "trip.create", "trip.update", "trip.plan", "trip.execution.read",
        "flight.search", "booking.read", "booking.request", "booking.approve",
        "booking.cancel", "booking.execute", "security.read", "connector.configure",
        "execution.history.read", "booking.history.read",
    },
}


class SecurityError(Exception):
    def __init__(self, detail: str) -> None:
        self.detail = detail
        self.status_code = 403
        super().__init__(detail)


def _authorization_denial(
    context: SecurityContext, action: str, require_mfa: bool
) -> str | None:
    if not posture.enforcement_active():
        return None
    if action not in _ROLE_ACTIONS.get(context.role, set()):
        return "role is not allowed to perform action"
    if require_mfa and not context.mfa_verified:
        return "MFA required for privileged action"
    return None


async def authorize(
    context: SecurityContext,
    session: AsyncSession,
    *,
    action: str,
    resource: str,
    request: Request | None = None,
    require_mfa: bool = False,
) -> None:
    await _enforce_decision(
        session, context, action=action, resource=resource, request=request,
        require_mfa=require_mfa,
        denial_reason=_authorization_denial(context, action, require_mfa),
    )


async def _enforce_decision(
    session: AsyncSession,
    context: SecurityContext,
    *,
    action: str,
    resource: str,
    request: Request | None,
    require_mfa: bool,
    denial_reason: str | None,
    not_found: Exception | None = None,
) -> None:
    await record_security_event(
        session, context, action=action, resource=resource,
        decision="deny" if denial_reason is not None else "allow",
        reason=denial_reason or (
            "allowed by role policy" if posture.enforcement_active()
            else "development security enforcement disabled"
        ),
        request=request, mfa_required=require_mfa,
    )
    if denial_reason is None:
        return
    if not_found is not None:
        raise not_found
    raise SecurityError(denial_reason)


async def _admit(
    session: AsyncSession,
    context: SecurityContext,
    *,
    action: str,
    resource: str,
    request: Request | None,
    require_mfa: bool,
    exists: bool,
    owned: bool,
    not_found: Exception,
) -> None:
    if not exists:
        denial_reason = "resource does not exist or is not visible"
    elif posture.enforcement_active() and not owned:
        denial_reason = "tenant or owner mismatch"
    else:
        denial_reason = _authorization_denial(context, action, require_mfa)
    await _enforce_decision(
        session, context, action=action, resource=resource, request=request,
        require_mfa=require_mfa, denial_reason=denial_reason,
        not_found=not_found if not exists or not owned else None,
    )


async def admit_trip(
    session: AsyncSession,
    context: SecurityContext,
    trip_id: int,
    *,
    action: str,
    request: Request | None = None,
    require_mfa: bool = False,
) -> TripRequest:
    trip = await session.get(TripRequest, trip_id)
    owner = await session.get(User, trip.user_id) if trip is not None else None
    owned = bool(
        trip is not None and owner is not None
        and owner.tenant_id == context.tenant_id and trip.user_id == context.user_id
    )
    not_found = TripError(ErrorCode.TRIP_NOT_FOUND, 404, f"No trip {trip_id}.")
    await _admit(
        session, context, action=action, resource=f"trip:{trip_id}", request=request,
        require_mfa=require_mfa, exists=trip is not None, owned=owned, not_found=not_found,
    )
    if trip is None:
        raise not_found
    return trip


async def admit_booking(
    session: AsyncSession,
    context: SecurityContext,
    log_id: int,
    *,
    action: str,
    request: Request | None = None,
    require_mfa: bool = False,
) -> HITLBookingLog:
    booking = await session.get(HITLBookingLog, log_id)
    trip = await session.get(TripRequest, booking.trip_request_id) if booking is not None else None
    owner = await session.get(User, trip.user_id) if trip is not None else None
    owned = bool(
        booking is not None and trip is not None and owner is not None
        and owner.tenant_id == context.tenant_id and trip.user_id == context.user_id
    )
    not_found = BookingError(ErrorCode.BOOKING_NOT_FOUND, 404, f"No booking log {log_id}.")
    await _admit(
        session, context, action=action, resource=f"booking:{log_id}", request=request,
        require_mfa=require_mfa, exists=booking is not None and trip is not None,
        owned=owned, not_found=not_found,
    )
    if booking is None:
        raise not_found
    return booking


# --- Route dependencies -----------------------------------------------------------------------
# The gate's action and MFA requirement are static per route, so each route declares them once as
# a dependency instead of repeating a four-argument call plus request/session/context params in
# every handler body.


def admit_trip_route(
    action: str, *, require_mfa: bool = False
) -> Callable[..., Awaitable[TripRequest]]:
    async def dependency(
        trip_id: int,
        request: Request,
        session: AsyncSession = Depends(get_session),
        context: SecurityContext = Depends(get_security_context),
    ) -> TripRequest:
        return await admit_trip(
            session, context, trip_id, action=action, request=request, require_mfa=require_mfa
        )

    return dependency


def admit_booking_route(
    action: str, *, require_mfa: bool = False
) -> Callable[..., Awaitable[HITLBookingLog]]:
    async def dependency(
        log_id: int,
        request: Request,
        session: AsyncSession = Depends(get_session),
        context: SecurityContext = Depends(get_security_context),
    ) -> HITLBookingLog:
        return await admit_booking(
            session, context, log_id, action=action, request=request, require_mfa=require_mfa
        )

    return dependency


def authorize_route(
    action: str, resource: str, *, require_mfa: bool = False
) -> Callable[..., Awaitable[None]]:
    async def dependency(
        request: Request,
        session: AsyncSession = Depends(get_session),
        context: SecurityContext = Depends(get_security_context),
    ) -> None:
        await authorize(
            context, session, action=action, resource=resource,
            request=request, require_mfa=require_mfa,
        )

    return dependency


def admit_collection_route(
    action: str, resource: str, *, require_mfa: bool = False
) -> Callable[..., Awaitable[User]]:
    """One seam for collection routes (create/list, no path id): authorize the action and return
    the authenticated owner in a single dependency, so handlers never reach for a second identity
    door. The returned principal's id scopes the owner-filtered repository query."""
    async def dependency(
        request: Request,
        session: AsyncSession = Depends(get_session),
        context: SecurityContext = Depends(get_security_context),
    ) -> User:
        await authorize(
            context, session, action=action, resource=resource,
            request=request, require_mfa=require_mfa,
        )
        owner = await session.get(User, context.user_id)
        assert owner is not None, "authorized context always references a persisted user"
        return owner

    return dependency
