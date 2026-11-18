"""Context-local ExecutionEvent recorder. Deep call-stack code records without threading
trip_request_id through every signature. Commits immediately so a later failure still leaves
prior events recorded.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.models import ExecutionEvent, ExecutionEventKind, ExecutionRun, ExecutionStep, TripRequest, utcnow
from app.request_context import bind_correlation_id, correlation_id


@dataclass
class _ExecutionContext:
    session: AsyncSession
    trip_request_id: int
    execution_run: ExecutionRun | None
    # AsyncSession isn't safe for concurrent use; serializes record_event() within this context
    # only. Cross-context seq safety is the FOR UPDATE claim in record_event(), not this lock.
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


_current: ContextVar[_ExecutionContext | None] = ContextVar("execution_context", default=None)


@asynccontextmanager
async def execution_context(
    session: AsyncSession, trip_request_id: int, *, provider: str | None = None, correlation: str | None = None
) -> AsyncIterator[ExecutionRun | None]:
    """Bind one execution so its append-only events retain both trip and run ownership."""
    with bind_correlation_id(correlation or correlation_id()):
        execution_run = None
        if provider is not None:
            execution_run = ExecutionRun(trip_request_id=trip_request_id, status="running", provider=provider)
            session.add(execution_run)
            await session.commit()
        if execution_run is not None:
            assert execution_run.id is not None

        token = _current.set(
            _ExecutionContext(
                session=session,
                trip_request_id=trip_request_id,
                execution_run=execution_run,
            )
        )
        try:
            yield execution_run
        except Exception:
            if execution_run is not None and execution_run.status == "running":
                await finish_run("failed")
            raise
        finally:
            _current.reset(token)


def _bound_context(caller_name: str) -> _ExecutionContext:
    context = _current.get()
    if context is None:
        raise RuntimeError(
            f"{caller_name}() called with no execution_context bound; every "
            "adapter/tool/protocol call must run inside execution_log.execution_context()"
        )
    return context


def current_trip(caller_name: str) -> tuple[AsyncSession, int]:
    """Exposed so a tool can query the trip's own data without threading session/trip_id
    through the execution context."""
    context = _bound_context(caller_name)
    return context.session, context.trip_request_id


async def record_event(
    kind: ExecutionEventKind,
    name: str,
    status: str,
    detail: str,
    duration_ms: int | None = None,
    data: dict[str, Any] | None = None,
    provider: str | None = None,
) -> None:
    context = _bound_context("record_event")
    async with context.lock:
        # FOR UPDATE on the trip row serializes seq allocation across concurrent runs (e.g. a
        # double-submitted searches); a locally-cached counter would let two runs read the same
        # starting point and hand out colliding seq values.
        await context.session.execute(
            select(TripRequest).where(col(TripRequest.id) == context.trip_request_id).with_for_update()
        )
        result = await context.session.execute(
            select(func.max(ExecutionEvent.seq)).where(
                col(ExecutionEvent.trip_request_id) == context.trip_request_id
            )
        )
        next_seq = (result.scalar_one_or_none() or 0) + 1
        context.session.add(
            ExecutionEvent(
                trip_request_id=context.trip_request_id,
                execution_run_id=context.execution_run.id if context.execution_run is not None else None,
                seq=next_seq,
                kind=kind,
                name=name,
                provider=provider,
                status=status,
                detail=detail,
                duration_ms=duration_ms,
                data=data,
                correlation_id=correlation_id(),
            )
        )
        await context.session.commit()


async def finish_run(
    status: str,
    *,
    steps: list[ExecutionStep] | None = None,
    total_ms: int | None = None,
    started_at: datetime | None = None,
    usage: Any = None,
) -> None:
    context = _bound_context("finish_run")
    execution_run = context.execution_run
    if execution_run is None:
        raise RuntimeError("finish_run requires an execution context with a run")
    finished_at = utcnow()
    execution_run.status = status
    if started_at is not None:
        execution_run.started_at = started_at
    execution_run.finished_at = finished_at
    execution_run.total_ms = (
        total_ms if total_ms is not None
        else round((finished_at - execution_run.started_at).total_seconds() * 1000)
    )
    assert execution_run.id is not None
    for step in steps or []:
        step.execution_run_id = execution_run.id
        context.session.add(step)
    await context.session.commit()
