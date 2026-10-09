# ADR-0009: V0 browser device and session credentials

**Status:** Accepted for V0 design; implementation and platform tests pending.  
**Date:** 2026-10-04.

## Context

User, Device and Session are separate identities. User proof alone cannot authorize an unapproved endpoint. ADR-0007 requires invalidated sessions to remain invalid after restoration/replay. Responsive browsers must authenticate without cloud identity and support current device-wide revocation, including localhost and long-running delivery.

## Alternatives

Network identity alone is inadequate for local/offline and replaceable transport. A passphrase alone lacks approved endpoint proof; a device credential alone does not supply fresh owner evidence. Passkeys may authenticate a user but synced credentials do not alone identify the separately approved endpoint. Hardware-backed WebAuthn/client TLS certificates need additional client/custody evidence. Self-contained signed sessions still need a live revocation check and add key/claim complexity without an independent verifier use case.

## Decision

Authenticate the single owner using a locally verified passphrase, without a username namespace or external sign-in. Store a salted Argon2id verifier. Require a separately approved, server-generated 256-bit random browser device credential and a fresh independent 256-bit opaque session identifier. Retain purpose-bound verifiers and authoritative associations on the server; session signature validity is not the access authority.

Carry device/session proofs in separate Secure, HttpOnly, SameSite=Strict host-only `__Host-` cookies. Both proofs must match current owner/device/credential generation/session state. Use synchronizer CSRF tokens, exact origin validation, no cross-origin API access and no secrets in JavaScript storage or URLs. Browser-managed cookies are copyable endpoint proof, not physical hardware identity.

Permit distinct enrolled browser-profile credentials for an explicitly owner-associated Device; each profile has its own session and ordinary tabs share it. Device revocation covers all profiles/sessions. New profiles are never associated automatically by name/address. Apply finite device proof validity and explicit replacement/enrollment.

Select server-side session defaults of eight-hour absolute and thirty-minute idle expiry, bounded to one–eight hours and five–thirty minutes respectively. Background polling/output cannot extend idle validity. No silent refresh: fresh owner authentication creates a new session and terminally invalidates the profile's predecessor. Logout/session revocation affects only its target; device revocation affects all dependent authority. Sensitive management requires fresh action-bound passphrase evidence.

On restart, advance a durable access boot generation before readiness and invalidate earlier sessions/ceremonies. Within a boot, enforce monotonic deadlines; suspend/resume or ambiguous clock evidence requires reauthentication. A durable security-time floor and terminal observed credential expiry prevent persistent device-proof age from regressing across restart; ambiguous time denies new authority. Cookie restoration, client timezone and message commit time cannot revive authority. Existing admitted generation may finish/save privately after expiry; delivery needs current permission.

## Consequences

Opaque sessions suit one authoritative server and immediate revocation. Reauthentication and browser credential loss create some user friction. Theft of current cookies can impersonate an endpoint until invalidation; HttpOnly is not protection from all same-origin compromise. Actual cookie/cache/CSRF behavior, OS clock detection and resource parameters require tests. No hardware-backed storage or multi-factor assurance is claimed.

Windows server usable secrets use user-scoped DPAPI under a dedicated service account with restrictive ACLs; verifiers/security state stay under C08. Browser code does not select the underlying OS cookie store. Actual disk/profile/copy protections and independent key custody remain deployment prerequisites, not proof provided by this ADR.

## Affected documents

The [evaluation sections 5–6, 8 and 12–15](../evaluations/v0-access-security-mechanisms.md) define parameters, alternatives, sources and tests. This resolves mechanism portions of SD-01/03/06/07 in [security](../07-security.md) while preserving [logical model](../05-data-model.md) User/Device/Session relationships, CB-07 and ADR-0007. No schema, API route, framework or token encoding is selected.
