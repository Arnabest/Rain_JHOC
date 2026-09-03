import sys
import sqlite3
import subprocess
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier, Thread
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from jhoc.contracts import ContractError, ErrorCode, SideEffectState  # noqa: E402
from jhoc.flow import FlowStateMachine  # noqa: E402
from jhoc.forge import Candidate, SQLiteForge  # noqa: E402
from jhoc.gate import Gate  # noqa: E402
from jhoc.idle import IdleJob, SQLiteIdleScheduler  # noqa: E402
from jhoc.memory_store import MemoryRecord, SQLiteMemoryStore  # noqa: E402
from jhoc.proof import EvidencePackage, SQLiteProofStore  # noqa: E402
from jhoc.storage import SQLiteStore  # noqa: E402
from jhoc.contracts import MessageEnvelope  # noqa: E402
from jhoc.relay import Relay, SQLiteRelay  # noqa: E402
from jhoc.runner import Runner  # noqa: E402


class SQLitePersistenceTests(unittest.TestCase):
    def test_evidence_record_is_idempotent_across_open_connections(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "proof-race.db")
            first, second = SQLiteProofStore(path), SQLiteProofStore(path)
            package = EvidencePackage("t-race", "w", "p:v1", "cap:v1", {}, {}, {"ok": True}, "SUCCEEDED", ("e:1",))
            barrier = Barrier(2)

            def record(store):
                barrier.wait()
                return store.record_evidence(package)

            try:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(record, (first, second)))
                self.assertEqual(results, [package.digest, package.digest])
            finally:
                first.close()
                second.close()

    def test_event_append_is_idempotent_across_open_connections(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "event-race.db")
            first, second = SQLiteStore(path), SQLiteStore(path)
            barrier = Barrier(2)

            def append(store):
                barrier.wait()
                return store.event_append("event:shared", {"value": 1})

            try:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(append, (first, second)))
                self.assertEqual(sorted(results), [False, True])
            finally:
                first.close()
                second.close()

    def test_memory_conflict_rolls_back_before_another_connection_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "memory.db")
            first, second = SQLiteMemoryStore(path), SQLiteMemoryStore(path)
            try:
                record = MemoryRecord({"value": 1}, "TaskMemory", "test:memory", "internal", "memory:same")
                first.write(record, approved=True)
                with self.assertRaises(ContractError) as error:
                    first.write(record, approved=True)
                self.assertEqual(error.exception.code, ErrorCode.IDEMPOTENCY_CONFLICT)
                self.assertFalse(first._db.in_transaction)
                other = MemoryRecord({"value": 2}, "TaskMemory", "test:memory", "internal", "memory:other")
                self.assertEqual(second.write(other, approved=True), other)
            finally:
                first.close()
                second.close()

    def test_idle_mutation_is_reverted_when_persistence_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            scheduler = SQLiteIdleScheduler(str(Path(directory) / "idle.db"))
            job = IdleJob("rollback", job_id="idle:rollback")
            try:
                with patch.object(scheduler, "_sync", side_effect=RuntimeError("write failed")):
                    with self.assertRaisesRegex(RuntimeError, "write failed"):
                        scheduler.submit(job)
                self.assertIsNone(scheduler.get(job.job_id))
            finally:
                scheduler.close()

    def test_forge_allocates_canary_sequence_across_open_instances(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "forge.db")
            setup = SQLiteForge(path)
            candidate = setup.observe(Candidate("adjust scorer", ("evidence:forge",), candidate_id="candidate:shared"))
            setup.evaluate(candidate.candidate_id, regression_free=True, benchmark_ref="bench:forge")
            setup.promote(candidate.candidate_id, approved=True, approved_by="test")
            setup.close()

            first, second = SQLiteForge(path), SQLiteForge(path)
            try:
                self.assertEqual(first.observe_canary(candidate.candidate_id, healthy=True, score=0.9, evidence_ref="canary:1").sequence, 1)
                self.assertEqual(second.observe_canary(candidate.candidate_id, healthy=True, score=0.95, evidence_ref="canary:2").sequence, 2)
            finally:
                first.close()
                second.close()
            reopened = SQLiteForge(path)
            try:
                self.assertEqual(tuple(item.sequence for item in reopened.canary_history(candidate.candidate_id)), (1, 2))
            finally:
                reopened.close()

    def test_state_survives_new_store_instance_and_cas_rejects_stale_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "jhoc.db")
            first = SQLiteStore(path)
            record = first.state_put("core", "counter", {"value": 1})
            first.close()
            second = SQLiteStore(path)
            self.assertEqual(second.state_get("core", "counter").value, {"value": 1})
            with self.assertRaises(ContractError) as error:
                second.state_put("core", "counter", {"value": 2}, expected_version=0)
            self.assertEqual(error.exception.code, ErrorCode.STALE_STATE)
            second.close()

    def test_event_and_artifact_are_durable_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "jhoc.db")
            store = SQLiteStore(path)
            self.assertTrue(store.event_append("e1", {"kind": "started"}))
            self.assertFalse(store.event_append("e1", {"kind": "started"}))
            ref = store.artifact_put("runner", b"bytes", content_type="text/plain")
            store.close()
            reopened = SQLiteStore(path)
            self.assertEqual(reopened.artifact_get(ref, owner="runner"), b"bytes")
            reopened.close()

    def test_proof_digest_is_recoverable_after_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "proof.db")
            package = EvidencePackage("t", "w", "p:v1", "cap:v1", {"expected": 1}, {"actual": 1}, {"ok": True}, "SUCCEEDED", ("a:1",))
            first = SQLiteProofStore(path)
            digest = first.record_evidence(package)
            first.close()
            second = SQLiteProofStore(path)
            self.assertEqual(second.record_evidence(package), digest)
            self.assertEqual(second.evidence(digest), package)
            second.close()

    def test_gate_acceptance_is_enforced_and_survives_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "proof-acceptance.db")
            task_id = uuid4()
            work_id = uuid4()
            flow = FlowStateMachine()
            execution = Runner().execute(task_id, work_id, flow, lambda: {"actual": 1})
            package = EvidencePackage(
                str(task_id), str(work_id), "p:v1", "cap:v1", {"expected": 1}, {"actual": 1},
                {"ok": True}, SideEffectState.NOT_APPLICABLE.value, ("a:1",),
            )
            first = SQLiteProofStore(path)
            try:
                digest = Gate(first).accept(flow, execution.result, package)
                self.assertEqual(first._db.execute("PRAGMA foreign_keys").fetchone(), (1,))
            finally:
                first.close()

            second = SQLiteProofStore(path)
            try:
                self.assertEqual(second.evidence(digest), package)
                receipt = second.acceptance(digest)
                self.assertIsNotNone(receipt)
                self.assertEqual((receipt.task_id, receipt.work_id), (str(task_id), str(work_id)))
            finally:
                second.close()

    def test_concurrent_cas_allows_exactly_one_expected_version_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteStore(str(Path(directory) / "race.db"))
            def write(value):
                try:
                    store.state_put("core", "race", {"value": value}, expected_version=0)
                    return True
                except ContractError as error:
                    self.assertEqual(error.code, ErrorCode.STALE_STATE)
                    return False
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(write, range(8)))
            self.assertEqual(sum(results), 1)
            store.close()

    def test_concurrent_relay_leases_assign_message_once(self):
        relay = Relay()
        envelope = MessageEnvelope("event", "race", "test", {}, "00000000-0000-0000-0000-000000000001")
        relay.enqueue(envelope)
        with ThreadPoolExecutor(max_workers=8) as pool:
            leases = list(pool.map(lambda index: relay.lease(f"worker-{index}"), range(8)))
        self.assertEqual(sum(lease is not None for lease in leases), 1)

    def test_artifact_references_are_isolated_by_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteStore(str(Path(directory) / "artifact.db"))
            first = store.artifact_put("owner-a", b"same", content_type="text/plain")
            second = store.artifact_put("owner-b", b"same", content_type="application/octet-stream")
            self.assertEqual(first.artifact_id, second.artifact_id)
            self.assertEqual(store.artifact_get(first, owner="owner-a"), b"same")
            self.assertEqual(store.artifact_get(second, owner="owner-b"), b"same")
            store.close()

    def test_independent_sqlite_relays_lease_once_and_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "relay.db")
            first, second = SQLiteRelay(path), SQLiteRelay(path)
            envelope = MessageEnvelope("event", "task", "producer", {"priority": 90}, "00000000-0000-0000-0000-000000000002")
            self.assertTrue(first.enqueue(envelope))
            leases = [first.lease("worker-a"), second.lease("worker-b")]
            self.assertEqual(sum(lease is not None for lease in leases), 1)
            lease = next(item for item in leases if item is not None)
            owner = lease.consumer
            (first if owner == "worker-a" else second).nack(str(envelope.message_id), consumer=owner, lease_id=lease.lease_id, retryable=False, error="fatal")
            self.assertEqual(len(first.dead_letters()), 1)
            replayed = second.replay(str(envelope.message_id))
            self.assertEqual(replayed.status.value, "PENDING")
            first.close()
            second.close()

    def test_sqlite_relay_recovers_lease_after_process_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "crash.db")
            child = (
                "import os, sys; "
                "sys.path.insert(0, r'G:\\JHOC\\src'); "
                "from jhoc.relay import SQLiteRelay; from jhoc.contracts import MessageEnvelope; "
                f"r=SQLiteRelay(r'{path}', lease_seconds=1); "
                "e=MessageEnvelope('event','crash','worker',{},'00000000-0000-0000-0000-000000000004'); "
                "r.enqueue(e); r.lease('crashed'); os._exit(0)"
            )
            completed = subprocess.run([sys.executable, "-c", child], timeout=30)
            self.assertEqual(completed.returncode, 0)
            recovered = SQLiteRelay(path)
            lease = recovered.lease("recovery", now=datetime.now(timezone.utc) + timedelta(seconds=2))
            self.assertIsNotNone(lease)
            self.assertEqual(lease.consumer, "recovery")
            self.assertEqual(lease.attempts, 2)
            recovered.close()

    def test_sqlite_relay_starts_lease_clock_after_write_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "lease-contention.db")
            relay = SQLiteRelay(path, lease_seconds=1.0)
            try:
                relay.enqueue(MessageEnvelope(
                    "event", "lease", "producer", {},
                    "00000000-0000-0000-0000-000000000007",
                ))
                holder = sqlite3.connect(path, timeout=30)
                worker = None
                try:
                    holder.execute("BEGIN IMMEDIATE")
                    result = []
                    worker = Thread(target=lambda: result.append(relay.lease("worker")))
                    worker.start()
                    # Hold the lock past the old implementation's clock start,
                    # while leaving enough margin for the returned lease.
                    import time
                    time.sleep(1.2)
                finally:
                    holder.commit()
                    holder.close()
                    if worker is not None:
                        worker.join(timeout=5)
                self.assertEqual(len(result), 1)
                self.assertIsNotNone(result[0])
                self.assertGreater(
                    result[0].lease_until - datetime.now(timezone.utc),
                    timedelta(seconds=0.5),
                )
            finally:
                relay.close()

    def test_sqlite_relay_applies_bounded_backpressure(self):
        with tempfile.TemporaryDirectory() as directory:
            relay = SQLiteRelay(str(Path(directory) / "pressure.db"), max_pending=1)
            first = MessageEnvelope("event", "pressure", "producer", {}, "00000000-0000-0000-0000-000000000005")
            second = MessageEnvelope("event", "pressure", "producer", {}, "00000000-0000-0000-0000-000000000006")
            self.assertTrue(relay.enqueue(first))
            with self.assertRaises(ContractError) as error:
                relay.enqueue(second)
            self.assertEqual(error.exception.code, ErrorCode.POLICY_DENIED)
            relay.close()

    def test_sqlite_relay_sustains_long_run_unique_ack_delivery(self):
        with tempfile.TemporaryDirectory() as directory:
            relay = SQLiteRelay(str(Path(directory) / "long-run.db"))
            try:
                envelopes = [
                    MessageEnvelope("event", "pressure", "producer", {"priority": index % 100}, f"00000000-0000-0000-0000-{index + 7:012d}")
                    for index in range(1000)
                ]
                for envelope in envelopes:
                    self.assertTrue(relay.enqueue(envelope))
                seen = set()
                for index in range(1000):
                    lease = relay.lease(f"worker-{index % 8}")
                    self.assertIsNotNone(lease)
                    message_id = str(lease.envelope.message_id)
                    self.assertNotIn(message_id, seen)
                    seen.add(message_id)
                    relay.ack(message_id, consumer=lease.consumer, lease_id=lease.lease_id)
                self.assertEqual(len(seen), 1000)
                self.assertIsNone(relay.lease("drain-check"))
            finally:
                relay.close()

    def test_multi_process_fault_storm_competitors_ack_each_message_once(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "storm.db")
            relay = SQLiteRelay(path, lease_seconds=2)
            for index in range(200):
                relay.enqueue(MessageEnvelope("event", "storm", "producer", {"priority": index % 100}, f"00000000-0000-0000-0000-{index + 1007:012d}"))
            relay.close()
            worker = (
                "import sys, time; "
                "sys.path.insert(0, r'G:\\JHOC\\src'); "
                "from jhoc.relay import SQLiteRelay; "
                f"r=SQLiteRelay(r'{path}', lease_seconds=2); count=0; "
                "\nwhile True:\n"
                "  item=r.lease('storm-worker')\n"
                "  if item is None: break\n"
                "  r.ack(str(item.envelope.message_id), consumer=item.consumer, lease_id=item.lease_id); count += 1\n"
                "print(count); r.close()"
            )
            processes = [subprocess.Popen([sys.executable, "-c", worker], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(4)]
            outputs = [process.communicate(timeout=30) for process in processes]
            self.assertTrue(all(process.returncode == 0 for process in processes), outputs)
            self.assertEqual(sum(int(stdout.strip() or "0") for stdout, _ in outputs), 200)
            check = SQLiteRelay(path)
            try:
                self.assertEqual(check.pending_count(), 0)
            finally:
                check.close()


if __name__ == "__main__":
    unittest.main()
