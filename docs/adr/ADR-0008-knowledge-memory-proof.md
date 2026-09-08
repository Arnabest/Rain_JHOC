# ADR-0008: Knowledge, Memory, Graph, and Proof Planes

- Status: Accepted
- Date: 2026-09-01
- Scope: P9 baseline

## Decision

Atlas owns knowledge content and lifecycle. Graph stores only verified relationship projections and never owns source content. Memory writes require an explicit write-gate approval. Proof stores immutable evidence packages and separate audit records; evidence includes task/work/policy/capability, expected/execution/verification, side-effect status, and references.

## Consequences

Atlas, Graph, Memory, and Proof each have isolated SQLite stores and are wired into the durable application assembly. Restart tests cover content lifecycle, verified relationship projections, gated memory writes, immutable evidence, and audit recovery. AIBOX/VERS data is not imported implicitly; offline migration requires source revalidation, quarantine, structural and semantic validation, and explicit per-item approval, preserving these ownership boundaries.
