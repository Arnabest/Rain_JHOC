# ADR-0010: Conductor and Context Boundaries

- Status: Accepted
- Date: 2026-09-01
- Scope: P11/P12 baseline

## Decision

Conductor is the only runtime capability selector. It accepts a Guard decision, filters Registry/Shelf to verified healthy entries, obtains a Quota lease, and returns an explainable selected/rejected/approval plan with one assessment per candidate, including fallback and not-evaluated reasons. Registry and Shelf never dispatch or grant permission.

Context is two-pass. Pass A contains user input, task metadata, and policy reference only. Pass B includes only source IDs explicitly authorized by Guard/Conductor, not expired, and allowed for the named consumer. Each source carries sensitivity, confidence, expiry, allowed consumers, and provenance. Canonical snapshots are content-addressed in State Store and rebuild across durable restart. Context cannot grant permissions, select a final model, execute tools, or write long-term memory.
