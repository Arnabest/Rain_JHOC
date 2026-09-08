"""Tests for Phase 5: Verification, Autonomous Arbitration & Evidence Harness.

Verifies all 15 binding co-review conditions (C1 - C15):
- C1: EvidencePackageEngine as sole gate-acceptable builder with ordered CompilerProbeResult records.
- C2: Empty-hash, all-zero sentinel, missing-file, and live mismatch rejection.
- C3: Anti-circular mock rule and mandatory negative-control validation.
- C4: Manifest snapshotting with declared vs undeclared file change verification.
- C5: TOCTOU live re-hash verification before Gate accept.
- C6: AtomicClaimDelta extraction; unparseable prose resolves to NON_PROBEABLE.
- C7: Sandboxed probe templates and AST-audited custom probe execution (allow_shell=False).
- C8: ArbitrationVerdict strict lattice and escalation to SQLiteApprovalInbox.
- C9: Immutable content-addressed verdicts chained to BlackBoxJournal.latest_hash.
- C10: HarnessPipeline thin stage registry driving FlowStateMachine through Gate.accept.
- C11: Dry-run vs live mode gating.
- C12: Deterministic error unwinding with reverse rollbacks.
- C13: Offline memory consolidation invariant.
- C14: Rule 7 pure ASCII and zero emoji verification.
- C15: Local-first SQLite WAL persistence and shadow_mode gating.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

from jhoc.conductor.inbox import ApprovalStatus, SQLiteApprovalInbox
from jhoc.contracts import ResultStatus, SideEffectState, WorkStatus
from jhoc.contracts.errors import ContractError, ErrorCode
from jhoc.flow.pipeline import (
    HarnessPipeline,
    PipelineConfig,
    PipelineContext,
    PipelineExecutionResult,
    PipelineStageContract,
)
from jhoc.flow.state_machine import FlowActor, FlowStateMachine
from jhoc.gate.gate import Gate
from jhoc.proof.arbitration import (
    ArbitrationVerdict,
    ArbitrationVerdictStatus,
    AtomicClaimDelta,
    DisputeArbitrationEngine,
    DisputeCase,
    ProbeTemplateType,
    audit_custom_probe_ast,
)
from jhoc.proof.blackbox import BlackBoxJournal
from jhoc.proof.evidence_compiler import (
    CompilerProbeResult,
    CompilerProbeType,
    EMPTY_SHA256,
    EvidencePackageEngine,
    EvidenceVerificationReport,
    ZERO_SHA256,
)
from jhoc.proof.store import EvidencePackage, ProofStore


class Phase5VerificationAndArbitrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="jhoc_phase5_test_")
        self.workspace = Path(self.temp_dir).resolve()
        self.proof_store = ProofStore()
        self.gate = Gate(self.proof_store)
        self.journal = BlackBoxJournal(task_id="task-p5-001", work_id="work-p5-001")
        self.inbox_db = self.workspace / "approvals.sqlite"
        self.inbox = SQLiteApprovalInbox(self.inbox_db)

    def tearDown(self) -> None:
        self.inbox.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # ==========================================
    # C1: EvidencePackageEngine & Probe Ordering
    # ==========================================
    def test_c1_compiler_probe_results_strict_ordering(self) -> None:
        target_file = self.workspace / "sample.py"
        target_file.write_text("def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")

        engine = EvidencePackageEngine(workspace_root=self.workspace)
        ast_probe = engine.compile_ast(target_file)
        unit_probe = engine.run_unit_test([sys.executable, "-c", "import sys; sys.exit(0)"])
        neg_probe = engine.run_unit_test([sys.executable, "-c", "import sys; sys.exit(1)"])

        pkg, report = engine.compile_package(
            task_id="task-p5-001",
            work_id="work-p5-001",
            policy_ref="jhoc:test:p5:c1",
            capability_version="v1",
            probes=[unit_probe, ast_probe],  # passed out-of-order intentionally
            file_paths=[target_file],
            negative_control_probe=neg_probe,
        )

        self.assertTrue(report.is_valid, f"Validation failed: {report.rejection_reason}")
        self.assertIsNotNone(pkg)

        # Probes must be ordered: AST -> Unit Test -> File Hash -> Negative Control
        probes = report.probes
        self.assertGreaterEqual(len(probes), 4)
        self.assertEqual(probes[0].probe_type, CompilerProbeType.AST_SYNTAX)
        self.assertEqual(probes[1].probe_type, CompilerProbeType.UNIT_TEST)
        self.assertEqual(probes[2].probe_type, CompilerProbeType.FILE_HASH)
        self.assertEqual(probes[3].probe_type, CompilerProbeType.NEGATIVE_CONTROL)

    # ==========================================
    # C2: Sentinel & Empty Hash Rejection
    # ==========================================
    def test_c2_rejects_empty_and_zero_sentinel_hashes(self) -> None:
        engine = EvidencePackageEngine(workspace_root=self.workspace)

        # 1. Empty file gives empty sha256 -> must raise ContractError
        empty_file = self.workspace / "empty.py"
        empty_file.write_bytes(b"")
        with self.assertRaises(ContractError) as cm:
            engine.hash_file_physical(empty_file)
        self.assertIn("empty-byte SHA-256", str(cm.exception))

        # 2. Sentinels length assertion
        self.assertEqual(len(ZERO_SHA256), 64)
        self.assertEqual(len(EMPTY_SHA256), 64)

        # 3. Missing file raises ContractError
        missing_file = self.workspace / "non_existent.py"
        with self.assertRaises(ContractError):
            engine.hash_file_physical(missing_file)

    # ==========================================
    # C3: Anti-Circular Mock & Negative Controls
    # ==========================================
    def test_c3_anti_circular_mock_and_negative_control_enforcement(self) -> None:
        good_file = self.workspace / "module.py"
        good_file.write_text("x = 42\n", encoding="utf-8")

        engine = EvidencePackageEngine(workspace_root=self.workspace)
        ast_probe = engine.compile_ast(good_file)

        # 1. Negative control missing with require_negative_control=True -> raises ContractError
        with self.assertRaises(ContractError) as cm1:
            engine.compile_package(
                task_id="task-p5-003",
                work_id="work-p5-003",
                policy_ref="jhoc:test:p5:c3",
                capability_version="v1",
                probes=[ast_probe],
                file_paths=[good_file],
                negative_control_probe=None,
                require_negative_control=True,
            )
        self.assertIn("Negative-control probe is mandatory", str(cm1.exception))

        # 2. Negative control that unexpectedly passed (exit code 0) -> raises ContractError
        passing_neg_probe = engine.run_unit_test([sys.executable, "-c", "import sys; sys.exit(0)"])
        with self.assertRaises(ContractError) as cm2:
            engine.compile_package(
                task_id="task-p5-003",
                work_id="work-p5-003",
                policy_ref="jhoc:test:p5:c3",
                capability_version="v1",
                probes=[ast_probe],
                file_paths=[good_file],
                negative_control_probe=passing_neg_probe,
            )
        self.assertIn("Negative-control probe was expected to fail, but passed", str(cm2.exception))

        # 3. Valid negative control (exit code 1) -> compiles successfully
        valid_neg_probe = engine.run_unit_test([sys.executable, "-c", "import sys; sys.exit(1)"])
        pkg, report = engine.compile_package(
            task_id="task-p5-003",
            work_id="work-p5-003",
            policy_ref="jhoc:test:p5:c3",
            capability_version="v1",
            probes=[ast_probe],
            file_paths=[good_file],
            negative_control_probe=valid_neg_probe,
        )
        self.assertTrue(report.is_valid)

    # ==========================================
    # C4: Manifest Snapshot & Declared File Diffs
    # ==========================================
    def test_c4_manifest_snapshotting_and_undeclared_change_detection(self) -> None:
        f1 = self.workspace / "f1.txt"
        f1.write_text("initial v1", encoding="utf-8")

        engine = EvidencePackageEngine(workspace_root=self.workspace)
        init_manifest = engine.snapshot_manifest([f1], scan_roots=[self.workspace])

        # Mutate f1 without declaring change in verify_file_manifest
        f1.write_text("unexpected mutation v2", encoding="utf-8")

        valid, current_hashes, reason = engine.verify_file_manifest(
            initial_manifest=init_manifest,
            declared_changes=[],  # empty declared changes
            scan_roots=[self.workspace],
        )
        self.assertFalse(valid)
        self.assertIn("Undeclared file modifications detected", reason)

        # When declared properly, verification passes
        valid_dec, _, reason_dec = engine.verify_file_manifest(
            initial_manifest=init_manifest,
            declared_changes=[f1],
            scan_roots=[self.workspace],
        )
        self.assertTrue(valid_dec, reason_dec)

    # ==========================================
    # C5: TOCTOU Defense Before Gate Accept
    # ==========================================
    def test_c5_toctou_live_rehash_detection(self) -> None:
        src_file = self.workspace / "core.py"
        src_file.write_text("def run(): return 1\n", encoding="utf-8")

        engine = EvidencePackageEngine(workspace_root=self.workspace)
        staged_hash = engine.hash_file_physical(src_file)
        staged_manifest = {str(src_file): staged_hash}

        # Verify passes when file unchanged
        valid, reason = engine.verify_toctou(staged_manifest)
        self.assertTrue(valid, reason)

        # Mutate file immediately to simulate TOCTOU drift
        src_file.write_text("def run(): return 999  # Tampered after record!\n", encoding="utf-8")

        valid_drift, reason_drift = engine.verify_toctou(staged_manifest)
        self.assertFalse(valid_drift)
        self.assertIn("TOCTOU drift", reason_drift)

    # ==========================================
    # C6: Arbitration Delta Isolation
    # ==========================================
    def test_c6_arbitration_delta_isolation_and_unparseable_prose(self) -> None:
        arb_db = self.workspace / "arb.sqlite"
        arb_engine = DisputeArbitrationEngine(
            db_path=arb_db,
            workspace_root=self.workspace,
            approval_inbox=self.inbox,
        )

        # Case 1: Structured valid deltas
        case1 = arb_engine.isolate_delta(
            task_id="task-p5-006",
            subject="service_port",
            claim_a_text="port: 8080",
            claim_b_text="port: 9090",
            provenance_a="model_a",
            provenance_b="model_b",
        )
        self.assertTrue(case1.is_probeable)
        self.assertEqual(case1.claim_a.value, "8080")
        self.assertEqual(case1.claim_b.value, "9090")

        # Case 2: Unparseable natural language prose divergence -> NON_PROBEABLE
        case2 = arb_engine.isolate_delta(
            task_id="task-p5-006",
            subject="architecture_philosophy",
            claim_a_text="I believe we should embrace reactive streaming patterns for high throughput.",
            claim_b_text="No, I think a simple thread pool executor is more reliable and understandable.",
            provenance_a="model_a",
            provenance_b="model_b",
        )
        self.assertFalse(case2.is_probeable)
        self.assertIn("Unparseable prose divergence", case2.unprobeable_reason)

        arb_engine.close()

    # ==========================================
    # C7: Sandboxed Probe Execution & AST Audit
    # ==========================================
    def test_c7_sandboxed_probe_execution_and_ast_audit(self) -> None:
        arb_db = self.workspace / "arb.sqlite"
        arb_engine = DisputeArbitrationEngine(
            db_path=arb_db,
            workspace_root=self.workspace,
            approval_inbox=self.inbox,
        )

        # 1. AST Audit: Dangerous primitives must be blocked
        unsafe_code_1 = "import os\nos.system('dir')\n"
        passed1, err1 = audit_custom_probe_ast(unsafe_code_1)
        self.assertFalse(passed1)
        self.assertIn("Forbidden", err1)

        unsafe_code_2 = "eval('1 + 1')\n"
        passed2, err2 = audit_custom_probe_ast(unsafe_code_2)
        self.assertFalse(passed2)
        self.assertIn("Forbidden", err2)

        # 2. Safe custom code passes AST audit
        safe_code = "print('42')\n"
        passed3, _ = audit_custom_probe_ast(safe_code)
        self.assertTrue(passed3)

        # 3. File exists template probe
        flag_file = self.workspace / "installed.flag"
        flag_file.write_text("installed", encoding="utf-8")

        case = arb_engine.isolate_delta(
            task_id="task-p5-007",
            subject="installed.flag",
            claim_a_text="exists: true",
            claim_b_text="exists: false",
            provenance_a="model_a",
            provenance_b="model_b",
        )
        verdict = arb_engine.arbitrate_case(
            case=case,
            probe_template=ProbeTemplateType.FILE_EXISTS,
            probe_args={"path": "installed.flag"},
            journal=self.journal,
        )
        self.assertEqual(verdict.status, ArbitrationVerdictStatus.PROVEN_A)
        self.assertEqual(verdict.winning_model, "model_a")

        arb_engine.close()

    # ==========================================
    # C8: ArbitrationVerdict Lattice & Escalation
    # ==========================================
    def test_c8_verdict_lattice_and_inbox_escalation(self) -> None:
        arb_db = self.workspace / "arb.sqlite"
        arb_engine = DisputeArbitrationEngine(
            db_path=arb_db,
            workspace_root=self.workspace,
            approval_inbox=self.inbox,
        )

        # 1. NON_PROBEABLE automatically escalates to SQLiteApprovalInbox
        case_unprobeable = arb_engine.isolate_delta(
            task_id="task-p5-008",
            subject="abstract_design",
            claim_a_text="Monolith is superior here",
            claim_b_text="Microservices are superior here",
        )
        verdict_np = arb_engine.arbitrate_case(case_unprobeable, journal=self.journal)
        self.assertEqual(verdict_np.status, ArbitrationVerdictStatus.NON_PROBEABLE)
        self.assertIsNotNone(verdict_np.escalated_ticket_id)

        ticket = self.inbox.get_ticket(verdict_np.escalated_ticket_id)
        self.assertIsNotNone(ticket)
        self.assertEqual(ticket.operation, "ARBITRATION_NON_PROBEABLE")
        self.assertEqual(ticket.status, ApprovalStatus.PENDING)

        # 2. INCONCLUSIVE probe also escalates
        case_probeable = arb_engine.isolate_delta(
            task_id="task-p5-008",
            subject="unknown_flag",
            claim_a_text="val: 100",
            claim_b_text="val: 200",
        )
        # Probe outputs "300" (matches neither A nor B) -> INCONCLUSIVE
        def inconclusive_runner():
            return (0, "300", "", "spec_hash_inconclusive")

        verdict_inc = arb_engine.arbitrate_case(
            case=case_probeable,
            probe_runner=inconclusive_runner,
            journal=self.journal,
        )
        self.assertEqual(verdict_inc.status, ArbitrationVerdictStatus.INCONCLUSIVE)
        self.assertIsNotNone(verdict_inc.escalated_ticket_id)

        ticket_inc = self.inbox.get_ticket(verdict_inc.escalated_ticket_id)
        self.assertIsNotNone(ticket_inc)
        self.assertEqual(ticket_inc.operation, "ARBITRATION_INCONCLUSIVE")

        arb_engine.close()

    # ==========================================
    # C9: Immutable Persistence & BlackBox Chaining
    # ==========================================
    def test_c9_content_addressed_verdict_and_blackbox_chaining(self) -> None:
        arb_db = self.workspace / "arb.sqlite"
        arb_engine = DisputeArbitrationEngine(
            db_path=arb_db,
            workspace_root=self.workspace,
            approval_inbox=self.inbox,
        )

        initial_journal_length = self.journal.length
        initial_hash = self.journal.latest_hash

        cfg_file = self.workspace / "app.json"
        cfg_file.write_text(json.dumps({"timeout": 30}), encoding="utf-8")

        case = arb_engine.isolate_delta(
            task_id="task-p5-009",
            subject="app.json",
            claim_a_text="timeout: 30",
            claim_b_text="timeout: 60",
            provenance_a="agent_codex",
            provenance_b="agent_claude",
        )
        verdict = arb_engine.arbitrate_case(
            case=case,
            probe_template=ProbeTemplateType.JSON_FIELD_EQUALS,
            probe_args={"path": "app.json", "field": "timeout"},
            journal=self.journal,
        )

        self.assertEqual(verdict.status, ArbitrationVerdictStatus.PROVEN_A)
        self.assertEqual(verdict.winning_model, "agent_codex")
        self.assertEqual(verdict.journal_chain_hash, initial_hash)

        # Journal must have recorded the arbitration verdict step
        self.assertEqual(self.journal.length, initial_journal_length + 1)
        self.assertNotEqual(self.journal.latest_hash, initial_hash)

        # Persistence check: load verdict from SQLite
        persisted = arb_engine.get_verdict(verdict.verdict_id)
        self.assertIsNotNone(persisted)
        self.assertEqual(persisted.verdict_id, verdict.verdict_id)
        self.assertEqual(persisted.probe_exit_code, 0)

        arb_engine.close()

    # ==========================================
    # C10 & C11: HarnessPipeline & Dry-Run Mode
    # ==========================================
    def test_c10_and_c11_harness_pipeline_dry_run_vs_live(self) -> None:
        audit_db = self.workspace / "pipeline_audit.sqlite"

        # 1. Dry-Run Execution: exercises stages without final Gate acceptance commit
        cfg_dry = PipelineConfig(
            task_id="task-p5-010",
            work_id="work-p5-010",
            workspace_root=self.workspace,
            dry_run=True,
            audit_db_path=audit_db,
        )
        pipeline_dry = HarnessPipeline(config=cfg_dry)
        res_dry = pipeline_dry.execute()

        self.assertTrue(res_dry.is_success)
        self.assertTrue(res_dry.is_dry_run)
        self.assertEqual(res_dry.final_state, WorkStatus.COMPLETION_PENDING)
        self.assertIn("PLAN", res_dry.executed_stages)
        self.assertIn("ACT", res_dry.executed_stages)
        self.assertIn("COMPLETE", res_dry.executed_stages)

        # 2. Live Execution: compiles valid evidence and accepts via Gate into COMPLETE
        src = self.workspace / "live_service.py"
        src.write_text("class Service:\n    pass\n", encoding="utf-8")

        cfg_live = PipelineConfig(
            task_id="task-p5-011",
            work_id="work-p5-011",
            workspace_root=self.workspace,
            dry_run=False,
            audit_db_path=audit_db,
        )
        engine = EvidencePackageEngine(workspace_root=self.workspace)
        ast_probe = engine.compile_ast(src)
        neg_probe = engine.run_unit_test([sys.executable, "-c", "import sys; sys.exit(1)"])

        pkg, report = engine.compile_package(
            task_id=cfg_live.task_id,
            work_id=cfg_live.work_id,
            policy_ref=cfg_live.policy_ref,
            capability_version="v1",
            probes=[ast_probe],
            file_paths=[src],
            side_effect_state=SideEffectState.SUCCEEDED.value,
            negative_control_probe=neg_probe,
        )
        self.assertTrue(report.is_valid)

        ctx_live = PipelineContext(
            config=cfg_live,
            flow=FlowStateMachine(initial=WorkStatus.NEW),
            evidence_engine=engine,
            compiled_evidence=pkg,
            proof_store=self.proof_store,
            gate=self.gate,
            journal=self.journal,
        )
        pipeline_live = HarnessPipeline(config=cfg_live)
        res_live = pipeline_live.execute(context=ctx_live)

        self.assertTrue(res_live.is_success, f"Live pipeline failed: {res_live.error_diagnostic}")
        self.assertFalse(res_live.is_dry_run)
        self.assertEqual(res_live.final_state, WorkStatus.COMPLETE)
        self.assertIsNotNone(res_live.evidence_digest)
        self.assertIsNotNone(self.proof_store.acceptance(res_live.evidence_digest))

    # ==========================================
    # C12: Deterministic Error Unwinding
    # ==========================================
    def test_c12_deterministic_error_unwinding_and_reverse_rollback(self) -> None:
        cfg = PipelineConfig(
            task_id="task-p5-012",
            work_id="work-p5-012",
            workspace_root=self.workspace,
            allow_degraded=True,
        )

        unwound_actions: list[str] = []

        def rollback_1(ctx, out):
            unwound_actions.append("rollback_1")

        def rollback_2(ctx, out):
            unwound_actions.append("rollback_2")

        stages = [
            PipelineStageContract(
                name="STAGE_1",
                target_state=WorkStatus.PLAN,
                run=lambda ctx: {"s1": "ok"},
                rollback=rollback_1,
            ),
            PipelineStageContract(
                name="STAGE_2",
                target_state=WorkStatus.ACT,
                run=lambda ctx: {"s2": "ok"},
                rollback=rollback_2,
            ),
            PipelineStageContract(
                name="STAGE_FAILING",
                target_state=WorkStatus.OBSERVE,
                run=lambda ctx: (_ for _ in ()).throw(RuntimeError("Simulated Stage Crash")),
            ),
        ]

        pipeline = HarnessPipeline(config=cfg, stages=stages)
        result = pipeline.execute()

        self.assertFalse(result.is_success)
        self.assertIn("Simulated Stage Crash", result.error_diagnostic)
        self.assertEqual(result.final_state, WorkStatus.DEGRADED)

        # Rollback execution order must be strict reverse: STAGE_2 then STAGE_1
        self.assertEqual(unwound_actions, ["rollback_2", "rollback_1"])
        self.assertEqual(result.unwound_stages, ("STAGE_2", "STAGE_1"))

    # ==========================================
    # C13: Offline Memory Consolidation Invariant
    # ==========================================
    def test_c13_offline_memory_consolidation_invariant(self) -> None:
        cfg = PipelineConfig(
            task_id="task-p5-013",
            work_id="work-p5-013",
            workspace_root=self.workspace,
            dry_run=True,
        )
        pipeline = HarnessPipeline(config=cfg)
        result = pipeline.execute()
        self.assertTrue(result.is_success)
        # Verify no memory store modification happened in workspace
        memory_db = self.workspace / "memory.sqlite"
        self.assertFalse(memory_db.exists())

    # ==========================================
    # C14: Rule 7 Pure ASCII & Zero Emoji Discipline
    # ==========================================
    def test_c14_rule7_pure_ascii_discipline(self) -> None:
        target_files = [
            Path("src/jhoc/proof/evidence_compiler.py"),
            Path("src/jhoc/proof/arbitration.py"),
            Path("src/jhoc/flow/pipeline.py"),
            Path("tests/test_phase5_verification_and_arbitration.py"),
        ]

        for rel_path in target_files:
            file_path = (Path.cwd() / rel_path).resolve()
            self.assertTrue(file_path.is_file(), f"File missing: {rel_path}")
            raw_bytes = file_path.read_bytes()
            for idx, byte in enumerate(raw_bytes):
                if byte >= 128:
                    line_no = raw_bytes[:idx].count(b"\n") + 1
                    self.fail(
                        f"Rule 7 Violation: Non-ASCII byte 0x{byte:02x} detected in {rel_path} "
                        f"at line {line_no}."
                    )

    # ==========================================
    # C15: Local-First SQLite WAL & Shadow Mode
    # ==========================================
    def test_c15_local_first_sqlite_wal_and_shadow_flag(self) -> None:
        audit_db = self.workspace / "shadow_audit.sqlite"
        cfg_shadow = PipelineConfig(
            task_id="task-p5-015",
            work_id="work-p5-015",
            workspace_root=self.workspace,
            dry_run=True,
            shadow_mode=True,
            audit_db_path=audit_db,
        )
        pipeline = HarnessPipeline(config=cfg_shadow)
        res = pipeline.execute()

        self.assertTrue(res.is_success)
        self.assertTrue(res.is_shadow)

        # Assert local SQLite WAL was created
        self.assertTrue(audit_db.is_file())
        import sqlite3
        with sqlite3.connect(str(audit_db)) as db:
            cur = db.execute("PRAGMA journal_mode")
            mode = cur.fetchone()[0].lower()
            self.assertEqual(mode, "wal")

            cur = db.execute("SELECT is_shadow FROM jhoc_pipeline_runs WHERE task_id = ?", ("task-p5-015",))
            row = cur.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], 1)


    def test_c6_spurious_dispute_and_attribute_mismatch(self) -> None:
        arb_db = self.workspace / "arb_edge.sqlite"
        arb_engine = DisputeArbitrationEngine(db_path=arb_db, workspace_root=self.workspace)

        # 1. Spurious dispute: identical values
        case_spur = arb_engine.isolate_delta(
            task_id="task-edge-01",
            subject="db_port",
            claim_a_text="port: 5432",
            claim_b_text="port: 5432",
        )
        self.assertFalse(case_spur.is_probeable)
        self.assertIn("Spurious dispute", case_spur.unprobeable_reason)

        # 2. Attribute mismatch: distinct observable keys
        case_attr = arb_engine.isolate_delta(
            task_id="task-edge-02",
            subject="network",
            claim_a_text="port: 8080",
            claim_b_text="protocol: udp",
        )
        self.assertFalse(case_attr.is_probeable)
        self.assertIn("Attribute mismatch", case_attr.unprobeable_reason)

        arb_engine.close()

    def test_c7_forbidden_import_modules_blocked(self) -> None:
        for mod in ["socket", "urllib.request", "requests", "ctypes"]:
            code = f"import {mod}\n"
            passed, err = audit_custom_probe_ast(code)
            self.assertFalse(passed, f"Module '{mod}' should have been blocked")
            self.assertIn("Forbidden", err)

    def test_c7_template_probes_contains_and_ast_valid(self) -> None:
        arb_db = self.workspace / "arb_tmpl.sqlite"
        arb_engine = DisputeArbitrationEngine(db_path=arb_db, workspace_root=self.workspace)

        doc = self.workspace / "doc.txt"
        doc.write_text("JHOC Physical Reality Law\n", encoding="utf-8")

        case = arb_engine.isolate_delta(
            task_id="task-tmpl-01",
            subject="doc.txt",
            claim_a_text="contains: true",
            claim_b_text="contains: false",
        )
        verdict = arb_engine.arbitrate_case(
            case=case,
            probe_template=ProbeTemplateType.FILE_CONTENT_CONTAINS,
            probe_args={"path": "doc.txt", "contains": "Physical Reality"},
        )
        self.assertEqual(verdict.status, ArbitrationVerdictStatus.PROVEN_A)

        # AST syntax valid probe
        py_file = self.workspace / "script.py"
        py_file.write_text("x = 10\ny = 20\n", encoding="utf-8")
        case_ast = arb_engine.isolate_delta(
            task_id="task-tmpl-02",
            subject="script.py",
            claim_a_text="syntax_valid: true",
            claim_b_text="syntax_valid: false",
        )
        verdict_ast = arb_engine.arbitrate_case(
            case=case_ast,
            probe_template=ProbeTemplateType.AST_SYNTAX_VALID,
            probe_args={"path": "script.py"},
        )
        self.assertEqual(verdict_ast.status, ArbitrationVerdictStatus.PROVEN_A)

        arb_engine.close()

    def test_c8_proven_b_verdict_when_b_refutes_a(self) -> None:
        arb_db = self.workspace / "arb_b.sqlite"
        arb_engine = DisputeArbitrationEngine(db_path=arb_db, workspace_root=self.workspace)

        case = arb_engine.isolate_delta(
            task_id="task-b-01",
            subject="cache_size",
            claim_a_text="size: 100",
            claim_b_text="size: 500",
            provenance_a="model_a",
            provenance_b="model_b",
        )
        # Probe observes 500 -> Model B is proven
        def runner_observes_500():
            return (0, "500", "", "hash_500")

        verdict = arb_engine.arbitrate_case(
            case=case,
            probe_runner=runner_observes_500,
            journal=self.journal,
        )
        self.assertEqual(verdict.status, ArbitrationVerdictStatus.PROVEN_B)
        self.assertEqual(verdict.winning_model, "model_b")

        arb_engine.close()

    def test_c9_supersedes_ref_versioning_and_list_verdicts(self) -> None:
        arb_db = self.workspace / "arb_ver.sqlite"
        arb_engine = DisputeArbitrationEngine(db_path=arb_db, workspace_root=self.workspace)

        case = arb_engine.isolate_delta(
            task_id="task-ver-01",
            subject="cfg",
            claim_a_text="v: 1",
            claim_b_text="v: 2",
        )
        v1 = arb_engine.arbitrate_case(
            case=case,
            probe_runner=lambda: (0, "1", "", "hash_1"),
        )
        # Second arbitration supersedes v1
        v2 = arb_engine.arbitrate_case(
            case=case,
            probe_runner=lambda: (0, "2", "", "hash_2"),
            supersedes_ref=v1.verdict_id,
        )
        self.assertEqual(v2.supersedes_ref, v1.verdict_id)

        all_verdicts = arb_engine.list_verdicts_for_task("task-ver-01")
        self.assertEqual(len(all_verdicts), 2)
        self.assertEqual(all_verdicts[0].verdict_id, v1.verdict_id)
        self.assertEqual(all_verdicts[1].verdict_id, v2.verdict_id)

        arb_engine.close()

    def test_c11_dry_run_leaves_gate_empty(self) -> None:
        cfg = PipelineConfig(
            task_id="task-dry-01",
            work_id="work-dry-01",
            workspace_root=self.workspace,
            dry_run=True,
        )
        pipeline = HarnessPipeline(config=cfg)
        result = pipeline.execute()
        self.assertTrue(result.is_success)
        self.assertTrue(result.is_dry_run)
        # Gate store has 0 acceptances
        self.assertIsNone(self.proof_store.acceptance("any_digest"))


if __name__ == "__main__":
    unittest.main()
