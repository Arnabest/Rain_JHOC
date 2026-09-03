import tempfile
import time
import unittest
from pathlib import Path
import json
import socket
from threading import Thread
from uuid import uuid4

from jhoc.relay import Relay, SQLiteRelay
from jhoc.provider import JHOCProviderClient
from jhoc.supervisor import JHOCSupervisor, JHOCSupervisorServer
from scripts.jhoc_readiness import inspect_readiness
from scripts.jhoc_dispatch import dispatch


class SupervisorTests(unittest.TestCase):
    def test_single_start_persistent_connection_and_correlated_response(self):
        supervisor = JHOCSupervisor(Relay(), poll_interval=0.005).start()
        seen = []
        supervisor.register_provider("codex", lambda payload: (seen.append(payload) or {"echo": payload["value"]}))
        correlation = supervisor.submit({"value": 7}, provider_id="codex")
        response = supervisor.await_response(correlation, timeout=1)
        self.assertIsNotNone(response)
        self.assertEqual(response.payload, {"echo": 7})
        self.assertEqual(seen, [{"value": 7}])
        supervisor.start()
        self.assertTrue(supervisor.health()["running"])
        supervisor.stop()

    def test_unavailable_explicit_provider_does_not_dispatch_to_another_provider(self):
        supervisor = JHOCSupervisor(Relay(), poll_interval=0.005).start()
        called = []
        supervisor.register_provider("codex", lambda payload: (called.append(payload) or payload))
        correlation = supervisor.submit({"value": 1}, provider_id="claude")
        self.assertIsNone(supervisor.await_response(correlation, timeout=0.1))
        self.assertEqual(called, [])
        supervisor.stop()

    def test_durable_response_survives_restart_and_second_start_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "jhoc.db"
            lock = path.with_suffix(".lock")
            first_relay = SQLiteRelay(str(path))
            first = JHOCSupervisor(first_relay, lock_path=lock, poll_interval=0.005).start()
            first.register_provider("gemini", lambda payload: {"ok": payload["value"]})
            correlation = first.submit({"value": 3}, provider_id="gemini")
            self.assertIsNotNone(first.await_response(correlation, timeout=1))
            second_relay = SQLiteRelay(str(path))
            second = JHOCSupervisor(second_relay, lock_path=lock)
            with self.assertRaises(RuntimeError):
                second.start()
            second.stop()
            second_relay.close()
            first.stop()
            first_relay.close()
            restarted_relay = SQLiteRelay(str(path))
            restarted = JHOCSupervisor(restarted_relay, lock_path=lock)
            self.assertEqual(restarted.response(correlation).payload, {"ok": 3})
            restarted.stop()
            restarted_relay.close()

    def test_json_lines_endpoint_exposes_health(self):
        supervisor = JHOCSupervisor(Relay(), poll_interval=0.005).start()
        endpoint = JHOCSupervisorServer(supervisor)
        host, port = endpoint.start()
        try:
            with socket.create_connection((host, port), timeout=1) as connection:
                connection.sendall(b'{"op":"health"}\n')
                value = json.loads(connection.makefile("rb").readline())
            self.assertTrue(value["ok"])
            self.assertEqual(value["route"], "jhoc.supervisor.v1")
        finally:
            endpoint.stop()
            supervisor.stop()

    def test_persistent_provider_client_round_trip(self):
        supervisor = JHOCSupervisor(Relay(), poll_interval=0.005).start()
        endpoint = JHOCSupervisorServer(supervisor)
        host, port = endpoint.start()
        client = JHOCProviderClient("agy-cli", lambda payload: {"echo": payload["value"]}, host=host, port=port, reconnect_delay=0.02)
        thread = Thread(target=client.run_forever, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 1
            while not supervisor.providers() and time.monotonic() < deadline:
                time.sleep(0.01)
            correlation = supervisor.submit({"value": 11}, provider_id="agy-cli")
            response = supervisor.await_response(correlation, timeout=1)
            self.assertEqual(response.payload, {"echo": 11})
        finally:
            client.stop()
            thread.join(timeout=1)
            endpoint.stop()
            supervisor.stop()

    def test_provider_failure_is_not_marked_accepted(self):
        supervisor = JHOCSupervisor(Relay(), poll_interval=0.005).start()
        supervisor.register_provider("codex-cli", lambda payload: {"status": "failed", "error": "quota"})
        try:
            correlation = supervisor.submit({"value": 1}, provider_id="codex-cli")
            response = supervisor.await_response(correlation, timeout=1)
            self.assertEqual(response.status, "failed")
        finally:
            supervisor.stop()

    def test_response_is_bound_to_workflow_session(self):
        supervisor = JHOCSupervisor(Relay(), poll_interval=0.005).start()
        supervisor.register_provider("codex-cli", lambda payload: {"status": "accepted", "final": True})
        try:
            correlation = supervisor.submit({"session_id": "workflow-1", "prompt": "x"}, provider_id="codex-cli")
            response = supervisor.await_response(correlation, timeout=1)
            self.assertEqual(response.session_id, "workflow-1")
        finally:
            supervisor.stop()

    def test_readiness_excludes_probe_only_results_from_model_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "jhoc.db"
            relay = SQLiteRelay(str(db))
            supervisor = JHOCSupervisor(relay, poll_interval=0.005).start()
            endpoint = JHOCSupervisorServer(supervisor)
            host, port = endpoint.start()
            supervisor.register_provider("codex-cli", lambda payload: {"status": "accepted", "final": True, "probe": "jhoc-native-transport"})
            supervisor.register_provider("agy-cli", lambda payload: {"status": "accepted", "final": True, "probe": "jhoc-native-transport"})
            try:
                for provider in ("codex-cli", "agy-cli"):
                    correlation = supervisor.submit({"session_id": "s", "prompt": "x"}, provider_id=provider)
                    self.assertIsNotNone(supervisor.await_response(correlation, timeout=1))
                readiness = inspect_readiness(db, host=host, port=port, session_id="s")
                self.assertTrue(readiness["transport_gate"])
                self.assertFalse(readiness["workflow_gate"])
                self.assertFalse(readiness["model_evidence"])
            finally:
                endpoint.stop()
                supervisor.stop()
                relay.close()

    def test_external_dispatch_requires_same_session_final_results(self):
        supervisor = JHOCSupervisor(Relay(), poll_interval=0.005).start()
        endpoint = JHOCSupervisorServer(supervisor)
        host, port = endpoint.start()
        supervisor.register_provider("codex-cli", lambda payload: {"status": "accepted", "final": True, "model_reply": True})
        supervisor.register_provider("agy-cli", lambda payload: {"status": "accepted", "final": True, "model_reply": True})
        try:
            result = dispatch(host, port, ("codex-cli", "agy-cli"), "workflow-x", "audit", 1)
            self.assertTrue(result["collaboration_gate"])
            self.assertEqual(result["accepted_final_provider_count"], 2)
        finally:
            endpoint.stop()
            supervisor.stop()


if __name__ == "__main__":
    unittest.main()
