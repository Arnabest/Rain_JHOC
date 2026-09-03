# ADR-0015: Single-Start Persistent Supervisor

## Status

Accepted, 2026-09-02

## Decision

JHOC owns one long-lived `JHOCSupervisor` instance per runtime database. The
application entrypoint starts it exactly once and stops it during shutdown.
The supervisor keeps provider connections and heartbeats, consumes requests
from the native JHOC Relay, invokes the selected provider, and publishes a
correlation-bound response. SQLite response records survive a process restart.

Provider loss does not discard work: a leased request is deferred without
consuming a retry attempt, and is retried after a provider reconnects. A
second supervisor for the same lock path is rejected, including across
processes; stale markers are reclaimed only when their recorded PID is dead.

## Boundary

Relay remains the owner of delivery state (lease, ACK, retry, dead letter).
Supervisor owns connection lifecycle and request/response correlation. It does
not import or proxy the legacy Agent Bus, its database, or its receipt schema.
Governance readiness still requires accepted provider results; supervisor
health or transport ACK alone cannot satisfy the collaboration gate.

## Verification

`tests/test_supervisor.py` covers idempotent start, persistent provider use,
explicit provider routing, reconnect-safe deferral, durable responses, and
duplicate-start rejection. Full suite: 166 tests and 7 subtests passed.
