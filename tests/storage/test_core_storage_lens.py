import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from jhoc.contracts import ContractError, ErrorCode  # noqa: E402
from jhoc.core import CoreRuntime, CoreState  # noqa: E402
from jhoc.lens import LogEntry, LensCollector  # noqa: E402
from jhoc.storage import ArtifactStore, EventStore, StateStore  # noqa: E402


class P6StorageLensTests(unittest.TestCase):
    def test_state_store_is_owner_scoped_and_cas_protected(self):
        store = StateStore()
        first = store.put("core", "mode", {"value": 1})
        self.assertEqual(store.get("other", "mode"), None)
        with self.assertRaises(ContractError) as error:
            store.put("core", "mode", {"value": 2}, expected_version=0)
        self.assertEqual(error.exception.code, ErrorCode.STALE_STATE)
        store.put("core", "mode", {"value": 2}, expected_version=first.version)

    def test_event_store_is_append_only_and_idempotent(self):
        store = EventStore()
        self.assertTrue(store.append("e1", {"kind": "started"}))
        self.assertFalse(store.append("e1", {"kind": "started"}))
        with self.assertRaises(ContractError):
            store.append("e1", {"kind": "changed"})

    def test_artifact_store_enforces_owner(self):
        store = ArtifactStore()
        reference = store.put("runner", b"data")
        self.assertEqual(store.get(reference, owner="runner"), b"data")
        with self.assertRaises(ContractError) as error:
            store.get(reference, owner="other")
        self.assertEqual(error.exception.code, ErrorCode.POLICY_DENIED)

    def test_lens_redacts_and_routes_by_module(self):
        lens = LensCollector()
        entry = lens.emit(LogEntry("request", "relay", fields={"api_key": "secret", "nested": {"password": "pw"}}))
        self.assertEqual(entry.fields["api_key"], "[REDACTED]")
        self.assertEqual(entry.fields["nested"]["password"], "[REDACTED]")
        self.assertEqual(len(lens.module_logs("relay")), 1)
        self.assertEqual(lens.module_logs("core"), ())
        lens.emit(LogEntry("non-string key", "relay", fields={1: {"secret": "x"}}))

    def test_lens_reconstructs_correlated_records_in_observation_order(self):
        lens = LensCollector()
        lens.emit(LogEntry("execute", "runner", task_id="task:1", work_id="work:1", trace_id="trace:1"))
        lens.record_event({"event": "observed", "task_id": "task:1", "work_id": "work:1", "trace_id": "trace:1"})
        lens.record_audit({"operation": "verify", "task_id": "task:1", "work_id": "work:1", "trace_id": "trace:1"})
        lens.record_evidence({"digest": "proof:1", "task_id": "task:1", "work_id": "work:1", "trace_id": "trace:1"})
        lens.record_event({"event": "other", "task_id": "task:2"})

        trace = lens.reconstruct(task_id="task:1", work_id="work:1")
        self.assertEqual([item.record_type for item in trace], ["log", "event", "audit", "evidence"])
        self.assertEqual([item.sequence for item in trace], [1, 2, 3, 4])
        self.assertEqual(len(lens.reconstruct(trace_id="trace:1")), 4)
        with self.assertRaises(ValueError):
            lens.reconstruct()

    def test_core_starts_independently_and_stops(self):
        core = CoreRuntime()
        self.assertEqual(core.start().state, CoreState.RUNNING)
        self.assertEqual(core.health().storage_ready, True)
        self.assertEqual(len(core.lens.module_logs("core")), 1)
        core.stop()
        self.assertEqual(core.state, CoreState.STOPPED)


if __name__ == "__main__":
    unittest.main()
