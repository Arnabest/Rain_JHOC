import sys
import unittest
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from jhoc.contracts import MessageEnvelope  # noqa: E402
from jhoc.flow import RetryPolicy  # noqa: E402
from jhoc.relay import DeliveryStatus, Relay  # noqa: E402
from jhoc.contracts import ContractError, ErrorCode  # noqa: E402


def envelope(priority=50):
    return MessageEnvelope("event", "task.events", "test", {"priority": priority}, uuid4())


class RelayTests(unittest.TestCase):
    def test_enqueue_is_idempotent_and_conflicting_payload_rejects(self):
        relay = Relay()
        item = envelope()
        self.assertTrue(relay.enqueue(item))
        self.assertFalse(relay.enqueue(item))
        conflicting = MessageEnvelope("event", "task.events", "other", {"x": 1}, item.correlation_id, message_id=item.message_id)
        with self.assertRaises(ContractError) as error:
            relay.enqueue(conflicting)
        self.assertEqual(error.exception.code, ErrorCode.IDEMPOTENCY_CONFLICT)

    def test_lease_ack_requires_matching_consumer_and_lease(self):
        relay = Relay()
        item = envelope()
        relay.enqueue(item)
        leased = relay.lease("worker-a")
        self.assertEqual(leased.status, DeliveryStatus.LEASED)
        with self.assertRaises(ContractError):
            relay.ack(str(item.message_id), consumer="worker-b", lease_id=leased.lease_id)
        acked = relay.ack(str(item.message_id), consumer="worker-a", lease_id=leased.lease_id)
        self.assertEqual(acked.status, DeliveryStatus.ACKED)

    def test_retry_is_bounded_then_dead_lettered(self):
        relay = Relay(retry_policy=RetryPolicy(max_attempts=2, base_delay_seconds=0, max_delay_seconds=0))
        item = envelope()
        relay.enqueue(item)
        first = relay.lease("worker")
        retry = relay.nack(str(item.message_id), consumer="worker", lease_id=first.lease_id, retryable=True, error="temporary")
        self.assertEqual(retry.status, DeliveryStatus.RETRYING)
        second = relay.lease("worker")
        dead = relay.nack(str(item.message_id), consumer="worker", lease_id=second.lease_id, retryable=True, error="again")
        self.assertEqual(dead.status, DeliveryStatus.DEAD_LETTERED)

    def test_expired_lease_is_requeued_and_non_retryable_is_dead_letter(self):
        relay = Relay(retry_policy=RetryPolicy(max_attempts=3, base_delay_seconds=0, max_delay_seconds=0), lease_seconds=1)
        item = envelope()
        now = item.occurred_at
        relay.enqueue(item)
        leased = relay.lease("worker", now=now)
        self.assertIsNotNone(leased)
        recovered = relay.lease("worker", now=now + timedelta(seconds=2))
        self.assertEqual(recovered.attempts, 2)
        dead = relay.nack(str(item.message_id), consumer="worker", lease_id=recovered.lease_id, retryable=False, error="permanent")
        self.assertEqual(dead.status, DeliveryStatus.DEAD_LETTERED)

    def test_expired_lease_cannot_be_acked_without_reclaim(self):
        relay = Relay(lease_seconds=0.01)
        item = envelope()
        relay.enqueue(item)
        leased = relay.lease("worker", now=item.occurred_at)
        time.sleep(0.03)
        with self.assertRaisesRegex(ContractError, "expired"):
            relay.ack(
                str(item.message_id),
                consumer="worker",
                lease_id=leased.lease_id,
            )

    def test_cancel_and_explicit_replay(self):
        relay = Relay(retry_policy=RetryPolicy(max_attempts=1, base_delay_seconds=0, max_delay_seconds=0))
        item = envelope()
        relay.enqueue(item)
        leased = relay.lease("worker")
        dead = relay.nack(str(item.message_id), consumer="worker", lease_id=leased.lease_id, retryable=True, error="bad")
        self.assertEqual(dead.status, DeliveryStatus.DEAD_LETTERED)
        replayed = relay.replay(str(item.message_id))
        self.assertEqual(replayed.status, DeliveryStatus.PENDING)
        cancelled = relay.cancel(str(item.message_id))
        self.assertEqual(cancelled.status, DeliveryStatus.CANCELLED)

    def test_priority_is_selected_first(self):
        relay = Relay()
        low, high = envelope(1), envelope(99)
        relay.enqueue(low)
        relay.enqueue(high)
        self.assertEqual(relay.lease("worker").envelope.message_id, high.message_id)

    def test_long_pressure_acknowledges_out_of_order_without_duplicates(self):
        relay = Relay()
        messages = [envelope(priority=index % 100) for index in range(300)]
        for item in messages:
            self.assertTrue(relay.enqueue(item))
        leased = []
        for index in range(len(messages)):
            record = relay.lease(f"worker-{index % 4}")
            self.assertIsNotNone(record)
            leased.append(record)
        self.assertIsNone(relay.lease("worker-final"))
        random.Random(17).shuffle(leased)
        for record in leased:
            relay.ack(str(record.envelope.message_id), consumer=record.consumer, lease_id=record.lease_id)
        self.assertEqual({relay.get(str(item.message_id)).status for item in messages}, {DeliveryStatus.ACKED})


if __name__ == "__main__":
    unittest.main()
