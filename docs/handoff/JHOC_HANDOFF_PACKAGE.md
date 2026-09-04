# JHOC Handoff Package

> Handoff package for the next model or engineer taking over `G:\JHOC`.

## 1. Package Status

- Generated: `2026-09-03T00:03:00+08:00`
- Repository: `G:\JHOC`
- Branch: `main`
- Working tree at handoff: clean (formal supervisor, multi-model collaboration closure, and legacy cutover recorded)
- Latest implementation commit: `3e35a32 feat(supervisor): implement persistent single-start supervisor, channel gateway, and native multi-model provider runtime`
- Latest task-archive commit: `8723fd4 chore(acceptance): update V5 acceptance matrix and archive cutover artifacts`
- Machine-readable companion: `docs/handoff/JHOC_HANDOFF_PACKAGE.json`

## 2. Project Objective

JHOC is a local-first, independently rebuilt, plugin-based Agent Harness. The target runtime pipeline is:

```text
input -> intent/risk analysis -> minimal context -> governance
      -> capability/resource orchestration -> authorized context
      -> model/tool execution -> collaboration -> verification/output
      -> memory/knowledge/proof -> controlled evolution
```

JHOC is the only harness runtime. AI Box and Verse Agent may enter through the allowlisted `jhoc.external.v1` ingress, but JHOC imports no AI Box/Verse runtime code and owns the SQLite receipts. VERS remains governance only. The legacy Agent Bus remains a frozen disaster-recovery artifact, not an automatically started route.

## 3. Non-Negotiable Constraints

- Do not reconnect legacy runtime dependencies or import legacy runtime code.
- Do not perform production migration, legacy cleanup, or Cutover without the required approvals.
- Keep formal release gates fail-closed; local evidence is not independent approval.
- Preserve module ownership boundaries and native JHOC contracts.
- Governance/skill rules never enter the capability shelf.
- Background work remains below foreground work.
- Self-evolution produces candidates only; it cannot directly alter the formal runtime.
- Before destructive changes, obtain explicit user confirmation and create a timestamped backup plus op-log.

## 4. Current Build State

### Implemented and accepted

P2-P18 and P20 have executable local evidence. P1 independent review R5, P19 formal import, and P21 USER_CUTOVER_APPROVAL are also closed. The current runtime contains 31 assembly modules, including the allowlisted external channel gateway.

Important durability and boundary work already landed:

- Durable SQLite stores and cross-process transaction/lease handling.
- Relay lease expiry, ACK/NACK, backpressure, dead-letter, replay, crash recovery, and long-run contention evidence.
- Runner operation journal preventing副作用重放.
- Gate two-phase `PENDING -> ACCEPTED` proof acceptance with recovery paths.
- Output CAS delivery state, retry, cross-restart recovery, and explicit `reconcile()` for unknown sender outcomes.
- Migration per-item hash verification, Trust user-session approval binding, StateStore import ledger, resume after partial failure, and symlink/absolute-path rejection.
- Cutover prerequisite validation bound to archive digest, migration manifest hash, and unique entrypoint hash.

### Acceptance status by stage

| Stage | Status | Notes |
|---|---|---|
| P0 | Freeze evidence pass; signature clarification open | Hash-only readonly freeze is verified and the formal record reports `P0_LEGACY_FREEZE=true`; the matrix retains a separate signature follow-up for explicit provenance. |
| P1 | Pass | R5 independent review accepted (codex 92 / gemini 95 / deepseek 92; average 93.0; P0/P1 findings 0). |
| P2-P17 | Pass locally | Command-backed implementation and persistence/fault evidence exists. |
| P18 | Pass locally | 159 tests, 7 Schema subtests, local probes, and artifact validation pass. |
| P19 | Pass formally | Approved 11-item mapping imported through the Trust-bound offline workflow; unapproved items are recorded as REJECT. |
| P20 | Pass locally | Clean-process startup, legacy isolation, and independence checks pass. |
| P21 | Pass formally | Exact archive, migration, entrypoint, and reviewed bindings are approved; formal record is READY with no failed gates. |

## 5. Verification Baseline

Run from `G:\JHOC`:

```powershell
python -m pytest -q
python -m unittest discover -s tests -p 'test_*.py'
python -m compileall -q src tests scripts
python scripts/validate_schemas.py
python scripts/check_independence.py
python scripts/smoke.py
python scripts/generate_runtime_plane_report.py
python scripts/generate_architecture_review.py
python scripts/generate_acceptance_report.py
python scripts/generate_migration_report.py
python scripts/generate_formal_cutover_record.py
python scripts/validate_acceptance_artifacts.py
```

Last verified results:

- `unittest`: `159 tests OK`
- compileall: pass
- Schema validation: `4/4 PASS`
- Independence: pass
- Smoke: `running=True`, `modules=31`, `legacy=False`
- Acceptance artifacts: `validated=true`

## 6. Evidence Map

- Plan: `docs/plan/JHOC_BUILD_PLAN_V5.md`
- Architecture and ownership: `docs/architecture/ARCHITECTURE.md`, `docs/architecture/JHOC_DOMAIN_TRUST_BOUNDARY.md`
- Acceptance matrix: `docs/acceptance/JHOC_V5_ACCEPTANCE_MATRIX.md`
- Runtime evidence: `docs/acceptance/artifacts/jhoc-runtime-plane-report.{json,md}`
- Architecture gate: `docs/acceptance/artifacts/jhoc-architecture-review.{json,md}`
- Migration evidence: `docs/acceptance/artifacts/jhoc-migration-report.{json,md}`
- Local independence/Cutover prerequisites: `docs/acceptance/artifacts/jhoc-independent-cutover-report.{json,md}`
- Formal Cutover record: `docs/acceptance/artifacts/jhoc-formal-cutover-record.{json,md}`
- Legacy readonly freeze: `docs/acceptance/artifacts/jhoc-legacy-readonly-freeze.{json,md}`
- P1 review evidence: `docs/acceptance/evidence/jhoc-p1-boundary-r3/`
- External channel activation: `docs/acceptance/artifacts/jhoc-channel-runtime-activation-20260902.{json,md}`

## 7. Remaining Work

### Remaining work after formal Cutover

1. **P0 freeze-signature resolved**
   - Operator approved the SHA-256 hash manifest (`docs/acceptance/artifacts/jhoc-legacy-readonly-freeze.json`) as the authoritative technical freeze baseline; `P0_LEGACY_FREEZE=true` is officially sealed and matrix updated to PASS.

2. **Handoff synchronization**
   - Commit this refreshed package with the current audit records.
   - Regenerate the package after any approved-binding or reviewed-boundary change.

3. **Multi-model closed-loop dispatch resolved (R1)**
   - Live dispatch completed via 8877 Supervisor (`session-20260902-jhoc-live-collab`); both `agy-cli` and `deepseek-harness` returned verified session-bound accepted final responses with durable SQLite persistence in `runtime/jhoc.db`; R1 updated to PASS.

4. **Optional evidence expansion**
   - Batch process-kill and sender-outcome reconciliation pressure for P13.
   - Broader P12 sensitivity/budget pressure, P14 identity matrices, and long-duration P10 fairness/resource exhaustion probes.

5. **Full migration reconciliation and completeness audit**
   - Full read-only inventory generated at `docs/migration/jhoc-incremental-inventory-20260902.{json,md}`.
   - Inventory covers 13,874 non-private AI Box/Verse files across 9 scopes; all items are 100% classified (`review_required: 0`).
   - Cumulative valid import is 1,864 records (1,676 ProjectMemory + 186 PROJECT_KNOWLEDGE + 2 ErrorMemory), verified with 0 source drift against SQLite stores. 5,157 items retained as reference only on source systems, 6,842 runtime caches excluded, 1 quantum state explicitly quarantined.
   - Full end-to-end reconciliation audit passed and recorded in `docs/migration/jhoc-migration-full-reconciliation-20260902.{json,md}`. Zero source files were modified or deleted.

### Optional evidence expansion (not a substitute for the gates)

- Batch process-kill and sender-outcome reconciliation pressure for P13.
- Broader P12 sensitivity/budget pressure matrix.
- Extended P14 handoff/review cross-identity matrix.
- Long-duration P10 fairness/resource exhaustion probe.
- Fresh P1 review of all local remediations.

## 8. Safe Takeover Procedure

1. Read this file, the acceptance matrix, the V5 plan, and the latest formal Cutover record.
2. Run `git status --short --branch` and verify the tree before editing.
3. Run the verification baseline above before making assumptions about regressions.
4. For each change, document impact (`UP/DOWN/FORK`), update focused tests, then run the full baseline.
5. Regenerate acceptance artifacts after behavior or test-count changes.
6. Commit implementation and documentation separately when practical; keep commit messages specific.
7. Write a session record and op-log, then run `post_task_archive.py` before final handoff.
8. Re-check `git status`; leave the repository clean.

## 9. Stop Conditions

The next model must stop and report instead of proceeding when:

- a requested action would migrate, delete, overwrite, or clean legacy/production data without explicit confirmation;
- a gate depends on an external reviewer or user approval that is not present;
- a test or artifact contradicts the acceptance matrix;
- a change would make JHOC import AI Box/Verse runtime code, share the legacy database, or automatically restart the frozen Agent Bus.

## 10. Handoff Conclusion

The JHOC framework is operationally covered and formally approved for Cutover. The next owner should resolve the P0 signature wording, commit the synchronized handoff records, and preserve the approved bindings; any boundary change requires renewed independent review and formal validation.
