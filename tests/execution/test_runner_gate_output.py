import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from jhoc.contracts import ContractError, ErrorCode, ResultStatus, SideEffectState, WorkStatus  # noqa: E402
from jhoc.flow import FlowStateMachine  # noqa: E402
from jhoc.gate import Gate  # noqa: E402
from jhoc.output import DeliveryState, OutputRuntime  # noqa: E402
from jhoc.proof import EvidencePackage, ProofStore  # noqa: E402
from jhoc.runner import Runner  # noqa: E402


class RunnerGateOutputTests(unittest.TestCase):
    def evidence(self, side_effect="SUCCEEDED"):
        return EvidencePackage("task", "task", "policy:v1", "cap:v1", {"ok": True}, {"value": 1}, {"checked": True}, side_effect, ("artifact:1",))

    def test_runner_stops_pending_and_gate_accepts_with_evidence(self):
        flow = FlowStateMachine()
        task_id, work_id = uuid4(), uuid4()
        execution = Runner().execute(
            task_id, work_id, flow, lambda: {"value": 1}, operation_id="operation:accept", side_effecting=True
        )
        evidence = EvidencePackage(str(task_id), str(work_id), "policy:v1", "cap:v1", {"ok": True}, {"value": 1}, {"checked": True}, "SUCCEEDED", ("artifact:1",))
        self.assertEqual(execution.state, WorkStatus.COMPLETION_PENDING)
        digest = Gate(ProofStore()).accept(flow, execution.result, evidence)
        self.assertTrue(digest)
        self.assertEqual(flow.state, WorkStatus.COMPLETE)

    def test_gate_rejects_uncertain_side_effect(self):
        flow = FlowStateMachine()
        task_id, work_id = uuid4(), uuid4()
        execution = Runner().execute(
            task_id, work_id, flow, lambda: {"value": 1}, operation_id="operation:uncertain", side_effecting=True
        )
        evidence = EvidencePackage(str(task_id), str(work_id), "policy:v1", "cap:v1", {"ok": True}, {"value": 1}, {"checked": True}, SideEffectState.UNKNOWN_SIDE_EFFECT.value, ("artifact:1",))
        with self.assertRaises(Exception):
            Gate(ProofStore()).accept(flow, execution.result, evidence)
        self.assertEqual(flow.state, WorkStatus.COMPLETION_PENDING)

    def test_proof_store_allows_only_one_bound_gate_writer(self):
        proof = ProofStore()
        Gate(proof)
        self.assertFalse(hasattr(proof, "_record_gate_acceptance"))
        with self.assertRaises(ContractError) as error:
            Gate(proof)
        self.assertEqual(error.exception.code, ErrorCode.POLICY_DENIED)

    def test_gate_persistence_failure_leaves_flow_completion_pending(self):
        proof = ProofStore()
        gate = Gate(proof)
        flow = FlowStateMachine()
        task_id, work_id = uuid4(), uuid4()
        execution = Runner().execute(task_id, work_id, flow, lambda: {"value": 1})
        evidence = EvidencePackage(
            str(task_id), str(work_id), "policy:v1", "cap:v1", {}, {"value": 1},
            {"checked": True}, SideEffectState.NOT_APPLICABLE.value, ("artifact:1",),
        )
        gate._prepare_acceptance = lambda package: (_ for _ in ()).throw(RuntimeError("proof unavailable"))
        with self.assertRaisesRegex(RuntimeError, "proof unavailable"):
            gate.accept(flow, execution.result, evidence)
        self.assertEqual(flow.state, WorkStatus.COMPLETION_PENDING)
        self.assertIsNone(proof.acceptance(evidence.digest))

    def test_gate_finalize_failure_keeps_receipt_unpublishable(self):
        proof = ProofStore()
        gate = Gate(proof)
        flow = FlowStateMachine()
        task_id, work_id = uuid4(), uuid4()
        execution = Runner().execute(task_id, work_id, flow, lambda: {"value": 1})
        evidence = EvidencePackage(
            str(task_id), str(work_id), "policy:v1", "cap:v1", {}, {"value": 1},
            {"checked": True}, SideEffectState.NOT_APPLICABLE.value, ("artifact:1",),
        )
        finalize = gate._finalize_acceptance
        gate._finalize_acceptance = lambda digest: (_ for _ in ()).throw(RuntimeError("commit interrupted"))
        with self.assertRaisesRegex(RuntimeError, "commit interrupted"):
            gate.accept(flow, execution.result, evidence)
        self.assertEqual(flow.state, WorkStatus.COMPLETE)
        self.assertIsNone(proof.acceptance(evidence.digest))
        self.assertIsNotNone(proof.pending_acceptance(evidence.digest))
        with self.assertRaises(ContractError) as error:
            OutputRuntime(proof).publish(evidence.digest, lambda value: None)
        self.assertEqual(error.exception.code, ErrorCode.POLICY_DENIED)
        gate._finalize_acceptance = finalize
        self.assertEqual(gate.reconcile_acceptance(flow, execution.result, evidence), evidence.digest)
        self.assertIsNotNone(proof.acceptance(evidence.digest))

    def test_gate_rejects_evidence_for_a_different_execution_output(self):
        flow = FlowStateMachine()
        task_id, work_id = uuid4(), uuid4()
        execution = Runner().execute(
            task_id, work_id, flow, lambda: {"value": 1}, operation_id="operation:mismatch", side_effecting=True
        )
        evidence = EvidencePackage(str(task_id), str(work_id), "policy:v1", "cap:v1", {"ok": True}, {"value": 999}, {"checked": True}, "SUCCEEDED", ("artifact:1",))
        with self.assertRaisesRegex(Exception, "execution does not match"):
            Gate(ProofStore()).accept(flow, execution.result, evidence)
        self.assertEqual(flow.state, WorkStatus.COMPLETION_PENDING)

    def test_runner_executes_action_in_act_phase_and_journals_replay(self):
        task_id, work_id = uuid4(), uuid4()
        runner = Runner()
        calls = []
        first_flow = FlowStateMachine()
        first = runner.execute(
            task_id,
            work_id,
            first_flow,
            lambda: (calls.append(first_flow.state) or {"value": 5}),
            operation_id="operation:once",
            side_effecting=True,
        )
        second = runner.execute(
            task_id,
            work_id,
            FlowStateMachine(),
            lambda: (calls.append("replayed") or {"value": 99}),
            operation_id="operation:once",
            side_effecting=True,
        )
        self.assertEqual(calls, [WorkStatus.ACT])
        self.assertEqual(first.result.output, {"value": 5})
        self.assertEqual(second.result.output, {"value": 5})
        self.assertEqual(second.result.side_effect_state, SideEffectState.SUCCEEDED)

    def test_gate_rejects_side_effect_claim_that_differs_from_runner(self):
        flow = FlowStateMachine()
        task_id, work_id = uuid4(), uuid4()
        execution = Runner().execute(task_id, work_id, flow, lambda: {"value": 1})
        evidence = EvidencePackage(
            str(task_id), str(work_id), "policy:v1", "cap:v1", {"ok": True}, {"value": 1},
            {"checked": True}, SideEffectState.SUCCEEDED.value, ("artifact:1",),
        )
        with self.assertRaisesRegex(Exception, "side effect does not match"):
            Gate(ProofStore()).accept(flow, execution.result, evidence)

    def test_unjournaled_side_effect_is_rejected_before_action(self):
        calls = []
        execution = Runner().execute(
            uuid4(),
            uuid4(),
            FlowStateMachine(),
            lambda: (calls.append(1) or {"unsafe": True}),
            side_effecting=True,
        )
        self.assertEqual(calls, [])
        self.assertEqual(execution.result.status, ResultStatus.FAILED)
        self.assertEqual(execution.result.side_effect_state, SideEffectState.NOT_APPLICABLE)
        self.assertEqual(execution.result.error_code, ErrorCode.INVALID_CONTRACT.value)
        self.assertEqual(execution.state, WorkStatus.BLOCKED)

    def test_failed_journaled_side_effect_is_unknown_and_requires_reconciliation(self):
        runner = Runner()
        execution = runner.execute(
            uuid4(),
            uuid4(),
            FlowStateMachine(),
            lambda: (_ for _ in ()).throw(RuntimeError("device disconnected")),
            operation_id="operation:failed-device",
            side_effecting=True,
        )
        self.assertEqual(execution.result.side_effect_state, SideEffectState.UNKNOWN_SIDE_EFFECT)
        self.assertEqual(execution.state, WorkStatus.BLOCKED)
        self.assertEqual(
            runner.journal.get("operation:failed-device").state.value,
            "REQUIRES_RECONCILIATION",
        )

    def test_reconciliation_storage_failure_blocks_flow_and_propagates(self):
        runner = Runner()
        flow = FlowStateMachine()
        with patch.object(
            runner.journal,
            "require_reconciliation",
            side_effect=RuntimeError("journal unavailable"),
        ):
            with self.assertRaisesRegex(RuntimeError, "journal unavailable"):
                runner.execute(
                    uuid4(),
                    uuid4(),
                    flow,
                    lambda: (_ for _ in ()).throw(RuntimeError("device disconnected")),
                    operation_id="operation:journal-failure",
                    side_effecting=True,
                )
        self.assertEqual(flow.state, WorkStatus.BLOCKED)

    def test_output_retry_does_not_reexecute_action(self):
        proof = ProofStore()
        flow = FlowStateMachine()
        task_id, work_id = uuid4(), uuid4()
        execution = Runner().execute(task_id, work_id, flow, lambda: {"value": 1})
        evidence = EvidencePackage(
            str(task_id), str(work_id), "policy:v1", "cap:v1", {"ok": True}, {"value": 1},
            {"checked": True}, SideEffectState.NOT_APPLICABLE.value, ("artifact:1",),
        )
        digest = Gate(proof).accept(flow, execution.result, evidence)
        output = OutputRuntime(proof)
        calls = []
        failed = output.publish(digest, lambda value: (_ for _ in ()).throw(RuntimeError("offline")))
        self.assertEqual(failed.state, DeliveryState.FAILED)
        delivered = output.retry(digest, lambda value: calls.append(value))
        self.assertEqual(delivered.state, DeliveryState.DELIVERED)
        self.assertEqual(calls, [digest])

    def test_output_rejects_evidence_not_accepted_by_gate(self):
        proof = ProofStore()
        digest = proof.record_evidence(self.evidence())
        with self.assertRaises(ContractError) as error:
            OutputRuntime(proof).publish(digest, lambda value: None)
        self.assertEqual(error.exception.code, ErrorCode.POLICY_DENIED)

    def test_output_persists_reconciliation_before_reraising_base_exception(self):
        proof = ProofStore()
        flow = FlowStateMachine()
        task_id, work_id = uuid4(), uuid4()
        execution = Runner().execute(task_id, work_id, flow, lambda: {"value": 1})
        evidence = EvidencePackage(
            str(task_id), str(work_id), "policy:v1", "cap:v1", {}, {"value": 1},
            {"checked": True}, SideEffectState.NOT_APPLICABLE.value, ("artifact:1",),
        )
        digest = Gate(proof).accept(flow, execution.result, evidence)
        output = OutputRuntime(proof)

        def interrupt(_value):
            raise KeyboardInterrupt()

        with self.assertRaises(KeyboardInterrupt):
            output.publish(digest, interrupt)
        record = output.record(digest)
        self.assertIsNotNone(record)
        self.assertEqual(record.state, DeliveryState.REQUIRES_RECONCILIATION)

    def test_concurrent_publish_claims_delivery_once(self):
        proof = ProofStore()
        flow = FlowStateMachine()
        task_id, work_id = uuid4(), uuid4()
        execution = Runner().execute(task_id, work_id, flow, lambda: {"value": 1})
        evidence = EvidencePackage(
            str(task_id), str(work_id), "policy:v1", "cap:v1", {}, {"value": 1},
            {"checked": True}, SideEffectState.NOT_APPLICABLE.value, ("artifact:1",),
        )
        digest = Gate(proof).accept(flow, execution.result, evidence)
        output = OutputRuntime(proof)
        started = Event()
        release = Event()
        calls = []

        def sender(value):
            calls.append(value)
            started.set()
            release.wait(timeout=5)

        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(output.publish, digest, sender)
            self.assertTrue(started.wait(timeout=5))
            with self.assertRaises(ContractError) as error:
                output.publish(digest, sender)
            self.assertEqual(error.exception.code, ErrorCode.IDEMPOTENCY_CONFLICT)
            release.set()
            self.assertEqual(first.result(timeout=5).state, DeliveryState.DELIVERED)
        self.assertEqual(calls, [digest])

    def test_runner_failure_is_blocked_and_not_completed(self):
        flow = FlowStateMachine()
        execution = Runner().execute(uuid4(), uuid4(), flow, lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        self.assertEqual(execution.result.status, ResultStatus.FAILED)
        self.assertEqual(flow.state, WorkStatus.BLOCKED)

    def test_runner_base_exception_marks_operation_in_doubt_and_blocks_flow(self):
        """P1 (R4): a BaseException during a side-effecting action must leave the
        durable operation explicitly in-doubt, land the flow in BLOCKED, and
        re-raise the interrupt instead of vanishing."""
        from jhoc.storage import StateStore
        from jhoc.runner.journal import OperationJournal, OperationState

        journal = OperationJournal(StateStore())
        runner = Runner(journal)
        flow = FlowStateMachine()
        operation_id = "operation:interrupt-p1"

        def interrupting_action():
            raise KeyboardInterrupt("user interrupt")

        with self.assertRaises(KeyboardInterrupt):
            runner.execute(
                uuid4(), uuid4(), flow, interrupting_action,
                operation_id=operation_id, side_effecting=True,
            )
        self.assertEqual(flow.state, WorkStatus.BLOCKED)
        operation = journal.get(operation_id)
        self.assertIsNotNone(operation)
        self.assertEqual(operation.state, OperationState.REQUIRES_RECONCILIATION)

    def test_sqlite_proof_store_encodes_non_json_values_like_digest(self):
        """P1 (R4): SQLite ProofStore must persist exactly what the in-memory
        store digests, including non-JSON values, without TypeError drift."""
        import json as _json
        import tempfile
        from datetime import datetime, timezone as tz
        from pathlib import Path as _Path
        import sys as _sys

        proofs = _sys.modules["jhoc.proof"]
        from jhoc.proof.store import EvidencePackage as _EvidencePackage

        stamp = datetime(2026, 9, 2, 12, 0, 0, tzinfo=tz.utc)
        package = _EvidencePackage(
            "task", "task", "policy:v1", "cap:v1", {"when": stamp}, {"when": stamp},
            {"checked": True}, "SUCCEEDED", ("artifact:1",),
        )
        with tempfile.TemporaryDirectory() as tmp:
            from jhoc.proof.sqlite import SQLiteProofStore

            store = SQLiteProofStore(str(_Path(tmp) / "proof.sqlite"))
            try:
                digest = store.record_evidence(package)
                self.assertEqual(digest, package.digest)
                restored = store.evidence(digest)
                self.assertIsNotNone(restored)
                self.assertEqual(
                    _json.dumps(restored.execution, sort_keys=True, default=str),
                    _json.dumps({"when": str(stamp)}, sort_keys=True, default=str),
                )
            finally:
                store.close()

    def test_output_reconciliation_persistence_failure_is_not_silent(self):
        """P1 (R4): when the state store cannot persist the reconciliation
        marker after a BaseException, the persistence error must surface (chained
        path) instead of being silently swallowed."""
        proof = ProofStore()
        flow = FlowStateMachine()
        task_id, work_id = uuid4(), uuid4()
        execution = Runner().execute(task_id, work_id, flow, lambda: {"value": 1})
        evidence = EvidencePackage(
            str(task_id), str(work_id), "policy:v1", "cap:v1", {}, {"value": 1},
            {"checked": True}, SideEffectState.NOT_APPLICABLE.value, ("artifact:1",),
        )
        digest = Gate(proof).accept(flow, execution.result, evidence)
        output = OutputRuntime(proof)

        def interrupt(_value):
            raise KeyboardInterrupt()

        real_save = output._save

        def failing_save(evidence_digest, record, *, expected_version):
            raise RuntimeError("state store unavailable")

        output._save = failing_save
        try:
            with self.assertRaises(RuntimeError) as error:
                output.publish(digest, interrupt)
            self.assertIn("state store unavailable", str(error.exception))
        finally:
            output._save = real_save


if __name__ == "__main__":
    unittest.main()
