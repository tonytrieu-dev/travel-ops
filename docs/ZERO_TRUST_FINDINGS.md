# Zero-trust findings

TravelOps is a zero-trust prototype. Flight search is deterministic and does not alter the request
boundary, booking state machine, or audit controls.

## Current controls

- Protected requests validate signed session, tenant, role, device, ownership, and MFA policy.
- Security decisions and booking/execution evidence are append-only at the database boundary.
- Repeated denials trigger incident creation and session containment.
- The enforced Compose deployment uses mutual TLS and private application/database networks.
- Flight search uses a provider strategy: live SearchApi or recorded real-response fixtures.
- Booking remains a human-approved handoff to a provider checkout link; the application does not
  purchase or claim to hold a fare.

## Remaining limits

This is not production certification. Enterprise identity, hardware attestation, managed
certificate revocation, independent assessment, fare holds, and airline purchasing remain out of
scope. See [ARCHITECTURE.md](ARCHITECTURE.md) for the current component and data-flow model.
