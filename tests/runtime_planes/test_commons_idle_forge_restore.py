import sys
import unittest
import time
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from jhoc.commons import Commons, CommunityMessage, SQLiteCommons  # noqa: E402
from jhoc.contracts import ContractError  # noqa: E402
from jhoc.forge import Candidate, CandidateStatus, Forge  # noqa: E402
from jhoc.idle import IdleJob, IdleScheduler, IdleStatus  # noqa: E402
from jhoc.restore import DatabaseSnapshot, RecoveryManager, RecoveryStage, RestoreManifest  # noqa: E402
from jhoc.config import RuntimeMode  # noqa: E402
from jhoc.bench import Bench, BenchmarkCase  # noqa: E402
from jhoc.trust import Identity, IdentityType, PermissionSet, SQLiteTrustStore, TrustStore  # noqa: E402


class RuntimePlaneTests(unittest.TestCase):
    def test_commons_requires_verified_evidence(self):
        trust = TrustStore()
        identity = trust.register(
            Identity("agent", IdentityType.AGENT, PermissionSet(frozenset({"commons.post"})))
        )
        commons = Commons(trust)
        message = CommunityMessage("POST", "agent", {"text": "review"}, ("evidence:1",), verified=True)
        commons.publish(message, eligible_evidence=True, identity_id=str(identity.identity_id))
        with self.assertRaises(ContractError):
            commons.publish(
                CommunityMessage("POST", "agent", {"text": "bad"}, ("evidence:2",), verified=False),
                eligible_evidence=False,
                identity_id=str(identity.identity_id),
            )

    def test_commons_rejects_author_impersonation_and_missing_type_permission(self):
        trust = TrustStore()
        identity = trust.register(
            Identity("agent", IdentityType.AGENT, PermissionSet(frozenset({"commons.post"})))
        )
        commons = Commons(trust)
        with self.assertRaises(ContractError):
            commons.publish(
                CommunityMessage("POST", "other", {"text": "impersonated"}, ("evidence:1",), verified=True),
                eligible_evidence=True,
                identity_id=str(identity.identity_id),
            )
        with self.assertRaises(ContractError):
            commons.publish(
                CommunityMessage("REVIEW", "agent", {"text": "review"}, ("evidence:2",), verified=True),
                eligible_evidence=True,
                identity_id=str(identity.identity_id),
            )

    def test_sqlite_commons_rejects_non_serializable_content_without_memory_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "commons.db")
            trust = SQLiteTrustStore(path)
            identity = trust.register(
                Identity("agent", IdentityType.AGENT, PermissionSet(frozenset({"commons.post"})))
            )
            commons = SQLiteCommons(path, trust)
            with self.assertRaises(TypeError):
                commons.publish(
                    CommunityMessage("POST", "agent", {"bad": {1}}, ("evidence:1",), verified=True),
                    eligible_evidence=True,
                    identity_id=str(identity.identity_id),
                )
            self.assertEqual(commons.messages(), ())
            commons.close(); trust.close()

    def test_community_timestamps_are_created_per_message(self):
        first = CommunityMessage("POST", "agent", {"text": "one"}, ("evidence:1",), verified=True)
        time.sleep(0.001)
        second = CommunityMessage("POST", "agent", {"text": "two"}, ("evidence:2",), verified=True)
        self.assertLess(first.created_at, second.created_at)

    def test_idle_job_is_preempted_and_resumable(self):
        scheduler = IdleScheduler()
        job = scheduler.submit(IdleJob("index", priority=1))
        self.assertEqual(scheduler.start_next().status, IdleStatus.RUNNING)
        scheduler.preempt_for_foreground()
        self.assertEqual(scheduler.resume(job.job_id).status, IdleStatus.QUEUED)

    def test_forge_never_promotes_without_approval(self):
        forge = Forge()
        candidate = forge.observe(Candidate("adjust ranking", ("evidence:1",)))
        candidate = forge.evaluate(candidate.candidate_id, regression_free=True)
        self.assertEqual(candidate.status, CandidateStatus.APPROVAL_REQUIRED)
        with self.assertRaises(ContractError):
            forge.promote(candidate.candidate_id, approved=False)
        self.assertEqual(forge.promote(candidate.candidate_id, approved=True).status, CandidateStatus.CANARY)

    def test_safe_restore_limits_stages(self):
        manifest = RestoreManifest("snap:1", tuple(RecoveryStage))
        restored = RecoveryManager().restore(manifest, mode=RuntimeMode.EMERGENCY_SAFE_MODE)
        self.assertEqual(restored, (RecoveryStage.IDENTITY, RecoveryStage.POLICY, RecoveryStage.STORAGE))

    def test_idle_foreground_gate_checkpoint_and_expiry(self):
        now = datetime.now(timezone.utc)
        scheduler = IdleScheduler(clock=lambda: now)
        job = scheduler.submit(IdleJob("maintenance", ttl_seconds=1, token_budget=5, created_at=now))
        self.assertIsNone(scheduler.start_next(foreground_active=True, now=now))
        running = scheduler.start_next(now=now)
        self.assertEqual(running.status, IdleStatus.RUNNING)
        scheduler.checkpoint(job.job_id, {"cursor": 9})
        scheduler.preempt_for_foreground()
        self.assertEqual(scheduler.get(job.job_id).checkpoint, {"cursor": 9})
        scheduler.resume(job.job_id)
        self.assertIsNone(scheduler.start_next(now=now + timedelta(seconds=2)))
        self.assertEqual(scheduler.get(job.job_id).status, IdleStatus.EXPIRED)

    def test_forge_full_canary_promotion_and_rollback(self):
        forge = Forge()
        good = forge.observe(Candidate("adjust retrieval ranking", ("evidence:1",)))
        evaluated = forge.evaluate(good.candidate_id, regression_free=True, replay_complete=True, safety_passed=True, benchmark_ref="bench:1")
        self.assertEqual(evaluated.status, CandidateStatus.APPROVAL_REQUIRED)
        canary = forge.promote(good.candidate_id, approved=True, approved_by="operator:1")
        self.assertEqual(canary.approved_by, "operator:1")
        self.assertEqual(forge.complete_canary(good.candidate_id, healthy=True, score=0.99).status, CandidateStatus.PROMOTED)

        bad = forge.observe(Candidate("adjust context compression", ("evidence:2",)))
        forge.evaluate(bad.candidate_id, regression_free=True, benchmark_ref="bench:2")
        forge.promote(bad.candidate_id, approved=True)
        rolled_back = forge.complete_canary(bad.candidate_id, healthy=False, score=0.2, rollback_reason="quality regression")
        self.assertEqual(rolled_back.status, CandidateStatus.ROLLED_BACK)
        self.assertEqual(rolled_back.rollback_reason, "quality regression")

        governance = forge.observe(Candidate("change governance permission", ("evidence:3",)))
        self.assertEqual(forge.evaluate(governance.candidate_id, regression_free=True).status, CandidateStatus.REJECTED)

        benchmark = Bench().run((BenchmarkCase("replay", 1, lambda actual, expected: actual == expected),), lambda _: 1)
        replayed = forge.observe(Candidate("adjust reranker", ("evidence:4",)))
        self.assertEqual(forge.evaluate(replayed.candidate_id, regression_free=True, benchmark_result=benchmark).status, CandidateStatus.APPROVAL_REQUIRED)
        failed_benchmark = Bench().run((BenchmarkCase("replay-fail", 2, lambda actual, expected: actual == expected),), lambda _: 1)
        rejected = forge.observe(Candidate("adjust reranker", ("evidence:5",)))
        self.assertEqual(forge.evaluate(rejected.candidate_id, regression_free=True, benchmark_result=failed_benchmark).status, CandidateStatus.REJECTED)

    def test_restore_audits_success_and_injected_integrity_failure(self):
        manager = RecoveryManager()
        with tempfile.TemporaryDirectory() as directory:
            snapshot_path = Path(directory) / "bad.sqlite3"
            snapshot_path.write_bytes(b"not-a-database")
            corrupted = DatabaseSnapshot("bad", str(snapshot_path), "0" * 64, snapshot_path.stat().st_size)
            with self.assertRaisesRegex(ValueError, "integrity"):
                manager.restore_database(corrupted, Path(directory) / "restored.sqlite3")
        audit = manager.audit_records()[-1]
        self.assertEqual(audit.status, "FAILED")
        self.assertEqual(audit.error, "ValueError")


if __name__ == "__main__":
    unittest.main()
