# AGENTS.md

Repo instructions for coding agents working on TravelOps.

## Workflow
- Use code-first TDD. Runtime code and focused tests are the source of truth. Add the smallest
  boundary test that can fail. Do not duplicate behavior in Gherkin or a hand-written API spec.
- Security changes must test the affected trust boundary: identity/session validation, role and MFA
  policy, tenant ownership, API segmentation, append-only audit, or automatic containment.
- Before committing, run `cd backend && uv run pytest -q` and `uv run pyrefly check`. These need
  PostgreSQL. Use `uv run pytest -q -m no_database` for tests that do not need it.
- Use fail-fast and never nest control flow. Raise the project's typed retry error for recoverable
  external-call failures so the caller can self-correct.
- No abbreviations in names. Comments only for non-obvious WHY.

## Architecture (enforced)
DI (`Depends`) · Finite State Machine (`app/state.py`) · Repository (`app/repositories/`) ·
Strategy (`FlightProvider`: Live vs Recorded by `USE_LIVE_FLIGHT_API`) · Durable Execution
(DBOS wraps booking `execute` and the flight-search execution run).

## TravelOps system

TravelOps is deterministic: flight search uses the configured live or recorded provider, and
booking execution remains behind the human approval and security boundaries. There is no LLM,
planner, research adapter, or generated BAML boundary to edit.
