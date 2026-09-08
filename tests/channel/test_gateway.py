import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from jhoc.channel import ChannelGateway  # noqa: E402
from jhoc.contracts import ContractError, MessageEnvelope  # noqa: E402
from jhoc.relay import DeliveryStatus, Relay, SQLiteRelay  # noqa: E402


class ChannelGatewayTests(unittest.TestCase):
    def test_allowlist_and_correlation_bound_ack(self):
        gateway = ChannelGateway(Relay())
        correlation_id = uuid4()
        receipt = gateway.accept("aibox", "probe", {"value": 1}, correlation_id=correlation_id)
        self.assertEqual(receipt.source_id, "aibox")
        self.assertEqual(receipt.correlation_id, str(correlation_id))
        self.assertEqual(receipt.status, DeliveryStatus.ACKED.value)
        self.assertFalse(receipt.durable)
        with self.assertRaises(ContractError):
            gateway.accept("legacy-agent-bus", "probe", {})

    def test_exact_message_ack_does_not_consume_unrelated_pending_item(self):
        relay = Relay()
        unrelated = MessageEnvelope("event", "other", "test", {"priority": 100}, uuid4())
        relay.enqueue(unrelated)
        receipt = ChannelGateway(relay).accept("verse-agent", "runtime.started", {})
        self.assertEqual(receipt.status, DeliveryStatus.ACKED.value)
        self.assertEqual(relay.get(str(unrelated.message_id)).status, DeliveryStatus.PENDING)

    def test_duplicate_is_idempotent_and_durable_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "jhoc.sqlite3")
            message_id, correlation_id = uuid4(), uuid4()
            first = SQLiteRelay(path)
            receipt = ChannelGateway(first).accept(
                "aibox", "probe", {"value": 2},
                message_id=message_id, correlation_id=correlation_id,
            )
            first.close()
            second = SQLiteRelay(path)
            try:
                gateway = ChannelGateway(second)
                restored = gateway.receipt(str(message_id))
                duplicate = gateway.accept(
                    "aibox", "probe", {"value": 2},
                    message_id=message_id, correlation_id=correlation_id,
                )
                self.assertEqual(restored.status, DeliveryStatus.ACKED.value)
                self.assertEqual(restored.envelope_sha256, receipt.envelope_sha256)
                self.assertTrue(duplicate.duplicate)
            finally:
                second.close()

    def test_sqlite_specific_leases_do_not_cross_ack_under_concurrency(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "concurrent.sqlite3")
            first, second = SQLiteRelay(path), SQLiteRelay(path)
            try:
                one = MessageEnvelope("event", "one", "test", {"priority": 100}, uuid4())
                two = MessageEnvelope("event", "two", "test", {"priority": 100}, uuid4())
                first.enqueue(one)
                first.enqueue(two)
                barrier = threading.Barrier(2)
                results = {}

                def acknowledge(relay, envelope, consumer):
                    barrier.wait()
                    leased = relay.lease_message(str(envelope.message_id), consumer)
                    results[consumer] = relay.ack(
                        str(envelope.message_id),
                        consumer=consumer,
                        lease_id=leased.lease_id,
                    )

                threads = (
                    threading.Thread(target=acknowledge, args=(first, one, "consumer-one")),
                    threading.Thread(target=acknowledge, args=(second, two, "consumer-two")),
                )
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=5)
                self.assertEqual(results["consumer-one"].envelope.correlation_id, one.correlation_id)
                self.assertEqual(results["consumer-two"].envelope.correlation_id, two.correlation_id)
                self.assertEqual(first.get(str(one.message_id)).status, DeliveryStatus.ACKED)
                self.assertEqual(second.get(str(two.message_id)).status, DeliveryStatus.ACKED)
            finally:
                first.close()
                second.close()

    def test_duplicate_message_rejects_correlation_change(self):
        gateway = ChannelGateway(Relay())
        message_id = uuid4()
        gateway.accept("aibox", "probe", {}, message_id=message_id, correlation_id=uuid4())
        with self.assertRaises(ContractError):
            gateway.accept("aibox", "probe", {}, message_id=message_id, correlation_id=uuid4())

    def test_cli_send_and_receipt_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = str(Path(directory) / "cli.sqlite3")
            command = [
                sys.executable, str(ROOT / "scripts" / "jhoc_channel.py"), "--db", db_path,
                "send", "--source-id", "verse-agent", "--event", "probe",
                "--payload-json", '{"value":3}',
            ]
            sent = subprocess.run(command, check=True, capture_output=True, text=True)
            sent_data = json.loads(sent.stdout)
            queried = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "jhoc_channel.py"), "--db", db_path,
                 "receipt", "--message-id", sent_data["message_id"]],
                check=True, capture_output=True, text=True,
            )
            queried_data = json.loads(queried.stdout)
            self.assertTrue(sent_data["ok"])
            self.assertTrue(sent_data["durable"])
            self.assertEqual(queried_data["status"], DeliveryStatus.ACKED.value)
            self.assertEqual(queried_data["correlation_id"], sent_data["correlation_id"])


if __name__ == "__main__":
    unittest.main()
