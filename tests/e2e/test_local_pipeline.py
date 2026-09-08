import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from jhoc import ApplicationConfig, JHOCApplication  # noqa: E402
from jhoc.context import ContextSource  # noqa: E402
from jhoc.contracts import PluginManifest, WorkItem  # noqa: E402
from jhoc.conductor import CapabilityRequest  # noqa: E402
from jhoc.guard import PolicyBundle, PolicyRequest, PolicyRule  # noqa: E402
from jhoc.proof import EvidencePackage  # noqa: E402
from jhoc.registry import CapabilityRecord  # noqa: E402
from jhoc.trust import Identity, IdentityType, PermissionSet  # noqa: E402
from jhoc.quota import ResourcePlan  # noqa: E402
from jhoc.output import DeliveryState  # noqa: E402
from jhoc.flow import FlowStateMachine  # noqa: E402


class LocalPipelineTests(unittest.TestCase):
    def test_task_to_output_pipeline_is_verified_and_idempotent(self):
        app = JHOCApplication()
        app.start()
        app.guard.load(PolicyBundle("policy:v1", "local", (PolicyRule("task", "ALLOW", frozenset({"task.local"}), 1),)))
        manifest = PluginManifest("local.echo", "Local Echo", "1.0.0", "1.0", "capability", verification_status="VERIFIED", shelf_eligible=True)
        app.registry.register(CapabilityRecord("local.echo", "1.0.0", manifest, "schema:in", "schema:out"))
        app.shelf.admit(app.registry.verify("local.echo", "1.0.0", health="HEALTHY"))
        identity = Identity("user", IdentityType.USER, PermissionSet())
        item = WorkItem(uuid4(), "task.local", {"value": 7}, "task-once")
        plan = app.conductor.select(identity, PolicyRequest("task.local", 0), CapabilityRequest("task.local", (("local.echo", "1.0.0"),), ResourcePlan(cpu_units=1, memory_mb=128, token_budget=100)), mode="OFFLINE")
        self.assertIsNotNone(plan.lease_id)
        context_a = app.context.pass_a("echo 7", {"work_id": str(item.work_id)}, policy_ref="policy:v1")
        context_b = app.context.pass_b(
            context_a,
            (
                ContextSource(
                    "task",
                    {"value": 7},
                    "public",
                    datetime.now(timezone.utc) + timedelta(minutes=5),
                    frozenset({"runner"}),
                    ("work-item:task",),
                ),
            ),
            authorized_source_ids=frozenset({"task"}),
            consumer_id="runner",
            resource_plan_ref=plan.lease_id,
        )
        self.assertEqual(len(context_b.sources), 1)
        calls = []
        flow = FlowStateMachine()
        execution = app.runner.execute(
            item.task_id,
            item.work_id,
            flow,
            lambda: (calls.append(1) or {"echo": 7}),
            operation_id=item.idempotency_key,
            side_effecting=True,
        )
        evidence = EvidencePackage(str(item.task_id), str(item.work_id), "policy:v1", "local.echo@1.0.0", {"value": 7}, execution.result.output, {"context": context_b.snapshot_id}, "SUCCEEDED", ("artifact:local",))
        digest = app.gate.accept(flow, execution.result, evidence)
        delivered = app.output.publish(digest, lambda value: None)
        app.conductor.release(plan)
        self.assertEqual(delivered.state, DeliveryState.DELIVERED)
        self.assertEqual(flow.state.value, "COMPLETE")
        self.assertEqual(len(calls), 1)
        app.stop()

    def test_durable_proof_survives_application_restart_without_action_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            config = ApplicationConfig(Path(directory) / "jhoc.db")
            calls = []
            first = JHOCApplication(config)
            first.start()
            item = WorkItem(uuid4(), "task.local", {"value": 9}, "restart-once")
            flow = FlowStateMachine()
            execution = first.runner.execute(
                item.task_id,
                item.work_id,
                flow,
                lambda: (calls.append(1) or {"echo": 9}),
                operation_id=item.idempotency_key,
                side_effecting=True,
            )
            evidence = EvidencePackage(
                str(item.task_id), str(item.work_id), "policy:v1", "local.echo@1.0.0", {"value": 9},
                execution.result.output, {"restart": True}, "SUCCEEDED", ("artifact:restart",),
            )
            digest = first.gate.accept(flow, execution.result, evidence)
            first.stop()

            second = JHOCApplication(config)
            self.assertIsNotNone(second.proof.evidence(digest))
            replay = second.runner.execute(
                item.task_id,
                item.work_id,
                FlowStateMachine(),
                lambda: (calls.append(2) or {"echo": 999}),
                operation_id=item.idempotency_key,
                side_effecting=True,
            )
            self.assertEqual(replay.result.output, {"echo": 9})
            delivered = second.output.publish(digest, lambda value: None)
            self.assertEqual(delivered.state, DeliveryState.DELIVERED)
            self.assertEqual(len(calls), 1)
            second.stop()

    def test_durable_context_snapshot_rebuilds_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            config = ApplicationConfig(Path(directory) / "jhoc.db")
            first = JHOCApplication(config)
            pass_a = first.context.pass_a("rebuild", {"task": "durable"}, policy_ref="policy:v1")
            package = first.context.pass_b(
                pass_a,
                (
                    ContextSource(
                        "source:durable",
                        {"value": 1},
                        "internal",
                        datetime.now(timezone.utc) + timedelta(minutes=5),
                        frozenset({"runner"}),
                        ("artifact:durable",),
                    ),
                ),
                authorized_source_ids=frozenset({"source:durable"}),
                consumer_id="runner",
                resource_plan_ref="lease:durable",
            )
            first.stop()

            second = JHOCApplication(config)
            rebuilt = second.context.rebuild(package.snapshot_id)
            self.assertEqual(rebuilt, package)
            second.stop()

    def test_failed_output_delivery_can_retry_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            config = ApplicationConfig(Path(directory) / "jhoc.db")
            task_id, work_id = uuid4(), uuid4()
            first = JHOCApplication(config)
            flow = FlowStateMachine()
            execution = first.runner.execute(task_id, work_id, flow, lambda: {"value": 1})
            evidence = EvidencePackage(
                str(task_id), str(work_id), "policy:v1", "cap:v1", {}, {"value": 1},
                {"ok": True}, "NOT_APPLICABLE", ("artifact:output-retry",),
            )
            digest = first.gate.accept(flow, execution.result, evidence)
            failed = first.output.publish(
                digest, lambda value: (_ for _ in ()).throw(RuntimeError("offline"))
            )
            self.assertEqual(failed.state, DeliveryState.FAILED)
            first.stop()

            delivered_values = []
            second = JHOCApplication(config)
            delivered = second.output.retry(digest, delivered_values.append)
            self.assertEqual(delivered.state, DeliveryState.DELIVERED)
            self.assertEqual(delivered_values, [digest])
            second.stop()

    def test_interrupted_output_can_be_reconciled_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            config = ApplicationConfig(Path(directory) / "jhoc.db")
            task_id, work_id = uuid4(), uuid4()
            first = JHOCApplication(config)
            flow = FlowStateMachine()
            execution = first.runner.execute(task_id, work_id, flow, lambda: {"value": 1})
            evidence = EvidencePackage(
                str(task_id), str(work_id), "policy:v1", "cap:v1", {}, {"value": 1},
                {"ok": True}, "NOT_APPLICABLE", ("artifact:output-reconcile",),
            )
            digest = first.gate.accept(flow, execution.result, evidence)

            def interrupt(_value):
                raise KeyboardInterrupt()

            with self.assertRaises(KeyboardInterrupt):
                first.output.publish(digest, interrupt)
            first.stop()

            second = JHOCApplication(config)
            reconciled = second.output.reconcile(digest, delivered=False, reason="sender outcome unknown")
            self.assertEqual(reconciled.state, DeliveryState.FAILED)
            delivered_values = []
            delivered = second.output.retry(digest, delivered_values.append)
            self.assertEqual(delivered.state, DeliveryState.DELIVERED)
            self.assertEqual(delivered_values, [digest])
            second.stop()

    def test_durable_in_doubt_operation_requires_reconciliation_without_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            config = ApplicationConfig(Path(directory) / "jhoc.db")
            task_id, work_id = uuid4(), uuid4()
            first = JHOCApplication(config)
            first.runner.journal.claim("crash-window", str(task_id), str(work_id))
            first.stop()

            calls = []
            second = JHOCApplication(config)
            execution = second.runner.execute(
                task_id,
                work_id,
                FlowStateMachine(),
                lambda: (calls.append(1) or {"unsafe": True}),
                operation_id="crash-window",
                side_effecting=True,
            )
            self.assertEqual(calls, [])
            self.assertEqual(execution.result.side_effect_state.value, "UNKNOWN_SIDE_EFFECT")
            self.assertEqual(execution.state.value, "BLOCKED")
            self.assertEqual(second.runner.journal.get("crash-window").state.value, "REQUIRES_RECONCILIATION")
            second.stop()


if __name__ == "__main__":
    unittest.main()
