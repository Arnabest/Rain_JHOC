# ADR-0004: Safe Origin, Trust, and Config

- Status: Accepted
- Date: 2026-09-01
- Scope: P5 baseline

## Decision

Origin starts with no model, memory, plugin, network, or legacy-service dependency. It initializes Trust, then an explicit immutable ConfigSnapshot, and exposes health before any provider is registered. Default mode is `OFFLINE`; emergency safe mode permits only L0 local work with no external side effect.

TrustStore holds identities, allow-listed permissions, non-secret key fingerprints, expiring identity-bound sessions, and explicit permission delegations. It does not store tokens, cookies, API keys, or device credentials. Durable mode uses SQLiteTrustStore with revision fencing so a stale writer cannot overwrite newer trust metadata. Config rejects unknown keys and disallows network overrides in offline/safe modes.

## Consequences

In-memory mode remains available for isolated tests. Durable Application restores Trust before Guard policy and general storage, persists only non-secret metadata, and preserves denied-authentication events. Key rotation, revocation, session isolation, delegation, stale-writer rejection, and restart recovery are covered by the P5 matrix.
