"""Planner execution owns dependencies, run recording, and outcome finalization."""

from pydantic_ai import UnexpectedModelBehavior
from pydantic_ai.exceptions import UsageLimitExceeded

from app.adapters.activities_tavily import ActivityProvider
from app.adapters.flights_searchapi import FlightProvider
from app.agent.execution_log import execution_context, finish_planner_run
from app.agent.planner import PlannerDeps, agent, default_usage_limits
from app.config import CEREBRAS_MODEL
from app.db import get_session_factory
from app.models import FitnessLevel
from app.schemas import ClarificationOut, PlannerOutput, PlanTooComplexOut


def _planner_outcome_for_error(error: Exception) -> PlannerOutput:
    """Map an expected planner failure to a user-facing outcome; re-raise anything unexpected."""
    if isinstance(error, UsageLimitExceeded):
        # A real, expected outcome on a research-heavy trip (MAX_CONTEXT_TOKENS).
        return PlanTooComplexOut(
            reason=(
                "This trip needed more planning work than fits in one pass. "
                "Try a shorter trip or a simpler request."
            )
        )
    if not isinstance(error, UnexpectedModelBehavior):
        raise error
    # The model exhausted its retries without producing a valid itinerary (e.g. no groundable
    # activities) — ask the user instead of crashing the request.
    return ClarificationOut(
        questions=[
            "I couldn't find enough verified activity information to complete this "
            "itinerary. Could you narrow the destination or share specific interests "
            "to search for?"
        ]
    )


async def _drive_agent_run(prompt: str, deps: PlannerDeps) -> PlannerOutput:
    """Iterate the agent to completion, finalizing the run on success or expected failure."""
    async with agent.iter(prompt, deps=deps, usage_limits=default_usage_limits()) as agent_run:
        try:
            async for _node in agent_run:
                pass
        except Exception as error:
            # Keeps whatever tool calls ran before the crash on the execution panel, not just successes.
            await finish_planner_run(
                message_history=agent_run.ctx.state.message_history,
                usage=agent_run.ctx.state.usage,
                status="failed",
            )
            return _planner_outcome_for_error(error)

        result = agent_run.result
        assert result is not None, "agent_run finished iterating without producing a result"
        await finish_planner_run(message_history=result.all_messages(), usage=result.usage)
        return result.output


async def run_planner(
    trip_id: int, prompt: str, trace_id: str,
    fitness_level: FitnessLevel,
    flight_provider: FlightProvider, activity_provider: ActivityProvider,
) -> PlannerOutput:
    async with (
        get_session_factory()() as session,
        execution_context(session, trip_id, run_model=CEREBRAS_MODEL, correlation=trace_id),
    ):
        deps = PlannerDeps(
            flight_provider=flight_provider,
            activity_provider=activity_provider,
            fitness_level=fitness_level,
        )
        return await _drive_agent_run(prompt, deps)
