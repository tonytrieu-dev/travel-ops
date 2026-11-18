# AGENTS.md

Repo instructions for coding agents working on Travel Agent.

## Workflow
- Use code-first TDD. Runtime code and focused tests are the source of truth. Add the smallest
  boundary test that can fail. Do not duplicate behavior in Gherkin or a hand-written API spec.
- Security changes must test the affected trust boundary: identity/session validation, role and MFA
  policy, tenant ownership, API segmentation, append-only audit, or automatic containment.
- Before committing, run `cd backend && uv run pytest -q` and `uv run pyrefly check`. These need
  PostgreSQL. Use `uv run pytest -q -m no_database` for tests that do not need it.
- Use fail-fast and never nest control flow. In the agent's tool loop, raise `ModelRetry` for a
  recoverable tool-call error so the model can self-correct.
- No abbreviations in names. Comments only for non-obvious WHY.

## Architecture (enforced)
DI (`Depends`) · Finite State Machine (`app/state.py`) · Repository (`app/repositories/`) ·
Strategy (`FlightProvider`: Live vs Recorded by `USE_LIVE_FLIGHT_API`) · Durable Execution
(DBOS wraps booking `execute` and the agent run).

## Travel-agent system prompt

The planner's LLM boundary (system prompt, output schemas `ItineraryOut`/`ClarificationOut`/
`ItineraryDayOut`/`ActivityOut`, and the Cerebras client) is defined once in
`backend/baml_src/travel_planner.baml` and generated into `baml_sdk`. Edit the prompt there, then
run `baml generate` from `backend`. `app/agent/prompts.py` reads the prompt text from that BAML
source; `app/schemas.py` re-exports the generated output types. The pydantic-ai agent in
`app/agent/planner.py` still owns the tool loop and the stateful safety validators.
