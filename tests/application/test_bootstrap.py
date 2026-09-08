import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from jhoc import ApplicationConfig, JHOCApplication, create_application  # noqa: E402
from jhoc.atlas import KnowledgeRecord, KnowledgeStatus  # noqa: E402
from jhoc.commons import CommunityMessage, SQLiteCommons  # noqa: E402
from jhoc.graph import GraphNode, GraphRelation  # noqa: E402
from jhoc.guard import PolicyBundle, PolicyRequest, PolicyRule, SQLiteGuardRuntime  # noqa: E402
from jhoc.memory_store import MemoryRecord  # noqa: E402
from jhoc.idle import IdleJob, IdleStatus  # noqa: E402
from jhoc.forge import Candidate, CandidateStatus  # noqa: E402
from jhoc.restore import RecoveryStage, RestoreManifest  # noqa: E402
from jhoc.config import RuntimeMode  # noqa: E402
from jhoc.lens import LogEntry, SQLiteLensCollector  # noqa: E402
from jhoc.trust import Identity, IdentityType, PermissionSet, SQLiteTrustStore  # noqa: E402


class ApplicationBootstrapTests(unittest.TestCase):
    def test_application_assembles_and_starts_without_external_services(self):
        app = JHOCApplication()
        health = app.start()
        self.assertTrue(health.running)
        self.assertEqual(health.origin_state, "RUNNING")
        self.assertEqual(health.module_count, 31)
        self.assertFalse(health.legacy_runtime_connected)
        self.assertTrue(health.channel_gateway_ready)
        self.assertEqual(health.channel_gateway_sources, ("aibox", "verse-agent"))
        self.assertIsNotNone(app.atlas)
        self.assertIsNotNone(app.graph)
        self.assertIsNotNone(app.memory)
        self.assertIsNotNone(app.ingest)
        self.assertIs(app.migration.scanner, app.ingest)
        self.assertIsInstance(create_application(), JHOCApplication)
        app.stop()
        self.assertFalse(app.health().running)

    def test_durable_application_reopens_with_shared_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "jhoc.db"
            first = JHOCApplication(ApplicationConfig(path))
            first.state_store.put("core", "boot", {"ready": True})
            first.event_store.append("booted", {"state": "RUNNING"})
            knowledge = first.atlas.ingest(KnowledgeRecord({"fact": 7}, "FACT", "task:durable", "internal", record_id="knowledge:durable"))
            first.atlas.transition(knowledge.record_id, KnowledgeStatus.PARSED)
            first.memory.write(MemoryRecord({"note": "persist"}, "TaskMemory", "task:durable", "confidential", "memory:durable"), approved=True)
            first.graph.add_node(GraphNode("task:durable", "Task"))
            first.graph.add_node(GraphNode("knowledge:durable", "Knowledge"))
            first.graph.add_relation(GraphRelation("relation:durable", "task:durable", "knowledge:durable", "supports", 0.9, "task:durable", "VERIFIED", "SUPPORTED"))
            idle = first.idle.submit(IdleJob("durable-index", job_id="idle:durable"))
            first.idle.start_next()
            first.idle.checkpoint(idle.job_id, {"cursor": 12})
            first.idle.preempt_for_foreground()
            candidate = first.forge.observe(Candidate("adjust durable reranker", ("evidence:durable",), candidate_id="candidate:durable", version="2"))
            first.forge.evaluate(candidate.candidate_id, regression_free=True, benchmark_ref="bench:durable")
            first.forge.promote(candidate.candidate_id, approved=True, approved_by="operator:durable")
            first.forge.observe_canary(candidate.candidate_id, healthy=True, score=0.98, evidence_ref="canary:1")
            first.restore.restore(RestoreManifest("snapshot:durable", tuple(RecoveryStage)), mode=RuntimeMode.EMERGENCY_SAFE_MODE)
            first.lens.emit(LogEntry("durable trace", "test", task_id="task:durable", fields={"token": "hidden"}))
            first.lens.record_event({"event": "started", "task_id": "task:durable"})
            first.lens.record_audit({"operation": "boot", "task_id": "task:durable"})
            first.lens.record_evidence({"digest": "evidence:durable", "task_id": "task:durable"})
            owner = first.trust.register(
                Identity(
                    "durable-user",
                    IdentityType.USER,
                    PermissionSet(frozenset({"task.read", "commons.post"})),
                )
            )
            key = first.trust.issue_key(owner.identity_id, "sha256:durable", key_id="key:durable")
            session = first.trust.open_session(owner.identity_id, key.key_id, "sha256:durable")
            first.guard.load(
                PolicyBundle("policy:durable", "local", (PolicyRule("read", "ALLOW", frozenset({"task.read"}), 1),))
            )
            first.guard.evaluate(owner, PolicyRequest("task.read", 0))
            first.commons.publish(
                CommunityMessage(
                    "POST", "durable-user", {"text": "durable"}, ("evidence:durable",), verified=True
                ),
                eligible_evidence=True,
                identity_id=str(owner.identity_id),
                session_id=session.session_id,
            )
            first.stop()

            second = JHOCApplication(ApplicationConfig(path))
            self.assertEqual(second.state_store.get("core", "boot").value, {"ready": True})
            self.assertEqual(second.event_store.read("booted"), {"state": "RUNNING"})
            self.assertIs(second.core.state_store, second.state_store)
            self.assertIs(second.core.event_store, second.event_store)
            self.assertIs(second.core.artifact_store, second.artifact_store)
            self.assertEqual(second.atlas.get("knowledge:durable").status, KnowledgeStatus.PARSED)
            self.assertEqual(len(second.atlas.history("knowledge:durable")), 2)
            self.assertEqual(second.memory.get("memory:durable").sensitivity, "CONFIDENTIAL")
            self.assertEqual(second.graph.relations_by_quality("SUPPORTED")[0].relation_id, "relation:durable")
            self.assertEqual(second.idle.get("idle:durable").status, IdleStatus.PAUSED)
            self.assertEqual(second.idle.get("idle:durable").checkpoint, {"cursor": 12})
            self.assertEqual(second.idle.resume("idle:durable").status, IdleStatus.QUEUED)
            self.assertEqual(second.forge.get("candidate:durable").status, CandidateStatus.CANARY)
            self.assertEqual(second.forge.canary_history("candidate:durable")[0].score, 0.98)
            self.assertEqual(second.forge.complete_canary("candidate:durable", healthy=True, score=0.99).status, CandidateStatus.PROMOTED)
            self.assertEqual(second.restore.audit_records()[0].snapshot_id, "snapshot:durable")
            self.assertEqual(second.restore.audit_records()[0].stages, (RecoveryStage.IDENTITY, RecoveryStage.POLICY, RecoveryStage.STORAGE))
            self.assertIsInstance(second.lens, SQLiteLensCollector)
            self.assertEqual(second.lens.module_logs("test")[0].fields["token"], "[REDACTED]")
            self.assertEqual(second.lens.module_logs("test")[0].task_id, "task:durable")
            self.assertEqual(second.lens.events[0]["event"], "started")
            self.assertEqual(second.lens.audits[0]["operation"], "boot")
            self.assertEqual(second.lens.evidence[0]["digest"], "evidence:durable")
            self.assertEqual(
                [item.record_type for item in second.lens.reconstruct(task_id="task:durable")],
                ["log", "event", "audit", "evidence"],
            )
            self.assertIsInstance(second.trust, SQLiteTrustStore)
            self.assertTrue(second.trust.authenticate(owner.identity_id, key.key_id, "sha256:durable"))
            self.assertTrue(second.trust.authorize(owner.identity_id, "task.read", session_id=session.session_id))
            self.assertIsInstance(second.guard, SQLiteGuardRuntime)
            self.assertEqual(second.guard.bundle_history()[-1].version, "policy:durable")
            self.assertEqual(second.guard.decisions(policy_ref="policy:durable")[0].operation, "task.read")
            self.assertIsInstance(second.commons, SQLiteCommons)
            self.assertEqual(second.commons.messages()[0].content, {"text": "durable"})
            second.stop()

    def test_partial_durable_initialization_closes_open_handles(self):
        class Handle:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

        storage = Handle()
        trust = Handle()
        guard = Handle()
        registry = Handle()
        shelf = Handle()
        quota = Handle()
        with patch("jhoc.application.SQLiteStore", return_value=storage), patch(
            "jhoc.application.SQLiteTrustStore", return_value=trust
        ), patch(
            "jhoc.application.SQLiteGuardRuntime", return_value=guard
        ), patch(
            "jhoc.application.SQLiteCapabilityRegistry", return_value=registry
        ), patch(
            "jhoc.application.SQLiteShelf", return_value=shelf
        ), patch(
            "jhoc.application.SQLiteQuotaManager", return_value=quota
        ), patch("jhoc.application.SQLiteRelay", side_effect=RuntimeError("injected open failure")):
            with self.assertRaisesRegex(RuntimeError, "injected open failure"):
                JHOCApplication(ApplicationConfig("unused.db"))
        self.assertTrue(trust.closed)
        self.assertTrue(guard.closed)
        self.assertTrue(storage.closed)
        self.assertTrue(registry.closed)
        self.assertTrue(shelf.closed)
        self.assertTrue(quota.closed)

    def test_late_assembly_failure_releases_all_durable_connections(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "late-failure.db"
            with patch("jhoc.application.CoreRuntime", side_effect=RuntimeError("late assembly failure")):
                with self.assertRaisesRegex(RuntimeError, "late assembly failure"):
                    JHOCApplication(ApplicationConfig(path))
            path.unlink()

    def test_stop_marks_application_closed_even_if_one_handle_close_fails(self):
        class Handle:
            def __init__(self, fail=False):
                self.fail = fail
                self.closed = False

            def close(self):
                self.closed = True
                if self.fail:
                    raise RuntimeError("close failed")

        app = JHOCApplication()
        app.start()
        failing, healthy = Handle(True), Handle()
        app._durable_handles = (failing, healthy)
        with self.assertRaisesRegex(RuntimeError, "close failed"):
            app.stop()
        self.assertTrue(app._closed)
        self.assertEqual(app._durable_handles, ())
        self.assertTrue(failing.closed)
        self.assertTrue(healthy.closed)

    def test_start_failure_closes_durable_handles_and_application(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "start-failure.db"
            app = JHOCApplication(ApplicationConfig(path))
            with patch.object(app.core, "start", side_effect=RuntimeError("injected start failure")):
                with self.assertRaisesRegex(RuntimeError, "injected start failure"):
                    app.start()
            self.assertTrue(app._closed)
            self.assertEqual(app._durable_handles, ())
            with self.assertRaisesRegex(RuntimeError, "application is closed"):
                app.start()
            path.unlink()


if __name__ == "__main__":
    unittest.main()
