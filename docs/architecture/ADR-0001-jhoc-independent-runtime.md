# ADR-0001: JHOC Independent Runtime Boundary

- Status: Accepted baseline
- Date: 2026-09-02
- Scope: JHOC runtime only

## Decision

JHOC is a local-first runtime with native contracts, native State/Event/Artifact/Proof stores, and a native Relay. AIBOX, VERS and the historical Agent Bus are offline migration references only and are not imported, opened, or written by JHOC runtime code.

The application assembly root owns dependency injection. A durable deployment explicitly supplies `ApplicationConfig(storage_path=...)`; the in-memory default is reserved for isolated development and tests. Core, Gate and Output receive one authoritative store set.

## Invariants

- Guard is default-deny and remains authoritative for permission and network decisions.
- Conductor is the only capability selector and cannot bypass Quota.
- Relay owns delivery state only; business state remains with the owning module.
- Gate is the only owner of `COMPLETE`; Output accepts only Gate-recorded evidence.
- Artifacts separate content blobs from owner references.
- Migration scans are read-only and source-hash verified.
- Final cutover requires independent runtime evidence and an Archive Manifest.

## Consequences

Local SQLite is the persistence boundary and can be reopened by a new process. Cross-process Relay leasing uses SQLite transactions. Historical data requires an explicit offline manifest and disposition review before import.

## Rejected Alternatives

- Reusing legacy runtime modules or databases: violates isolation and ownership boundaries.
- Making the Relay own task or evidence business state: creates shared-resource corruption risk.
- Allowing model or Forge output to mutate formal policy: violates governance invariants.
