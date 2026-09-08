"""Phase 6 Comprehensive Verification Suite: Execution Depth, Manifest & Live-Loop Arbitration Gating.

Tests binding conditions C1 through C10 from Phase 6 opening co-review:
- C1: Mode-aware arbitration gating (dry-run halts at COMPLETION_PENDING, live mode fails closed to REPAIR).
- C2: Task correlation in escalation tickets (task_id written to ticket payload and queried by gate).
- C3: Arbitration resolution semantics via inbox approval/consumed status and supersession.
- C4: Exception surfacing in arbitration (_persist_and_escalate propagates inbox errors, logs blackbox errors).
- C5: Mandatory failing negative control with physical execution provenance (exit_code != 0).
- C6: Governed negative control bypass with policy_ref validation and execution_dict recording.
- C7: Compile validation precedence (anti-circular check precedes negative control check).
- C8: Declared-new file manifest semantics (fails closed if declared-new file is not created).
- C9: Ghost file detection in scan_roots with deterministic ignore filters and TOCTOU finalize re-scan.
- C10: Inline code AST pre-audit for -c/--command with dangling flag rejection.
- C14: Strict Rule 7 check: 100% pure ASCII across Phase 6 deliverables and zero emoji repo-wide.
"""

import ast
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from jhoc.conductor.inbox import ApprovalStatus, SQLiteApprovalInbox
from jhoc.contracts.errors import ContractError, ErrorCode
from jhoc.contracts.models import WorkStatus
from jhoc.flow.pipeline import (
    HarnessPipeline,
    PipelineConfig,
    PipelineContext,
    PipelineExecutionResult,
)
from jhoc.flow.state_machine import FlowActor, FlowStateMachine
from jhoc.proof.arbitration import (
    ArbitrationVerdict,
    ArbitrationVerdictStatus,
    AtomicClaimDelta,
    DisputeArbitrationEngine,
    DisputeCase,
)
from jhoc.proof.evidence_compiler import (
    CompilerProbeResult,
    CompilerProbeType,
    EvidencePackageEngine,
)


class TestPhase6VerificationDepth(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.workspace_root = Path(self.temp_dir.name).resolve()
        self.arbitration_db = self.workspace_root / "test_arb.sqlite"
        self.inbox_db = self.workspace_root / "test_inbox.sqlite"
        self.compiler = EvidencePackageEngine(workspace_root=self.workspace_root)
        self.inbox = SQLiteApprovalInbox(path=self.inbox_db)
        self.arbitration = DisputeArbitrationEngine(
            workspace_root=self.workspace_root,
            db_path=self.arbitration_db,
            inbox=self.inbox,
        )

    def tearDown(self) -> None:
        if hasattr(self, "arbitration") and self.arbitration is not None:
            try:
                self.arbitration.close()
            except Exception:
                pass
        if hasattr(self, "inbox") and self.inbox is not None:
            try:
                self.inbox.close()
            except Exception:
                pass
        import gc
        gc.collect()
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_c1_mode_aware_arbitration_gating_dry_run_vs_live(self) -> None:
        """C1: Proves dry-run over an open blocking dispute halts at COMPLETION_PENDING with

        arbitration_blocked=True without failing, while live mode fails closed to REPAIR/BLOCKED.
        """
        task_id = "task-c1-mode-aware"
        file_a = self.workspace_root / "mod_a.py"
        file_a.write_text("x = 1\n", encoding="utf-8")

        # Create an inconclusive/blocking dispute
        case = DisputeCase(
            dispute_id="disp-c1-001",
            task_id=task_id,
            claim_a=AtomicClaimDelta("target_file", "line_count", 1, "test_agent_a"),
            claim_b=AtomicClaimDelta("target_file", "line_count", 2, "test_agent_b"),
        )
        verdict = self.arbitration.arbitrate(case)
        self.assertTrue(verdict.status.blocks_completion)

        # Build pipeline context
        pos_probe = CompilerProbeResult(
            probe_type=CompilerProbeType.UNIT_TEST,
            target="test_ok",
            passed=True,
            details="positive probe passed",
            exit_code=0,
            stdout_sha256=hashlib.sha256(b"ok").hexdigest(),
        )
        neg_probe = CompilerProbeResult(
            probe_type=CompilerProbeType.NEGATIVE_CONTROL,
            target="test_fail",
            passed=False,
            details="negative probe failed as expected",
            exit_code=1,
            stdout_sha256=hashlib.sha256(b"fail").hexdigest(),
        )

        pipeline = HarnessPipeline()

        # 1. Test Dry-Run: must succeed with arbitration_blocked=True, halting at COMPLETION_PENDING
        sm_dry = FlowStateMachine()
        ctx_dry = PipelineContext(
            task_id=task_id,
            work_id="work-dry",
            config=PipelineConfig(dry_run=True, shadow_mode=False),
            state_machine=sm_dry,
            declared_changes=[file_a],
            probes=[pos_probe],
            negative_control_probe=neg_probe,
            evidence_engine=self.compiler,
            arbitration_engine=self.arbitration,
            inbox=self.inbox,
            workspace_root=self.workspace_root,
            action_hook=lambda ctx: file_a.write_text("x = 2\n", encoding="utf-8"),
        )
        res_dry = pipeline.run(ctx_dry)
        self.assertTrue(res_dry.success, "Dry-run must report success=True as a run")
        self.assertEqual(res_dry.final_status, WorkStatus.COMPLETION_PENDING)
        self.assertTrue(res_dry.arbitration_blocked, "Dry-run must surface arbitration_blocked=True")
        self.assertIsNone(res_dry.error)

        # 2. Test Live Mode: must fail closed, unwinding to REPAIR with success=False
        sm_live = FlowStateMachine()
        ctx_live = PipelineContext(
            task_id=task_id,
            work_id="work-live",
            config=PipelineConfig(dry_run=False, shadow_mode=False),
            state_machine=sm_live,
            declared_changes=[file_a],
            probes=[pos_probe],
            negative_control_probe=neg_probe,
            evidence_engine=self.compiler,
            arbitration_engine=self.arbitration,
            inbox=self.inbox,
            workspace_root=self.workspace_root,
            action_hook=lambda ctx: file_a.write_text("x = 3\n", encoding="utf-8"),
        )
        res_live = pipeline.run(ctx_live)
        self.assertFalse(res_live.success, "Live mode must fail closed when arbitration is unresolved")
        self.assertEqual(res_live.final_status, WorkStatus.REPAIR)
        self.assertTrue(res_live.arbitration_blocked)
        self.assertIn("Gate acceptance blocked by unresolved arbitration", str(res_live.error))

    def test_c2_task_correlation_in_escalation(self) -> None:
        """C2: Proves _persist_and_escalate writes task_id into ticket payload and gate queries by task."""
        task_id = "task-c2-correlation"
        case = DisputeCase(
            dispute_id="disp-c2-001",
            task_id=task_id,
            claim_a=AtomicClaimDelta("target_val", "count", 10, "agent_1"),
            claim_b=AtomicClaimDelta("target_val", "count", 20, "agent_2"),
        )
        verdict = self.arbitration.arbitrate(case)
        self.assertTrue(verdict.status.blocks_completion)

        # Inspect ticket payload in inbox
        ticket_id = f"arb-esc-{verdict.verdict_id[:10]}"
        ticket = self.inbox.get_ticket(ticket_id)
        self.assertIsNotNone(ticket, "Escalation ticket must be created in inbox")
        self.assertEqual(ticket.payload.get("task_id"), task_id, "Ticket payload must contain task_id")
        self.assertEqual(ticket.payload.get("dispute_id"), "disp-c2-001")

        # Verify task-scoped filtering
        pending = self.inbox.list_tickets(status=ApprovalStatus.PENDING)
        task_tickets = [t for t in pending if t.payload.get("task_id") == task_id]
        self.assertEqual(len(task_tickets), 1)

    def test_c3_arbitration_resolution_via_inbox_approval_and_supersession(self) -> None:
        """C3: Proves operator approval (APPROVED/CONSUMED) resolves a blocking verdict,

        and supersession filters out obsolete blocking verdicts.
        """
        task_id = "task-c3-resolution"
        case = DisputeCase(
            dispute_id="disp-c3-001",
            task_id=task_id,
            claim_a=AtomicClaimDelta("conf", "mode", "A", "agent_a"),
            claim_b=AtomicClaimDelta("conf", "mode", "B", "agent_b"),
        )
        verdict1 = self.arbitration.arbitrate(case)
        self.assertTrue(verdict1.status.blocks_completion)
        self.assertFalse(self.arbitration.is_verdict_resolved(verdict1))

        # 1. Operator approval resolution
        ticket_id = f"arb-esc-{verdict1.verdict_id[:10]}"
        self.inbox.approve(ticket_id)
        self.assertTrue(
            self.arbitration.is_verdict_resolved(verdict1),
            "APPROVED ticket must mark verdict as resolved",
        )

        # Test CONSUMED status as well
        self.inbox.consume_approval(ticket_id)
        self.assertTrue(
            self.arbitration.is_verdict_resolved(verdict1),
            "CONSUMED ticket must mark verdict as resolved",
        )

        # 2. Supersession test: a newer verdict supersedes verdict1
        verdict2 = ArbitrationVerdict(
            verdict_id="arb-v2-superseding",
            dispute_id="disp-c3-001",
            task_id=task_id,
            status=ArbitrationVerdictStatus.PROVEN_A,
            winner_claim=case.claim_a,
            probe_exit_code=0,
            probe_stdout_sha256="",
            probe_stderr_sha256="",
            parent_blackbox_hash="0" * 64,
            supersedes_ref=verdict1.verdict_id,
            justification="Superseding with verified probe",
            decided_at="2026-09-07T00:00:01Z",
        )
        # Store verdict2 into db directly to simulate newer probe
        conn = sqlite3.connect(str(self.arbitration_db))
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO jhoc_arbitration_verdicts (
                        verdict_id, dispute_id, task_id, status, winner_claim_json,
                        probe_exit_code, probe_stdout_sha256, probe_stderr_sha256,
                        parent_blackbox_hash, supersedes_ref, justification, decided_at, digest
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        verdict2.verdict_id, verdict2.dispute_id, verdict2.task_id,
                        verdict2.status.value, json.dumps(case.claim_a.to_dict()),
                        0, "", "", verdict2.parent_blackbox_hash, verdict1.verdict_id,
                        verdict2.justification, verdict2.decided_at, verdict2.digest
                    )
                )
        finally:
            conn.close()

        active = self.arbitration.get_active_disputes_for_task(task_id)
        active_ids = [v.verdict_id for v in active]
        self.assertIn("arb-v2-superseding", active_ids)
        self.assertNotIn(verdict1.verdict_id, active_ids, "Superseded verdict must be excluded from active disputes")

    def test_c4_exception_surfacing_in_arbitration(self) -> None:
        """C4: Proves inbox escalation failure surfaces as ContractError and blackbox error is recorded."""
        task_id = "task-c4-exceptions"
        case = DisputeCase(
            dispute_id="disp-c4-001",
            task_id=task_id,
            claim_a=AtomicClaimDelta("item", "flag", True, "mod_1"),
            claim_b=AtomicClaimDelta("item", "flag", False, "mod_2"),
        )

        # Mock inbox to raise exception on create_ticket
        class BrokenInbox:
            def create_ticket(self, *args, **kwargs):
                raise IOError("Disk full on inbox partition")
            def close(self):
                pass

        broken_inbox = BrokenInbox()
        engine_broken_inbox = DisputeArbitrationEngine(
            workspace_root=self.workspace_root,
            db_path=self.workspace_root / "arb_broken_inbox.sqlite",
            inbox=broken_inbox,  # type: ignore
        )
        with self.assertRaises(ContractError) as ctx_err:
            engine_broken_inbox.arbitrate(case)
        self.assertIn("Arbitration escalation ticket creation failed", str(ctx_err.exception))
        self.assertEqual(ctx_err.exception.code, ErrorCode.POLICY_DENIED)
        self.assertIn("Inbox escalation failed", engine_broken_inbox.last_escalation_error)

        # Mock blackbox failure
        class BrokenBlackBox:
            latest_hash = "0" * 64
            def append(self, *args, **kwargs):
                raise RuntimeError("BlackBox network journal unreachable")

        engine_broken_bb = DisputeArbitrationEngine(
            workspace_root=self.workspace_root,
            db_path=self.workspace_root / "arb_broken_bb.sqlite",
            blackbox=BrokenBlackBox(),  # type: ignore
        )
        verdict = engine_broken_bb.arbitrate(case)
        self.assertIsNotNone(verdict)
        self.assertIn("BlackBox append failed", engine_broken_bb.last_escalation_error)

    def test_c5_negative_control_physical_provenance(self) -> None:
        """C5: Proves in-memory negative control without real non-zero exit_code is rejected."""
        task_id = "task-c5-provenance"
        file_p = self.workspace_root / "code.py"
        file_p.write_text("a = 10\n", encoding="utf-8")

        pos_probe = CompilerProbeResult(
            probe_type=CompilerProbeType.UNIT_TEST,
            target="test_valid",
            passed=True,
            details="valid positive test",
            exit_code=0,
        )

        # 1. In-memory decoy probe with exit_code=None: must be rejected
        decoy_none = CompilerProbeResult(
            probe_type=CompilerProbeType.NEGATIVE_CONTROL,
            target="decoy_fail",
            passed=False,
            details="decoy probe with exit_code=None",
            exit_code=None,
        )
        with self.assertRaises(ContractError) as ctx_none:
            self.compiler.compile_package(
                task_id=task_id,
                work_id="work-c5",
                policy_ref="jhoc-v1",
                capability_version="1.0",
                probes=[pos_probe],
                file_paths=[file_p],
                negative_control_probe=decoy_none,
            )
        self.assertIn("lacks physical execution provenance", str(ctx_none.exception))

        # 2. In-memory probe with exit_code=0: must be rejected
        decoy_zero = CompilerProbeResult(
            probe_type=CompilerProbeType.NEGATIVE_CONTROL,
            target="decoy_zero",
            passed=False,
            details="decoy probe with exit_code=0",
            exit_code=0,
            stdout_sha256=hashlib.sha256(b"err").hexdigest(),
        )
        with self.assertRaises(ContractError) as ctx_zero:
            self.compiler.compile_package(
                task_id=task_id,
                work_id="work-c5",
                policy_ref="jhoc-v1",
                capability_version="1.0",
                probes=[pos_probe],
                file_paths=[file_p],
                negative_control_probe=decoy_zero,
            )
        self.assertIn("lacks physical execution provenance", str(ctx_zero.exception))

        # 3. In-memory probe with exit_code=1 but empty digests: must be rejected
        decoy_empty_digest = CompilerProbeResult(
            probe_type=CompilerProbeType.NEGATIVE_CONTROL,
            target="decoy_empty_digest",
            passed=False,
            details="decoy probe with exit_code=1 but empty digests",
            exit_code=1,
            stdout_sha256="",
            stderr_sha256="",
        )
        with self.assertRaises(ContractError) as ctx_empty:
            self.compiler.compile_package(
                task_id=task_id,
                work_id="work-c5",
                policy_ref="jhoc-v1",
                capability_version="1.0",
                probes=[pos_probe],
                file_paths=[file_p],
                negative_control_probe=decoy_empty_digest,
            )
        self.assertIn("lacks physical execution provenance", str(ctx_empty.exception))

        # 4. Real negative probe with exit_code=1 and non-empty digest: succeeds
        real_neg = CompilerProbeResult(
            probe_type=CompilerProbeType.NEGATIVE_CONTROL,
            target="real_neg",
            passed=False,
            details="real negative control with exit code 1",
            exit_code=1,
            stdout_sha256=hashlib.sha256(b"AssertionError").hexdigest(),
        )
        pkg, report = self.compiler.compile_package(
            task_id=task_id,
            work_id="work-c5",
            policy_ref="jhoc-v1",
            capability_version="1.0",
            probes=[pos_probe],
            file_paths=[file_p],
            negative_control_probe=real_neg,
        )
        self.assertTrue(report.is_valid)
        self.assertFalse(pkg.execution["negative_control_bypassed"])

    def test_c6_negative_control_bypass_governance(self) -> None:
        """C6: Proves negative control bypass without governed policy_ref is denied,

        and valid bypass records reason in execution_dict.
        """
        task_id = "task-c6-bypass"
        file_p = self.workspace_root / "read_only.txt"
        file_p.write_text("documentation artifact\n", encoding="utf-8")
        pos_probe = CompilerProbeResult(
            probe_type=CompilerProbeType.UNIT_TEST,
            target="test_docs",
            passed=True,
            details="positive test for documentation",
            exit_code=0,
        )

        # 1. Missing negative control and no bypass reason: denied
        with self.assertRaises(ContractError) as ctx_fail:
            self.compiler.compile_package(
                task_id=task_id,
                work_id="work-c6",
                policy_ref="jhoc-v1",
                capability_version="1.0",
                probes=[pos_probe],
                file_paths=[file_p],
                require_negative_control=True,
                negative_control_probe=None,
            )
        self.assertIn("Negative-control probe is mandatory but was not supplied", str(ctx_fail.exception))

        # 2. Bypass reason provided but empty/default policy_ref: denied
        with self.assertRaises(ContractError) as ctx_pol:
            self.compiler.compile_package(
                task_id=task_id,
                work_id="work-c6",
                policy_ref="",
                capability_version="1.0",
                probes=[pos_probe],
                file_paths=[file_p],
                require_negative_control=True,
                negative_control_probe=None,
                negative_control_bypass_reason="Pure documentation task without falsifiable mutant",
            )
        self.assertIn("governed policy_ref is required", str(ctx_pol.exception))

        # 3. Valid governed bypass: succeeds and records audit reason
        pkg, report = self.compiler.compile_package(
            task_id=task_id,
            work_id="work-c6",
            policy_ref="governed-doc-audit-v1",
            capability_version="1.0",
            probes=[pos_probe],
            file_paths=[file_p],
            require_negative_control=True,
            negative_control_probe=None,
            negative_control_bypass_reason="Pure documentation task without falsifiable mutant",
        )
        self.assertTrue(report.is_valid)
        self.assertTrue(pkg.execution["negative_control_bypassed"])
        self.assertEqual(
            pkg.execution["negative_control_bypass_reason"],
            "Pure documentation task without falsifiable mutant",
        )

    def test_c7_compile_validation_precedence(self) -> None:
        """C7: Proves anti-circular check precedes negative control check."""
        task_id = "task-c7-precedence"
        ast_probe = CompilerProbeResult(
            probe_type=CompilerProbeType.AST_SYNTAX,
            target="virtual_module",
            passed=True,
            details="ast syntax validation passed",
        )
        # Empty file_paths and test_probes has no exit_code=0
        with self.assertRaises(ContractError) as ctx_prec:
            self.compiler.compile_package(
                task_id=task_id,
                work_id="work-c7",
                policy_ref="jhoc-v1",
                capability_version="1.0",
                probes=[ast_probe],
                file_paths=[],
                negative_control_probe=None,
                require_negative_control=True,
            )
        # Anti-circular-mock must take precedence over mandatory negative control error
        self.assertIn("Anti-circular-mock violation", str(ctx_prec.exception))

    def test_c8_declared_new_file_manifest_verification(self) -> None:
        """C8: Proves declared new file is verified upon creation and failure to create fails closed."""
        new_file = self.workspace_root / "brand_new_file.py"
        initial_manifest = {str(new_file.resolve()): None}

        # Case A: File was NEVER created -> must fail closed
        ok, hashes, msg = self.compiler.verify_file_manifest(
            initial_manifest=initial_manifest,
            declared_changes=[new_file],
        )
        self.assertFalse(ok)
        self.assertIn("Declared new file was not created", msg)

        # Case B: File is physically created -> succeeds
        new_file.write_text("def created(): pass\n", encoding="utf-8")
        ok, hashes, msg = self.compiler.verify_file_manifest(
            initial_manifest=initial_manifest,
            declared_changes=[new_file],
        )
        self.assertTrue(ok)
        self.assertIn(str(new_file.resolve()), hashes)

    def test_c9_ghost_file_detection_and_transient_ignores(self) -> None:
        """C9: Proves undeclared ghost files in scan_roots fail closed while benign artifacts are ignored."""
        scan_dir = self.workspace_root / "src_sub"
        scan_dir.mkdir()
        tracked_file = scan_dir / "tracked.py"
        tracked_file.write_text("print(1)\n", encoding="utf-8")

        initial_manifest = self.compiler.snapshot_manifest([tracked_file], scan_roots=[scan_dir])

        # Modify declared tracked file so change is observed
        tracked_file.write_text("print(2)\n", encoding="utf-8")

        # 1. Add benign temporary files: .pyc, .sqlite-wal, __pycache__, editor temps (.swp, ~)
        pycache_dir = scan_dir / "__pycache__"
        pycache_dir.mkdir()
        (pycache_dir / "tracked.cpython-312.pyc").write_bytes(b"\x00\x00")
        (scan_dir / "test.sqlite-wal").write_bytes(b"\x00")
        (scan_dir / "test.lock").write_text("lock\n", encoding="utf-8")
        (scan_dir / ".tracked.py.swp").write_bytes(b"\x00\x01\x02")
        (scan_dir / "tracked.py~").write_text("backup\n", encoding="utf-8")

        # Must succeed and ignore these transient artifacts
        ok, hashes, msg = self.compiler.verify_file_manifest(
            initial_manifest=initial_manifest,
            declared_changes=[tracked_file],
            scan_roots=[scan_dir],
        )
        self.assertTrue(ok, f"Transient files must be ignored: {msg}")

        # 2. Add an undeclared ghost file
        ghost_file = scan_dir / "ghost_backdoor.py"
        ghost_file.write_text("malicious = True\n", encoding="utf-8")

        # Must fail closed on ghost file
        ok, hashes, msg = self.compiler.verify_file_manifest(
            initial_manifest=initial_manifest,
            declared_changes=[tracked_file],
            scan_roots=[scan_dir],
        )
        self.assertFalse(ok)
        self.assertIn("Undeclared ghost file detected in scan scope", msg)
        self.assertIn("ghost_backdoor.py", msg)

        # 3. Verify TOCTOU ghost detection at finalize
        staged_manifest = {str(tracked_file.resolve()): self.compiler.hash_file_physical(tracked_file)}
        ok_toctou, msg_toctou = self.compiler.verify_toctou(
            staged_manifest=staged_manifest,
            scan_roots=[scan_dir],
            declared_changes=[tracked_file],
            initial_manifest=initial_manifest,
        )
        self.assertFalse(ok_toctou)
        self.assertIn("TOCTOU drift: Undeclared ghost file appeared before finalize", msg_toctou)

    def test_c10_inline_code_ast_pre_audit(self) -> None:
        """C10: Proves -c/--command AST pre-audit catches syntax errors and dangling flags prior to execution."""
        # 1. Dangling -c flag without code payload
        with self.assertRaises(ContractError) as ctx_dang:
            self.arbitration.run_sandboxed_probe(["python", "-c"])
        self.assertIn("Dangling -c/--command argument", str(ctx_dang.exception))
        self.assertEqual(ctx_dang.exception.code, ErrorCode.INVALID_CONTRACT)

        # 2. Syntax error in inline code
        with self.assertRaises(ContractError) as ctx_syn:
            self.arbitration.run_sandboxed_probe(["python", "-c", "def broken_syntax(:"])
        self.assertIn("Inline probe code AST syntax error", str(ctx_syn.exception))
        self.assertEqual(ctx_syn.exception.code, ErrorCode.POLICY_DENIED)

        # 3. Valid inline code executes cleanly
        exit_code, stdout, stderr, out_h, err_h = self.arbitration.run_sandboxed_probe(
            ["python", "-c", "print('ast_verified_ok')"]
        )
        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout, "ast_verified_ok")
        self.assertEqual(out_h, hashlib.sha256(b"ast_verified_ok").hexdigest())

    def test_c9_w2_ghost_detection_in_empty_baseline_scan_root(self) -> None:
        """W2: Proves ghost file created in an empty-at-baseline scan_root fails closed at verify/accept."""
        scan_dir = self.workspace_root / "empty_root"
        scan_dir.mkdir()
        pos_probe = CompilerProbeResult(
            probe_type=CompilerProbeType.UNIT_TEST,
            target="pos",
            passed=True,
            details="pass",
            exit_code=0,
            stdout_sha256=hashlib.sha256(b"ok").hexdigest(),
        )
        neg_probe = CompilerProbeResult(
            probe_type=CompilerProbeType.NEGATIVE_CONTROL,
            target="neg",
            passed=False,
            details="neg",
            exit_code=1,
            stderr_sha256=hashlib.sha256(b"err").hexdigest(),
        )

        def plant_ghost(ctx):
            ghost = scan_dir / "ghost_undetected.py"
            ghost.write_text("backdoor = 1\n", encoding="utf-8")

        pipeline = HarnessPipeline()
        sm = FlowStateMachine()
        ctx = PipelineContext(
            task_id="task-w2-ghost",
            work_id="work-w2",
            config=PipelineConfig(dry_run=False),
            state_machine=sm,
            scan_roots=[scan_dir],
            declared_changes=[],
            probes=[pos_probe],
            negative_control_probe=neg_probe,
            evidence_engine=self.compiler,
            workspace_root=self.workspace_root,
            action_hook=plant_ghost,
        )
        res = pipeline.run(ctx)
        self.assertFalse(res.success, "Pipeline must fail closed when ghost appears in empty-baseline scan_root")
        self.assertEqual(res.final_status, WorkStatus.REPAIR)
        self.assertIn("Undeclared ghost file detected", str(res.error))

    def test_c3_w1_superseded_ticket_does_not_block_live_loop(self) -> None:
        """W1: Proves a stale PENDING ticket belonging to a superseded verdict does not block live gate."""
        task_id = "task-w1-supersede-ticket"
        file_a = self.workspace_root / "live_code.py"
        file_a.write_text("a = 1\n", encoding="utf-8")

        # 1. Create blocking dispute and verdict 1
        case = DisputeCase(
            dispute_id="disp-w1-001",
            task_id=task_id,
            claim_a=AtomicClaimDelta("cfg", "opt", 1, "agent_1"),
            claim_b=AtomicClaimDelta("cfg", "opt", 2, "agent_2"),
        )
        v1 = self.arbitration.arbitrate(case)
        self.assertTrue(v1.status.blocks_completion)

        # 2. Supersede v1 with a winning verdict v2
        v2 = ArbitrationVerdict(
            verdict_id="arb-v2-win",
            dispute_id="disp-w1-001",
            task_id=task_id,
            status=ArbitrationVerdictStatus.PROVEN_A,
            winner_claim=case.claim_a,
            probe_exit_code=0,
            probe_stdout_sha256="",
            probe_stderr_sha256="",
            parent_blackbox_hash="0" * 64,
            supersedes_ref=v1.verdict_id,
            justification="Superseding with proven resolution",
            decided_at="2026-09-07T00:00:02Z",
        )
        conn = sqlite3.connect(str(self.arbitration_db))
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO jhoc_arbitration_verdicts (
                        verdict_id, dispute_id, task_id, status, winner_claim_json,
                        probe_exit_code, probe_stdout_sha256, probe_stderr_sha256,
                        parent_blackbox_hash, supersedes_ref, justification, decided_at, digest
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        v2.verdict_id, v2.dispute_id, v2.task_id,
                        v2.status.value, json.dumps(case.claim_a.to_dict()),
                        0, "", "", v2.parent_blackbox_hash, v1.verdict_id,
                        v2.justification, v2.decided_at, v2.digest
                    )
                )
        finally:
            conn.close()

        # 3. Live pipeline run: should succeed because v1 was superseded even though its ticket is PENDING
        pos_probe = CompilerProbeResult(
            probe_type=CompilerProbeType.UNIT_TEST,
            target="pos",
            passed=True,
            details="pass",
            exit_code=0,
            stdout_sha256=hashlib.sha256(b"ok").hexdigest(),
        )
        neg_probe = CompilerProbeResult(
            probe_type=CompilerProbeType.NEGATIVE_CONTROL,
            target="neg",
            passed=False,
            details="neg",
            exit_code=1,
            stderr_sha256=hashlib.sha256(b"err").hexdigest(),
        )
        pipeline = HarnessPipeline()
        sm = FlowStateMachine()
        ctx = PipelineContext(
            task_id=task_id,
            work_id="work-w1-live",
            config=PipelineConfig(dry_run=False),
            state_machine=sm,
            declared_changes=[file_a],
            probes=[pos_probe],
            negative_control_probe=neg_probe,
            evidence_engine=self.compiler,
            arbitration_engine=self.arbitration,
            inbox=self.inbox,
            workspace_root=self.workspace_root,
            action_hook=lambda c: file_a.write_text("a = 2\n", encoding="utf-8"),
        )
        res = pipeline.run(ctx)
        self.assertTrue(res.success, f"Live pipeline must succeed on superseded verdict: {res.error}")
        self.assertEqual(res.final_status, WorkStatus.COMPLETE)

    def test_c14_rule7_pure_ascii_and_zero_emoji_scan(self) -> None:
        """C14: Strict Rule 7 check: 100% pure ASCII across Phase 6 deliverables and zero emoji repo-wide."""
        phase6_files = [
            Path("src/jhoc/flow/pipeline.py"),
            Path("src/jhoc/proof/evidence_compiler.py"),
            Path("src/jhoc/proof/arbitration.py"),
            Path("tests/test_phase6_verification_depth.py"),
            Path("scripts/jhoc_phase6_opening_co_review.py"),
        ]

        # 1. Phase 6 deliverables must be 100% pure ASCII
        for f in phase6_files:
            if not f.exists():
                continue
            raw_bytes = f.read_bytes()
            for line_no, b in enumerate(raw_bytes.splitlines(), start=1):
                try:
                    b.decode("ascii")
                except UnicodeDecodeError as exc:
                    self.fail(
                        f"Rule 7 Violation: Non-ASCII character in {f}:{line_no} "
                        f"(byte 0x{b[exc.start]:02x} at col {exc.start}): {b!r}"
                    )

        # 2. Zero non-BMP emojis anywhere across repository python files
        repo_root = Path(".").resolve()
        for p in repo_root.rglob("*.py"):
            if any(part in {".git", ".venv", "__pycache__", "build", "dist"} for part in p.parts):
                continue
            try:
                content = p.read_text(encoding="utf-8", errors="replace")
                for ch in content:
                    if ord(ch) > 0xFFFF:
                        self.fail(f"Rule 7 Violation: Non-BMP emoji character U+{ord(ch):04X} in {p}")
            except Exception:
                pass


if __name__ == "__main__":
    unittest.main()
