# TravelOps

A bounded **zero-trust flight-search application** with a human-approved booking handoff. It
demonstrates verified sessions, role and tenant policy, MFA, append-only security decisions,
automatic session containment, deterministic flight search, caching, and audited booking state
transitions. It does not use an LLM and does not purchase flights.

## What it does

1. Create a trip with airports and travel dates.
2. Search SearchApi.io for real flight offers, or replay recorded fixtures in test mode.
3. Reuse recent identical searches to limit provider spend.
4. Request and approve a flight booking handoff, then receive a carrier/OTA checkout link.
5. Review flight-search activity, booking history, and zero-trust monitoring evidence.

The booking flow never claims to hold a fare or mint an airline confirmation number. Prices expire
after 30 minutes and the user completes purchase on the provider's site.

## Zero-trust demo

With Docker Desktop, demo certificates, and `.env` configured:

```bash
docker compose -f compose.zero-trust.yml up --build -d
docker compose -f compose.zero-trust.yml run --rm migrate python -m scripts.seed_security_demo
```

Open `https://localhost:8443`, select the traveler certificate, and use the seeded credentials.
The deployment keeps the API and PostgreSQL ports private; see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Stack

- FastAPI, Pydantic, SQLModel/asyncpg, PostgreSQL 16, Alembic
- DBOS for durable booking execution
- SearchApi.io for live flight offers, with recorded fixtures for repeatable tests
- React 19, Vite, Tailwind CSS v4

## Configuration

Copy `.env.example` to `.env`. The only external provider key required by the application is
`SEARCHAPI_API_KEY`; recorded-flight tests do not call the provider. The deployment also needs
the database, signing, and gateway secrets listed in `.env.example`.

## Development

```bash
cd backend
uv run pytest -q
uv run pyrefly check
```

The integration suite needs PostgreSQL. Use `uv run pytest -q -m no_database` for tests that do
not require it. The frontend is a standard Vite app under `frontend/`.

## Security scope

The project is a zero-trust prototype, not a production certification. It does not provide an
enterprise identity provider, hardware attestation, managed certificate revocation, fare holds,
or airline purchasing. See [docs/ZERO_TRUST_FINDINGS.md](docs/ZERO_TRUST_FINDINGS.md) for remaining
security findings and evidence.
