from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import sqlite3
from uuid import uuid4

from jhoc.contracts.errors import ContractError, ErrorCode

from .quota import HardwareState, QuotaManager, ResourceLease, ResourcePlan, UsageRecord


class SQLiteQuotaManager(QuotaManager):
    """Cross-process resource admission and durable token accounting."""

    def __init__(
        self,
        path: str,
        capacity: ResourcePlan,
        hardware_state: HardwareState | None = None,
    ) -> None:
        super().__init__(capacity, hardware_state)
        self._db = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS jhoc_quota_lease (
                lease_id TEXT PRIMARY KEY,
                owner TEXT NOT NULL,
                plan TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS jhoc_quota_expiry ON jhoc_quota_lease(expires_at);
            CREATE TABLE IF NOT EXISTS jhoc_quota_usage (
                lease_id TEXT PRIMARY KEY,
                owner TEXT NOT NULL,
                tokens_used INTEGER NOT NULL,
                recorded_at TEXT NOT NULL
            );
            """
        )
        self._db.commit()
        self._closed = False

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._db.close()
                self._closed = True

    def acquire(
        self,
        owner: str,
        plan: ResourcePlan,
        *,
        now: datetime | None = None,
        hardware_state: HardwareState | None = None,
    ) -> ResourceLease:
        if not owner.strip():
            raise ContractError("resource lease owner is required")
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ContractError("quota time must be timezone-aware")
        now = now.astimezone(timezone.utc)
        self._check_hardware(plan, hardware_state if hardware_state is not None else self.hardware_state())
        with self._lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                self._reap_db(now)
                active = self._read_active()
                self._check_capacity(active, plan)
                lease = ResourceLease(str(uuid4()), owner, plan, now + timedelta(seconds=plan.max_seconds))
                self._db.execute(
                    "INSERT INTO jhoc_quota_lease(lease_id,owner,plan,expires_at) VALUES(?,?,?,?)",
                    (lease.lease_id, lease.owner, _encode_plan(plan), lease.expires_at.isoformat()),
                )
                self._db.commit()
                return lease
            except Exception:
                if self._db.in_transaction:
                    self._db.rollback()
                raise

    def release(self, lease_id: str) -> None:
        with self._lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                self._db.execute("DELETE FROM jhoc_quota_lease WHERE lease_id=?", (lease_id,))
                self._db.commit()
            except Exception:
                if self._db.in_transaction:
                    self._db.rollback()
                raise

    def record_usage(self, lease_id: str, *, tokens_used: int) -> UsageRecord:
        if tokens_used < 0:
            raise ContractError("usage cannot be negative")
        with self._lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                self._reap_db(datetime.now(timezone.utc))
                row = self._db.execute(
                    "SELECT owner,plan FROM jhoc_quota_lease WHERE lease_id=?",
                    (lease_id,),
                ).fetchone()
                if row is None:
                    raise ContractError("resource lease not found", ErrorCode.POLICY_DENIED)
                plan = _decode_plan(row[1])
                previous = self._db.execute(
                    "SELECT tokens_used FROM jhoc_quota_usage WHERE lease_id=?", (lease_id,)
                ).fetchone()
                total = (int(previous[0]) if previous else 0) + tokens_used
                if total > plan.token_budget:
                    raise ContractError("token usage exceeds lease budget", ErrorCode.POLICY_DENIED)
                recorded_at = datetime.now(timezone.utc)
                self._db.execute(
                    "INSERT INTO jhoc_quota_usage(lease_id,owner,tokens_used,recorded_at) VALUES(?,?,?,?) "
                    "ON CONFLICT(lease_id) DO UPDATE SET tokens_used=excluded.tokens_used,recorded_at=excluded.recorded_at",
                    (lease_id, row[0], total, recorded_at.isoformat()),
                )
                self._db.commit()
                return UsageRecord(lease_id, row[0], total, recorded_at)
            except Exception:
                if self._db.in_transaction:
                    self._db.rollback()
                raise

    def usage(self, lease_id: str) -> UsageRecord | None:
        with self._lock:
            row = self._db.execute(
                "SELECT owner,tokens_used,recorded_at FROM jhoc_quota_usage WHERE lease_id=?",
                (lease_id,),
            ).fetchone()
        return UsageRecord(lease_id, row[0], int(row[1]), datetime.fromisoformat(row[2])) if row else None

    def active(self) -> tuple[ResourceLease, ...]:
        with self._lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                self._reap_db(datetime.now(timezone.utc))
                active = tuple(self._read_active())
                self._db.commit()
                return active
            except Exception:
                if self._db.in_transaction:
                    self._db.rollback()
                raise

    def _read_active(self) -> list[ResourceLease]:
        return [
            ResourceLease(row[0], row[1], _decode_plan(row[2]), datetime.fromisoformat(row[3]))
            for row in self._db.execute(
                "SELECT lease_id,owner,plan,expires_at FROM jhoc_quota_lease ORDER BY lease_id"
            ).fetchall()
        ]

    def _reap_db(self, now: datetime) -> None:
        self._db.execute("DELETE FROM jhoc_quota_lease WHERE expires_at<=?", (now.isoformat(),))

    def _check_capacity(self, active: list[ResourceLease], plan: ResourcePlan) -> None:
        if any(
            (
                sum(lease.plan.cpu_units for lease in active) + plan.cpu_units > self.capacity.cpu_units,
                sum(lease.plan.gpu_units for lease in active) + plan.gpu_units > self.capacity.gpu_units,
                sum(lease.plan.memory_mb for lease in active) + plan.memory_mb > self.capacity.memory_mb,
                sum(lease.plan.token_budget for lease in active) + plan.token_budget > self.capacity.token_budget,
                sum(lease.plan.max_concurrency for lease in active) + plan.max_concurrency > self.capacity.max_concurrency,
            )
        ):
            raise ContractError("resource quota exceeded", ErrorCode.POLICY_DENIED)


def _encode_plan(plan: ResourcePlan) -> str:
    return json.dumps(
        {
            "cpu_units": plan.cpu_units,
            "gpu_units": plan.gpu_units,
            "memory_mb": plan.memory_mb,
            "token_budget": plan.token_budget,
            "max_concurrency": plan.max_concurrency,
            "max_seconds": plan.max_seconds,
            "requires_network": plan.requires_network,
            "max_temperature_c": plan.max_temperature_c,
            "max_power_watts": plan.max_power_watts,
            "min_battery_percent": plan.min_battery_percent,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def _decode_plan(payload: str) -> ResourcePlan:
    return ResourcePlan(**json.loads(payload))
