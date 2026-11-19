# Presentation Q&A

Use these as short spoken answers. The demo is an eight-minute presentation, so answer the
question directly and stop unless someone asks for more detail.

## Primary questions

### 1. How are the device certificates created, and where do they come from?

They are created locally by `deploy/issue-device.py` with OpenSSL. The first run creates a
private, local certificate authority; each later run creates a device key and certificate signed
by that authority. This demo does not use a public certificate provider. The CA private key is
kept separately in `.device-authority`, while the browser gets a device `.p12` bundle.

### 2. What do the local CA and browser `.p12` files do?

The local CA is the trust anchor: the gateway trusts certificates signed by it. The `.p12` file
bundles one device's private key, certificate, and CA certificate so the browser can present that
device identity during mutual TLS. Its matching `.password` file protects the import. The gateway
checks the certificate before forwarding API traffic, and the backend checks the gateway's
secret-authenticated verification headers before accepting the device identity.

### 3. Is a certificate alone enough to access the system?

No. It proves possession of the registered device, not that the user is authorized. A protected
request also needs a valid session whose claims still match the database, the right tenant and
role, resource ownership, and MFA when required. The deployment adds private service networks,
so the API and database are not directly exposed to the host.

### 4. What happens if the system crashes during booking?

Booking is gated by a human approval state transition. The booking execution and the external
booking-options lookup run through DBOS durable execution, so the workflow can resume or replay
after a process failure instead of relying on an in-memory task. The application still hands the
user to a carrier or OTA checkout page; it does not buy the ticket or promise a fare hold.

### 5. How do you know what happened, and how repeatable is the demo?

Security decisions, booking transitions, execution events, and monitoring assessments are stored
as append-only audit data. Database triggers reject updates, deletes, and truncation of those
records, and the runtime database role cannot mutate them. Flight search uses either the live
SearchApi provider or recorded real-response fixtures, selected by configuration. Recorded mode
makes tests and demonstrations repeatable without inventing flight results; searches are also
cached for 15 minutes.

## Backup questions

### What are the main limitations?

This is a zero-trust prototype, not a production certification. It does not provide enterprise
identity integration, hardware attestation, managed certificate revocation, an independent
security assessment, fare holds, or airline purchasing. Those are explicit boundaries, not claims
the demo is making.

### What exactly is tested?

The backend has unit and PostgreSQL integration tests for authentication, MFA, tenant and
ownership policy, concurrency, migrations, provider behavior, durable booking paths, and
append-only enforcement. The frontend has Node/jsdom component and API tests plus a production
build. There is not yet a browser end-to-end test suite.

### Why call this zero trust?

Because each protected request is checked against current evidence rather than trusted solely
because it came from the network. The checks include session validity, device identity, tenant,
role, ownership, and MFA. Repeated denials are recorded and can trigger incident creation and
session containment. “Zero trust” here describes the control pattern, not a guarantee that every
enterprise control has been implemented.

### What does the provider strategy buy you?

It keeps application behavior independent of whether the source is live SearchApi data or a
recorded response. The same search service handles validation, caching, ordering, persistence,
and activity logging. That gives a realistic live path and a deterministic path for tests and
presentations without adding an LLM or planner.
