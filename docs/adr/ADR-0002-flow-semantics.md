# ADR-0002: Unified Flow Semantics

- Status: Accepted
- Date: 2026-09-01
- Scope: P3 Flow baseline

## Decision

JHOC work follows one explicit state machine. State writes carry a monotonically increasing version and may include an expected version; stale writes are rejected. Only Gate may commit `COMPLETE` from `COMPLETION_PENDING`.

Retry is bounded and deterministic. Unknown or partial external side effects never auto-retry; they produce `RECONCILE`. Idempotency claims are keyed by a canonical request fingerprint; reuse with different input is a hard conflict. Cancellation is one-way and observable by every participant.

## State ownership

- Runner owns operational transitions through `COMPLETION_PENDING`.
- Guard may block work, but does not complete it.
- Gate owns acceptance into `COMPLETE`.
- Relay owns delivery attempts and leases; Flow continues to own only work-state semantics.

## Consequences

The state machine remains storage-agnostic. Durable execution is layered through the State Store-backed `OperationJournal`, which records `STARTED`, `EXECUTED`, and `REQUIRES_RECONCILIATION` states. A replay after restart returns the recorded result without repeating a completed side effect; an uncertain crash window is fail-closed into reconciliation. The lightweight `IdempotencyRegistry` remains process-local and is not the authoritative boundary for Runner side effects.
