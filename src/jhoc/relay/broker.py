from __future__ import annotations

from dataclasses import dataclass, replace
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from enum import StrEnum
import json
import sqlite3
from threading import RLock
from typing import Any
from uuid import uuid4

from jhoc.contracts.errors import ContractError, ErrorCode
from jhoc.contracts.models import DeliveryState, MessageEnvelope
from jhoc.flow.retry import RetryPolicy


class DeliveryStatus(StrEnum):
    PENDING = "PENDING"
    LEASED = "LEASED"
    RETRYING = "RETRYING"
    ACKED = "ACKED"
    DEAD_LETTERED = "DEAD_LETTERED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class DeliveryRecord:
    envelope: MessageEnvelope
    status: DeliveryStatus = DeliveryStatus.PENDING
    attempts: int = 0
    consumer: str | None = None
    lease_id: str | None = None
    lease_until: datetime | None = None
    next_attempt_at: datetime | None = None
    last_error: str | None = None


class Relay:
    """Thread-safe at-least-once delivery coordinator.

    Relay owns only delivery state. Business state remains with Core/modules.
    """

    def __init__(self, *, retry_policy: RetryPolicy | None = None, lease_seconds: float = 30.0) -> None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        self.retry_policy = retry_policy or RetryPolicy()
        self.lease_seconds = lease_seconds
        self._records: dict[str, DeliveryRecord] = {}
        self._lock = RLock()

    def enqueue(self, envelope: MessageEnvelope) -> bool:
        key = str(envelope.message_id)
        snapshot = deepcopy(envelope)
        with self._lock:
            previous = self._records.get(key)
            if previous is not None:
                if previous.envelope.to_dict() != snapshot.to_dict():
                    raise ContractError("message ID reused with different envelope", ErrorCode.IDEMPOTENCY_CONFLICT)
                return False
            self._records[key] = DeliveryRecord(snapshot, next_attempt_at=snapshot.occurred_at)
            return True

    def lease(self, consumer: str, *, now: datetime | None = None) -> DeliveryRecord | None:
        if not consumer.strip():
            raise ContractError("consumer is required")
        requested_now = now
        with self._lock:
            effective_now = requested_now or datetime.now(timezone.utc)
            self._reap_expired(effective_now)
            candidates = [
                record
                for record in self._records.values()
                if record.status in {DeliveryStatus.PENDING, DeliveryStatus.RETRYING}
                and (record.next_attempt_at is None or record.next_attempt_at <= effective_now)
            ]
            if not candidates:
                return None
            candidates.sort(
                key=lambda record: (
                    -self._priority(record.envelope.payload.get("priority", 50)),
                    record.envelope.occurred_at,
                )
            )
            selected = candidates[0]
            lease_id = str(uuid4())
            updated = replace(
                selected,
                status=DeliveryStatus.LEASED,
                attempts=selected.attempts + 1,
                consumer=consumer,
                lease_id=lease_id,
                lease_until=effective_now + timedelta(seconds=self.lease_seconds),
                next_attempt_at=None,
            )
            self._records[str(selected.envelope.message_id)] = updated
            return updated

    def lease_message(
        self,
        message_id: str,
        consumer: str,
        *,
        now: datetime | None = None,
    ) -> DeliveryRecord | None:
        """Lease one exact message without consuming another pending route."""
        if not consumer.strip():
            raise ContractError("consumer is required")
        with self._lock:
            effective_now = now or datetime.now(timezone.utc)
            self._reap_expired(effective_now)
            record = self._records.get(message_id)
            if (
                record is None
                or record.status not in {DeliveryStatus.PENDING, DeliveryStatus.RETRYING}
                or (record.next_attempt_at is not None and record.next_attempt_at > effective_now)
            ):
                return None
            lease_id = str(uuid4())
            updated = replace(
                record,
                status=DeliveryStatus.LEASED,
                attempts=record.attempts + 1,
                consumer=consumer,
                lease_id=lease_id,
                lease_until=effective_now + timedelta(seconds=self.lease_seconds),
                next_attempt_at=None,
            )
            self._records[message_id] = updated
            return updated

    def ack(self, message_id: str, *, consumer: str, lease_id: str) -> DeliveryRecord:
        with self._lock:
            record = self._leased_unlocked(message_id, consumer, lease_id)
            updated = replace(record, status=DeliveryStatus.ACKED, lease_until=None)
            self._records[message_id] = updated
        return updated

    def nack(
        self,
        message_id: str,
        *,
        consumer: str,
        lease_id: str,
        retryable: bool,
        error: str,
        now: datetime | None = None,
    ) -> DeliveryRecord:
        requested_now = now
        with self._lock:
            effective_now = requested_now or datetime.now(timezone.utc)
            record = self._leased_unlocked(message_id, consumer, lease_id)
            decision = self.retry_policy.decide(record.attempts, retryable=retryable)
            if decision.value == "RETRY":
                updated = replace(
                    record,
                    status=DeliveryStatus.RETRYING,
                    consumer=None,
                    lease_id=None,
                    lease_until=None,
                    next_attempt_at=effective_now + timedelta(seconds=self.retry_policy.delay_seconds(record.attempts)),
                    last_error=error,
                )
            else:
                updated = replace(
                    record,
                    status=DeliveryStatus.DEAD_LETTERED,
                    consumer=None,
                    lease_id=None,
                    lease_until=None,
                    last_error=error,
                )
            self._records[message_id] = updated
        return updated

    def defer(self, message_id: str, *, consumer: str, lease_id: str, now: datetime | None = None) -> DeliveryRecord:
        """Release a lease without consuming a retry attempt (e.g. provider offline)."""
        effective_now = now or datetime.now(timezone.utc)
        with self._lock:
            record = self._leased_unlocked(message_id, consumer, lease_id)
            updated = replace(record, status=DeliveryStatus.RETRYING, consumer=None, lease_id=None,
                              lease_until=None, next_attempt_at=effective_now, last_error="deferred")
            self._records[message_id] = updated
            return updated

    def cancel(self, message_id: str) -> DeliveryRecord:
        with self._lock:
            record = self._records.get(message_id)
            if record is None:
                raise ContractError("message not found")
            if record.status in {DeliveryStatus.ACKED, DeliveryStatus.DEAD_LETTERED, DeliveryStatus.CANCELLED}:
                return record
            updated = replace(record, status=DeliveryStatus.CANCELLED, consumer=None, lease_id=None, lease_until=None)
            self._records[message_id] = updated
            return updated

    def replay(self, message_id: str) -> DeliveryRecord:
        with self._lock:
            record = self._records.get(message_id)
            if record is None:
                raise ContractError("message not found")
            if record.status != DeliveryStatus.DEAD_LETTERED:
                raise ContractError("only dead-lettered messages may be replayed")
            updated = replace(record, status=DeliveryStatus.PENDING, attempts=0, next_attempt_at=datetime.now(timezone.utc), last_error=None)
            self._records[message_id] = updated
            return updated

    def get(self, message_id: str) -> DeliveryRecord | None:
        with self._lock:
            return self._records.get(message_id)

    def dead_letters(self) -> tuple[DeliveryRecord, ...]:
        with self._lock:
            return tuple(record for record in self._records.values() if record.status == DeliveryStatus.DEAD_LETTERED)

    def pending_count(self) -> int:
        with self._lock:
            return sum(record.status in {DeliveryStatus.PENDING, DeliveryStatus.LEASED, DeliveryStatus.RETRYING} for record in self._records.values())

    def _leased_unlocked(self, message_id: str, consumer: str, lease_id: str) -> DeliveryRecord:
        record = self._records.get(message_id)
        if record is None:
            raise ContractError("message not found")
        if record.status != DeliveryStatus.LEASED or record.consumer != consumer or record.lease_id != lease_id:
            raise ContractError("invalid or expired delivery lease", ErrorCode.POLICY_DENIED)
        if record.lease_until is None or record.lease_until <= datetime.now(timezone.utc):
            raise ContractError("invalid or expired delivery lease", ErrorCode.POLICY_DENIED)
        return record

    @staticmethod
    def _priority(value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            return 50
        return max(0, min(100, value))

    def _reap_expired(self, now: datetime) -> None:
        for key, record in tuple(self._records.items()):
            if record.status != DeliveryStatus.LEASED or record.lease_until is None or record.lease_until > now:
                continue
            if record.attempts >= self.retry_policy.max_attempts:
                self._records[key] = replace(record, status=DeliveryStatus.DEAD_LETTERED, consumer=None, lease_id=None, lease_until=None, last_error="lease expired")
            else:
                self._records[key] = replace(record, status=DeliveryStatus.RETRYING, consumer=None, lease_id=None, lease_until=None, next_attempt_at=now, last_error="lease expired")


class SQLiteRelay:
    """SQLite-backed Relay allowing independent processes to lease one message."""

    def __init__(self, path: str, *, retry_policy: RetryPolicy | None = None, lease_seconds: float = 30.0, max_pending: int | None = None) -> None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        if max_pending is not None and max_pending < 1:
            raise ValueError("max_pending must be positive")
        self.path = path
        self.retry_policy = retry_policy or RetryPolicy()
        self.lease_seconds = lease_seconds
        self.max_pending = max_pending
        self._db = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS jhoc_relay_delivery ("
            "message_id TEXT PRIMARY KEY, envelope TEXT NOT NULL, status TEXT NOT NULL, attempts INTEGER NOT NULL, "
            "consumer TEXT, lease_id TEXT, lease_until TEXT, next_attempt_at TEXT, last_error TEXT, priority INTEGER NOT NULL)"
        )
        self._db.commit()
        self._lock = RLock()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def enqueue(self, envelope: MessageEnvelope) -> bool:
        encoded = json.dumps(envelope.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        key = str(envelope.message_id)
        priority = Relay._priority(envelope.payload.get("priority", 50))
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._db.execute("SELECT envelope FROM jhoc_relay_delivery WHERE message_id=?", (key,)).fetchone()
                if row is not None:
                    if row[0] != encoded:
                        raise ContractError("message ID reused with different envelope", ErrorCode.IDEMPOTENCY_CONFLICT)
                    self._db.commit()
                    return False
                if self.max_pending is not None:
                    pending = self._db.execute(
                        "SELECT COUNT(*) FROM jhoc_relay_delivery WHERE status IN (?,?,?)",
                        (DeliveryStatus.PENDING.value, DeliveryStatus.RETRYING.value, DeliveryStatus.LEASED.value),
                    ).fetchone()[0]
                    if pending >= self.max_pending:
                        raise ContractError("relay backpressure limit reached", ErrorCode.POLICY_DENIED)
                self._db.execute(
                    "INSERT INTO jhoc_relay_delivery(message_id,envelope,status,attempts,next_attempt_at,priority) VALUES(?,?,?,?,?,?)",
                    (key, encoded, DeliveryStatus.PENDING.value, 0, envelope.occurred_at.isoformat(), priority),
                )
                self._db.commit()
                return True
            except Exception:
                if self._db.in_transaction:
                    self._db.rollback()
                raise

    def lease(self, consumer: str, *, now: datetime | None = None) -> DeliveryRecord | None:
        if not consumer.strip():
            raise ContractError("consumer is required")
        requested_now = now
        with self._lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                # Start the lease clock only after acquiring the write lock. If
                # SQLite contention delays BEGIN, calculating it beforehand can
                # create an already-expired lease and make the immediate ACK fail.
                effective_now = requested_now or datetime.now(timezone.utc)
                now_text = effective_now.isoformat()
                self._reap_expired_unlocked(effective_now)
                row = self._db.execute(
                    "SELECT message_id,envelope,status,attempts,consumer,lease_id,lease_until,next_attempt_at,last_error "
                    "FROM jhoc_relay_delivery WHERE status IN (?,?) AND (next_attempt_at IS NULL OR next_attempt_at<=?) "
                    "ORDER BY priority DESC, next_attempt_at, message_id LIMIT 1",
                    (DeliveryStatus.PENDING.value, DeliveryStatus.RETRYING.value, now_text),
                ).fetchone()
                if row is None:
                    self._db.commit()
                    return None
                lease_id = str(uuid4())
                lease_until = effective_now + timedelta(seconds=self.lease_seconds)
                self._db.execute(
                    "UPDATE jhoc_relay_delivery SET status=?,attempts=attempts+1,consumer=?,lease_id=?,lease_until=?,next_attempt_at=NULL WHERE message_id=?",
                    (DeliveryStatus.LEASED.value, consumer, lease_id, lease_until.isoformat(), row[0]),
                )
                self._db.commit()
                return self._record_from_row((row[0], row[1], DeliveryStatus.LEASED.value, int(row[3]) + 1, consumer, lease_id, lease_until.isoformat(), None, row[8]))
            except Exception:
                if self._db.in_transaction:
                    self._db.rollback()
                raise

    def lease_message(
        self,
        message_id: str,
        consumer: str,
        *,
        now: datetime | None = None,
    ) -> DeliveryRecord | None:
        """Lease one exact durable message without changing queue ordering."""
        if not consumer.strip():
            raise ContractError("consumer is required")
        with self._lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                effective_now = now or datetime.now(timezone.utc)
                self._reap_expired_unlocked(effective_now)
                row = self._db.execute(
                    "SELECT message_id,envelope,status,attempts,consumer,lease_id,lease_until,next_attempt_at,last_error "
                    "FROM jhoc_relay_delivery WHERE message_id=? AND status IN (?,?) "
                    "AND (next_attempt_at IS NULL OR next_attempt_at<=?)",
                    (
                        message_id,
                        DeliveryStatus.PENDING.value,
                        DeliveryStatus.RETRYING.value,
                        effective_now.isoformat(),
                    ),
                ).fetchone()
                if row is None:
                    self._db.commit()
                    return None
                lease_id = str(uuid4())
                lease_until = effective_now + timedelta(seconds=self.lease_seconds)
                self._db.execute(
                    "UPDATE jhoc_relay_delivery SET status=?,attempts=attempts+1,consumer=?,lease_id=?,lease_until=?,next_attempt_at=NULL WHERE message_id=?",
                    (
                        DeliveryStatus.LEASED.value,
                        consumer,
                        lease_id,
                        lease_until.isoformat(),
                        message_id,
                    ),
                )
                self._db.commit()
                return self._record_from_row(
                    (
                        row[0], row[1], DeliveryStatus.LEASED.value, int(row[3]) + 1,
                        consumer, lease_id, lease_until.isoformat(), None, row[8],
                    )
                )
            except Exception:
                if self._db.in_transaction:
                    self._db.rollback()
                raise

    def ack(self, message_id: str, *, consumer: str, lease_id: str) -> DeliveryRecord:
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._leased_row(message_id, consumer, lease_id)
                self._db.execute("UPDATE jhoc_relay_delivery SET status=?,lease_until=NULL WHERE message_id=?", (DeliveryStatus.ACKED.value, message_id))
                self._db.commit()
                return self._record_from_row((*row[:4], consumer, lease_id, None, None, row[8]), status=DeliveryStatus.ACKED)
            except Exception:
                if self._db.in_transaction:
                    self._db.rollback()
                raise

    def nack(self, message_id: str, *, consumer: str, lease_id: str, retryable: bool, error: str, now: datetime | None = None) -> DeliveryRecord:
        now = now or datetime.now(timezone.utc)
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._leased_row(message_id, consumer, lease_id)
                attempts = int(row[3])
                decision = self.retry_policy.decide(attempts, retryable=retryable)
                if decision.value == "RETRY":
                    status = DeliveryStatus.RETRYING
                    next_at = now + timedelta(seconds=self.retry_policy.delay_seconds(attempts))
                else:
                    status = DeliveryStatus.DEAD_LETTERED
                    next_at = None
                self._db.execute(
                    "UPDATE jhoc_relay_delivery SET status=?,consumer=NULL,lease_id=NULL,lease_until=NULL,next_attempt_at=?,last_error=? WHERE message_id=?",
                    (status.value, next_at.isoformat() if next_at else None, error, message_id),
                )
                self._db.commit()
                return self._record_from_row((*row[:4], None, None, None, next_at.isoformat() if next_at else None, error), status=status)
            except Exception:
                if self._db.in_transaction:
                    self._db.rollback()
                raise

    def defer(self, message_id: str, *, consumer: str, lease_id: str, now: datetime | None = None) -> DeliveryRecord:
        """Release a lease without consuming a retry attempt."""
        now = now or datetime.now(timezone.utc)
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._leased_row(message_id, consumer, lease_id)
                self._db.execute(
                    "UPDATE jhoc_relay_delivery SET status=?,consumer=NULL,lease_id=NULL,lease_until=NULL,next_attempt_at=?,last_error=? WHERE message_id=?",
                    (DeliveryStatus.RETRYING.value, now.isoformat(), "deferred", message_id),
                )
                self._db.commit()
                return self._record_from_row((*row[:4], None, None, None, now.isoformat(), "deferred"), status=DeliveryStatus.RETRYING)
            except Exception:
                if self._db.in_transaction:
                    self._db.rollback()
                raise

    def cancel(self, message_id: str) -> DeliveryRecord:
        with self._lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                row = self._row(message_id)
                if row is None:
                    raise ContractError("message not found")
                status = DeliveryStatus(row[2])
                if status in {DeliveryStatus.ACKED, DeliveryStatus.DEAD_LETTERED, DeliveryStatus.CANCELLED}:
                    self._db.commit()
                    return self._record_from_row(row)
                self._db.execute("UPDATE jhoc_relay_delivery SET status=?,consumer=NULL,lease_id=NULL,lease_until=NULL WHERE message_id=?", (DeliveryStatus.CANCELLED.value, message_id))
                self._db.commit()
                return self._record_from_row((*row[:4], None, None, None, row[7], row[8]), status=DeliveryStatus.CANCELLED)
            except Exception:
                if self._db.in_transaction:
                    self._db.rollback()
                raise

    def replay(self, message_id: str) -> DeliveryRecord:
        with self._lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                row = self._row(message_id)
                if row is None:
                    raise ContractError("message not found")
                if row[2] != DeliveryStatus.DEAD_LETTERED.value:
                    raise ContractError("only dead-lettered messages may be replayed")
                now = datetime.now(timezone.utc).isoformat()
                self._db.execute("UPDATE jhoc_relay_delivery SET status=?,attempts=0,next_attempt_at=?,last_error=NULL WHERE message_id=?", (DeliveryStatus.PENDING.value, now, message_id))
                self._db.commit()
                return self._record_from_row((*row[:2], DeliveryStatus.PENDING.value, 0, None, None, None, now, None))
            except Exception:
                if self._db.in_transaction:
                    self._db.rollback()
                raise

    def get(self, message_id: str) -> DeliveryRecord | None:
        with self._lock:
            row = self._row(message_id)
            return self._record_from_row(row) if row else None

    def dead_letters(self) -> tuple[DeliveryRecord, ...]:
        with self._lock:
            rows = self._db.execute("SELECT message_id,envelope,status,attempts,consumer,lease_id,lease_until,next_attempt_at,last_error FROM jhoc_relay_delivery WHERE status=?", (DeliveryStatus.DEAD_LETTERED.value,)).fetchall()
            return tuple(self._record_from_row(row) for row in rows)

    def pending_count(self) -> int:
        with self._lock:
            row = self._db.execute(
                "SELECT COUNT(*) FROM jhoc_relay_delivery WHERE status IN (?,?,?)",
                (DeliveryStatus.PENDING.value, DeliveryStatus.LEASED.value, DeliveryStatus.RETRYING.value),
            ).fetchone()
            return int(row[0])

    def _row(self, message_id: str):
        return self._db.execute("SELECT message_id,envelope,status,attempts,consumer,lease_id,lease_until,next_attempt_at,last_error FROM jhoc_relay_delivery WHERE message_id=?", (message_id,)).fetchone()

    def _leased_row(self, message_id: str, consumer: str, lease_id: str):
        row = self._row(message_id)
        if row is None or row[2] != DeliveryStatus.LEASED.value or row[4] != consumer or row[5] != lease_id:
            raise ContractError("invalid or expired delivery lease", ErrorCode.POLICY_DENIED)
        if row[6] and datetime.fromisoformat(row[6]) <= datetime.now(timezone.utc):
            raise ContractError("invalid or expired delivery lease", ErrorCode.POLICY_DENIED)
        return row

    def _reap_expired_unlocked(self, now: datetime) -> None:
        rows = self._db.execute("SELECT message_id,attempts FROM jhoc_relay_delivery WHERE status=? AND lease_until<=?", (DeliveryStatus.LEASED.value, now.isoformat())).fetchall()
        for message_id, attempts in rows:
            if attempts >= self.retry_policy.max_attempts:
                self._db.execute("UPDATE jhoc_relay_delivery SET status=?,consumer=NULL,lease_id=NULL,lease_until=NULL,last_error=? WHERE message_id=?", (DeliveryStatus.DEAD_LETTERED.value, "lease expired", message_id))
            else:
                self._db.execute("UPDATE jhoc_relay_delivery SET status=?,consumer=NULL,lease_id=NULL,lease_until=NULL,next_attempt_at=?,last_error=? WHERE message_id=?", (DeliveryStatus.RETRYING.value, now.isoformat(), "lease expired", message_id))

    @staticmethod
    def _record_from_row(row, *, status: DeliveryStatus | None = None) -> DeliveryRecord:
        envelope_data = json.loads(row[1])
        delivery = envelope_data.get("delivery", {})
        envelope = MessageEnvelope(
            envelope_data["message_type"], envelope_data["channel"], envelope_data["producer"], envelope_data["payload"],
            envelope_data["correlation_id"], envelope_data["message_id"], datetime.fromisoformat(envelope_data["occurred_at"]),
            DeliveryState(delivery.get("attempt", 0), delivery.get("max_attempts", 3), delivery.get("lease_id")),
            envelope_data.get("schema_version", "1.0"),
        )
        lease_until = datetime.fromisoformat(row[6]) if row[6] else None
        next_attempt = datetime.fromisoformat(row[7]) if row[7] else None
        return DeliveryRecord(envelope, status or DeliveryStatus(row[2]), int(row[3]), row[4], row[5], lease_until, next_attempt, row[8])
