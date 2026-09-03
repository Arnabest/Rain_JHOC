# ADR-0011: Runner, Gate, and Output

- Status: Accepted
- Date: 2026-09-01
- Scope: P13 baseline

## Decision

Runner invokes the action in `ACT` and advances only through `COMPLETION_PENDING`. Its State Store-backed OperationJournal records `STARTED`, `EXECUTED`, or `REQUIRES_RECONCILIATION`: a durable executed operation replays its result without invoking the action, while a crash-window `STARTED` record fails closed to reconciliation. Gate validates task/work, execution output, and side-effect equality before committing `COMPLETE`. Output accepts only a proof digest from Gate and maintains an independent delivery state; send retries never invoke Runner or repeat external side effects. An interrupted sender is persisted as `REQUIRES_RECONCILIATION`; an operator must explicitly resolve it to `DELIVERED` or `FAILED` before any further delivery attempt.
