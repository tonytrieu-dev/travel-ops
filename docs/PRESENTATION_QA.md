### What makes this a zero-trust application?

Every protected request is checked at admission. The gateway verifies the device certificate,
then the application checks the live session, identity, tenant, role, MFA, and ownership before
allowing or denying the request. A request is not trusted just because it came through the network.

### Where do the device certificates come from?

For this local demo, they are created locally with OpenSSL. The first run creates a private local
certificate authority, and each device certificate is signed by it. The browser imports a `.p12`
file containing the device identity and private key; the gateway uses it to verify the device.
That is a demo trust system, not enterprise certificate management.

### What did you actually verify?

I tested the security boundaries, not just the happy path: cross-tenant access is denied,
tampered tokens are rejected, security records are append-only, and repeated denials revoke a
session. The isolated-stack boundary check also showed that an uncertified request is rejected,
the gateway cannot reach PostgreSQL directly, and the runtime role cannot mutate the audit data.

### Why is MFA required for some actions?

The system separates ordinary reading from privileged operations. A password-only session can
perform an ordinary read, but a protected security operation returns “MFA required” until the
user completes TOTP verification. That limits the impact of a stolen or incomplete session.

### What are the main limitations?

This is a zero-trust prototype, not a production certification. It does not include enterprise
identity integration, hardware attestation, managed certificate revocation, an independent
security assessment, or automatic airline purchasing.
