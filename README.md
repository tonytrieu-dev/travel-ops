# TravelOps Agent

A bounded **zero-trust application prototype**, using a stateful travel planner as
the protected resource. It demonstrates user/session verification, role and tenant
access policy, privileged MFA, recorded security decisions, and automatic session
containment. It is a first implementation toward the enterprise-network project
objective; the isolated deployment adds certificate possession and private service networks.
Deployment-level verification still requires Docker.

The planner searches flights and destination activities and proposes an itinerary.
Booking approval and execution stay outside the model's tools, behind application
policy and a human-approval state machine. The system returns checkout links;
it does not purchase flights.

## Zero-trust architecture

The application requires verified sessions on protected routes. The isolated deployment adds
mutual TLS and private service networks. See the [architecture](docs/ARCHITECTURE.md) for the
security model, trust boundaries, and known limits.

## Zero-trust demo

Follow [deployment setup](#running-it) first, including the private environment secrets.
For the synthetic walkthrough, issue both devices before starting the gateway:

```bash
python3 deploy/issue-device.py device-a-traveler
python3 deploy/issue-device.py device-a-operator
docker compose -f compose.zero-trust.yml up --build -d
docker compose -f compose.zero-trust.yml run --rm migrate python -m scripts.seed_security_demo
cd backend
uv sync
baml generate
uv run python -m scripts.security_demo
```

The synthetic seed uses public demo credentials for a disposable local walkthrough. Do not reuse
them. Login, MFA, and protected requests require the registered client certificate.

For the repeatable PostgreSQL demonstration, run the security tests in the [tests](#5-tests)
section. They cover authorized booking, cross-tenant denial, tampered tokens, revocation, and
completed planner exchanges retained after a later model failure. They use isolated test data and
stubbed external providers; they do not purchase flights or consume model/search quota.
If the booking-options provider is unavailable, execution stays confirmed and the user can retry;
the app does not create a terminal handoff without checkout links.

## What it does

1. **Plan a trip:** origin, destination, dates, age, and fitness level are all required at
   intake. It can still ask a clarifying question if a provided value is ambiguous.
2. **Search flights:** SearchApi.io Google Flights results in live-provider mode, with
   route-and-date caching; recorded fixtures are available for repeatable tests.
3. **Generate an attributed itinerary:** the agent researches activities through Tavily and
   returns a day-by-day plan. Each activity must cite a URL returned by that run's web search.
4. **Human-approved booking handoff:** review a proposed flight, explicitly approve it, then
   retrieve real checkout links, as three separate steps. Nothing here books a flight. Approval
   unlocks a deterministic, audited workflow whose output is airline/OTA checkout links with the
   chosen flight already attached; you complete the purchase on the carrier's own site, and the
   reference this app stores is its own audit id, not an airline confirmation number. Because no
   fare is actually held, a 30-minute freshness window guards against handing you a stale price:
   approving or executing past it marks the booking `EXPIRED` and asks you to search again.
5. **Review execution and approvals:** trip planners and admins have separate execution-history
   and approval-history tabs, scoped to their own trips. Execution history includes tool calls,
   token usage, timing, and page controls. Approval history reads the append-only booking trail.
   Travelers retain their trip's live activity and booking controls without these history tabs.
6. **Revisit any past trip:** a "Your trips" tab lists everything you've created, newest first
   and filterable by date range. Trips remain in Postgres until their rows are removed.

## Stack

- **Backend:** FastAPI, Pydantic AI, SQLModel/asyncpg, PostgreSQL 16, Alembic, DBOS (durable
  workflow execution, reuses the same Postgres instance).
- **LLM:** Cerebras `gpt-oss-120b` via Pydantic AI.
- **Flights:** SearchApi.io Google Flights structured responses, or recorded fixtures.
- **Activities:** Tavily web search.
- **Frontend:** React 19 + Vite + Tailwind CSS v4, TypeScript. A structured trip form drives the
  agent; a live activity feed polls for its tool calls on the trip page, and a separate
  execution panel pages through run traces for owned trips. A "Your trips" tab lists the
  signed-in user's trips.

Live-provider operation requires accounts and API credentials for the configured services.
Availability, pricing, and quotas are controlled by those providers and can change.

## Running it

| Role | Available views |
| --- | --- |
| Traveler | Plan a trip, Your trips |
| Trip planner | Plan a trip, Your trips, Agent execution history, Approval history |
| Security operator | Connectors, Security monitoring (verified MFA required) |
| Platform operator | Security monitoring (verified MFA required) |
| Admin | All views; Connectors and Security monitoring require verified MFA |

The enforced deployment uses `compose.zero-trust.yml`. It builds the frontend and backend,
serves the browser application through an HTTPS gateway, and keeps the API and PostgreSQL
ports private. Docker with Compose and OpenSSL are required. The original `docker-compose.yml`
starts only a loopback development database; it does not provide the certificate gateway or
restricted application role. Existing development database volumes are not copied into the
isolated stack automatically.

### 1. Configure the environment

From the repository root:

```bash
cp .env.example .env
```

Fill in `CEREBRAS_API_KEY`, `SEARCHAPI_API_KEY`, and `TAVILY_API_KEY`. Add these four settings
to the root `.env`, using a different random value for each:

| Setting | Purpose |
|---|---|
| `OWNER_DATABASE_PASSWORD` | Administrative database access for provisioning and migrations |
| `RUNTIME_DATABASE_PASSWORD` | Restricted database access used by the running API and DBOS |
| `ZERO_TRUST_SIGNING_SECRET` | Signs application access tokens and keeps them valid across restarts |
| `DEVICE_GATEWAY_SECRET` | Authenticates the gateway's certificate-verification headers to the API |

Generate each value separately with `openssl rand -hex 32`. Use the resulting hex strings
without adding them to source control. Hex avoids special-character escaping in the database
URL and gateway configuration. Compose supplies the container database URLs and sets
`FRONTEND_ORIGIN=https://localhost:8443` for this deployment.

### 2. Issue and import device certificates

An administrator must first confirm the account's registered device ID. Issue a certificate
for that exact ID from the repository root:

```bash
python3 deploy/issue-device.py <registered-device-id>
```

The script stores the local certificate authority and signing key in the ignored
`.device-authority/` directory. Keep that directory private. For the synthetic walkthrough,
issue `device-a-traveler` and `device-a-operator` as shown in the [demo commands](#zero-trust-demo).

Import the device's `.p12` file into the browser's client-certificate store, using the password
in its matching `.password` file. Trust `ca.crt` for the local HTTPS server. Keep private keys
and password files private, and never distribute `ca.key`: anyone holding that key could issue
another trusted device certificate. The gateway receives only the CA certificate and its own
server certificate and key.

The gateway validates the client certificate and overwrites device-identity headers. The API
checks the gateway secret and matches the certified device ID to the account or session during
login, MFA, and protected requests. A copied access token alone cannot satisfy this boundary.

### 3. Start the isolated stack

On Windows PowerShell, run Docker Desktop with Linux containers and use the repository root.
If Git for Windows supplies OpenSSL, add it to this terminal's path before issuing certificates:

```powershell
$env:Path = "C:\Program Files\Git\usr\bin;$env:Path"
py deploy/issue-device.py device-a-traveler
py deploy/issue-device.py device-a-operator
docker compose -f compose.zero-trust.yml up --build -d
docker compose -f compose.zero-trust.yml run --rm migrate python -m scripts.seed_security_demo
```

Complete the environment configuration above first. Skip certificate issuance for devices already
issued. Import the traveler's `.p12` into Current User / Personal and the local `ca.crt` into
Current User / Trusted Root Certification Authorities, then visit `https://localhost:8443`.
Add the demo TOTP setup secret to an authenticator app. The sign-in form takes its generated
six-digit code, not the setup secret.

### 4. Enroll accounts and verify access

Ordinary accounts must already exist with the intended tenant, role, and device assignment.
A trusted database operator enrolls an existing account with:

```bash
sh deploy/enroll-identity.sh \
  --email <existing-account-email> --provisioning-file enrollment-uri
```

The command prompts for a password and writes a unique authenticator provisioning URI to
`.identity-provisioning/enrollment-uri`. Transfer it securely to the account owner, import it
into an authenticator, and remove the file after enrollment. Provisioning preserves ownership and
policy and revokes existing sessions.
For a password-enrolled account whose shared MFA secret was retired, add `--reset-mfa`
to rotate its authenticator while preserving its password.

The [synthetic seed command](#zero-trust-demo) is only for a disposable demonstration: its
accounts deliberately use public passwords and authenticator secrets. Do not use those
identities for a real deployment.

Open `https://localhost:8443` with the registered client certificate, then sign in and complete
MFA. Tenant security operators and admins see their own tenant's security evidence. The separate
`platform-operator` role can investigate cross-tenant events and incidents, including attacks
that could not be attributed to an authenticated account. Assign that role only through trusted
administrative account management.

From the repository root, check the deployed boundaries with an issued device ID:

```bash
sh deploy/check-boundaries.sh <registered-device-id>
```

The script checks gateway-to-API access, blocks gateway-to-database access, checks certificate
admission, and verifies audit protections through the API's runtime database credentials.
The configuration and local certificate issuance have been checked, and a restricted database
login has passed the audit-protection checks and started DBOS in its own schema. Container
builds, deployed network isolation, and the gateway TLS handshake remain unverified in the
current development environment because Docker is unavailable there.

### 5. Tests

```bash
cd backend
uv run pytest -q
uv run pyrefly check
# The suite needs PostgreSQL; the subset that does not is marked and can run without it:
uv run pytest -q -m no_database
```

Use a migrated, disposable PostgreSQL database whose name ends in `_test` or `_testing`,
and set `TEST_DATABASE_URL` to its asyncpg URL. Database tests truncate their tables between
cases; never point them at application data.

See the [validation record](docs/ZERO_TRUST_FINDINGS.md) for dated results and known gaps.

Run the frontend checks separately:

```bash
cd frontend
npm ci
npm test
npm run lint
npm run build
```
