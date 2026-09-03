# JHOC Restore Runbook

## Scope

This runbook restores a verified local SQLite snapshot into a new target. It never overwrites an existing target and it does not reconnect legacy services.

## Procedure

1. Stop the JHOC process that owns the source database.
2. Create a snapshot with `RecoveryManager.snapshot_database(source, destination_dir, snapshot_id=...)`.
3. Verify the snapshot SHA-256 and byte size with `RecoveryManager.verify_snapshot` in a fresh process.
4. Restore to a new path with `RecoveryManager.restore_database`; an existing target must fail closed.
5. Start JHOC in `EMERGENCY_SAFE_MODE` if identity, policy, or storage validation is still pending.
6. Inspect `RecoveryManager.audit_records()` and attach the operation IDs to the change record.
7. Re-run the full verification baseline before returning to normal mode.

## Failure and rollback

An integrity mismatch or existing target is a failed operation. Keep the source and snapshot untouched, preserve the failed audit record, and choose a new target path after correcting the source of the mismatch. Do not delete or replace a snapshot as part of recovery.

## Evidence

`docs/acceptance/artifacts/jhoc-runtime-plane-report.json` contains a deterministic snapshot/restore probe and audit count. This is local evidence and does not replace an operator-approved incident record.
