# ADR-0006: Relay Delivery Semantics

- Status: Accepted
- Date: 2026-09-01
- Scope: P7 baseline

## Decision

Relay owns only message delivery state. It provides at-least-once local delivery with priority ordering, consumer leases, matching ACKs, bounded NACK retries, lease-expiry recovery, dead letters, cancellation, and explicit replay. Duplicate message IDs with identical envelopes are idempotent; changed envelopes are conflicts.

## Boundary

Relay never mutates task, memory, knowledge, capability, or evidence business state and never re-executes an external side effect. It coordinates delivery only; consumers own execution and must use JHOC Flow idempotency and Gate semantics.

## Consequences

JHOC provides both an in-memory Relay and `SQLiteRelay`. The SQLite implementation persists delivery state, uses transactional leases across independent connections/processes, recovers expired leases after process exit, enforces optional pending-message backpressure, and preserves ACK/NACK/dead-letter/cancel/replay semantics across restart. Relay still does not own consumer business state or side-effect reconciliation.
