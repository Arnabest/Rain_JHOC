# ADR-0005: Core, Storage, and Lens Boundaries

- Status: Accepted
- Date: 2026-09-01
- Scope: P6 baseline

## Decision

JHOC Core owns local store instances and observability wiring. State is owner-scoped and compare-and-swap versioned; Event Store is append-only and idempotent; Artifact Store is content-addressed and returns owner-bound references. No module may mutate another owner's state directly.

Lens keeps logs, events, audits, and evidence in separate physical routes. Every log can carry task/work/message/trace/component/plugin/policy/capability correlation fields. Sensitive field names are redacted recursively before storage. A separate correlation timeline reconstructs the ordered task/work/trace chain without merging the physical record tables.

## Consequences

Durable mode uses SQLite State/Event/Artifact stores and SQLite Lens tables. Application restart tests cover owner-scoped state, append-only events, content-addressed artifacts, redacted Lens records, and full correlated trace reconstruction.
