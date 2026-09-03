# ADR-0013: Acceptance, Migration, and Cutover

- Status: Accepted
- Date: 2026-09-01
- Scope: P18-P21 baseline

## Decision

P18 acceptance is evidence-driven. P19 Ingest is read-only and creates a quarantined, hashed manifest before any disposition. P20 independence scans runtime source for forbidden legacy dependencies. P21 cutover is fail-closed until every named gate, migration completion, and independence report passes.

The offline preparation boundary is implemented by `jhoc.ingest.OfflineMigration`. It re-verifies the source hash, rejects implicit `QUARANTINE` dispositions, copies files one at a time into an explicit quarantine directory, validates JSON migration candidates against a small type/sensitivity/source/content contract, and records the prepared content SHA-256. `MIGRATE` and `TRANSFORM` items with invalid structure or semantics remain quarantined; `REFERENCE_ONLY` and `ARCHIVE` items never enter runtime stores. Runtime-store writes belong to `ApprovedMigrationImporter`, which requires a Trust-authorized user session and an approval bound to the manifest, path, prepared hash, type and owner store. A per-item StateStore ledger makes partial imports resumable and idempotent.

Final cutover evidence records the reviewed migration manifest hash, a canonical Archive Manifest digest and a revalidated SHA-256 proof for the exact installed `jhoc.entrypoint:create_application` source. `CutoverValidator.validate_final` also requires a Trust-authorized user session approval bound to the archive digest, migration hash and entrypoint hash. Missing or mismatched evidence remains fail-closed.
