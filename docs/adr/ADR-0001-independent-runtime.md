# ADR-0001: Independent JHOC Runtime

- Status: Accepted
- Date: 2026-09-01
- Scope: P0 freeze

## Decision

JHOC is rebuilt as the only runtime in this repository. AIBOX, VERS, and the legacy Agent Bus remain offline migration/reference sources and are not imported, called, or dual-written by JHOC runtime modules.

## Consequences

- Every runtime boundary uses a versioned native JHOC contract.
- Migration is a later, one-way, read-only-source workflow.
- Compatibility shims are not part of the runtime architecture.
- The repository can be tested with external systems disconnected.

## Acceptance evidence

The initial repository contains no legacy runtime package or dependency. Independence is re-tested at P20 before cutover.

