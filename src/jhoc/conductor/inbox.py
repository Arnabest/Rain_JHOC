"""Durable Human Approval Inbox for Guard and Conductor REQUIRE_APPROVAL gates."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
import json
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Any, Mapping
from uuid import uuid4


class ApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CONSUMED = "CONSUMED"


@dataclass(frozen=True, slots=True)
class ApprovalTicket:
    ticket_id: str
    operation: str
    requester: str
    reason: str
    payload: Mapping[str, Any]
    status: ApprovalStatus
    created_at: datetime
    resolved_at: datetime | None = None
    approver: str | None = None
    resolution_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        data["created_at"] = self.created_at.isoformat()
        data["resolved_at"] = self.resolved_at.isoformat() if self.resolved_at else None
        return data


class SQLiteApprovalInbox:
    """Persistent SQLite-backed Approval Inbox."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self.path), check_same_thread=False, timeout=30)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._lock = RLock()
        with self._lock:
            self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS jhoc_approval_inbox (
                    ticket_id TEXT PRIMARY KEY,
                    operation TEXT NOT NULL,
                    requester TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT,
                    approver TEXT,
                    resolution_reason TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_jhoc_approval_status ON jhoc_approval_inbox(status, created_at);
                """
            )
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def create_ticket(
        self,
        operation: str,
        requester: str,
        reason: str,
        *,
        payload: Mapping[str, Any] | None = None,
        ticket_id: str | None = None,
    ) -> ApprovalTicket:
        ticket = ApprovalTicket(
            ticket_id=ticket_id or f"ticket-{uuid4()}",
            operation=operation.strip(),
            requester=requester.strip(),
            reason=reason.strip(),
            payload=dict(payload or {}),
            status=ApprovalStatus.PENDING,
            created_at=datetime.now(timezone.utc),
        )
        with self._lock:
            self._db.execute(
                """
                INSERT INTO jhoc_approval_inbox
                (ticket_id, operation, requester, reason, payload, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ticket.ticket_id,
                    ticket.operation,
                    ticket.requester,
                    ticket.reason,
                    json.dumps(dict(ticket.payload), ensure_ascii=True),
                    ticket.status.value,
                    ticket.created_at.isoformat(),
                ),
            )
            self._db.commit()
        return ticket

    def get_ticket(self, ticket_id: str) -> ApprovalTicket | None:
        with self._lock:
            row = self._db.execute(
                """
                SELECT ticket_id, operation, requester, reason, payload, status, created_at, resolved_at, approver, resolution_reason
                FROM jhoc_approval_inbox WHERE ticket_id = ?
                """,
                (ticket_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_ticket(row)

    def list_tickets(self, *, status: ApprovalStatus | str | None = None) -> tuple[ApprovalTicket, ...]:
        query = "SELECT ticket_id, operation, requester, reason, payload, status, created_at, resolved_at, approver, resolution_reason FROM jhoc_approval_inbox"
        params: list[Any] = []
        if status is not None:
            status_val = status.value if isinstance(status, ApprovalStatus) else str(status)
            query += " WHERE status = ? ORDER BY created_at DESC"
            params.append(status_val)
        else:
            query += " ORDER BY created_at DESC"
        with self._lock:
            rows = self._db.execute(query, params).fetchall()
        return tuple(self._row_to_ticket(row) for row in rows)

    def find_active_approval(self, operation: str, target: str, *, max_age_seconds: int = 300) -> ApprovalTicket | None:
        """Finds if an unexpired APPROVED ticket exists for the given operation and target."""
        now = datetime.now(timezone.utc)
        with self._lock:
            rows = self._db.execute(
                "SELECT ticket_id, operation, requester, reason, payload, status, created_at, resolved_at, approver, resolution_reason "
                "FROM jhoc_approval_inbox WHERE operation = ? AND status = 'APPROVED' ORDER BY resolved_at DESC",
                (operation,),
            ).fetchall()
            for r in rows:
                ticket = self._row_to_ticket(r)
                if ticket.payload.get("target") == target or ticket.payload.get("command") == target:
                    if ticket.resolved_at is not None:
                        age = (now - ticket.resolved_at).total_seconds()
                        if age > max_age_seconds:
                            continue
                    return ticket
        return None

    def consume_approval(self, ticket_id: str, *, consumer: str = "jhoc_hook_gate", note: str = "Consumed by gate") -> bool:
        """Atomically marks an APPROVED ticket as CONSUMED, turning it into a one-shot token."""
        now = datetime.now(timezone.utc)
        with self._lock:
            cur = self._db.execute(
                """
                UPDATE jhoc_approval_inbox
                SET status = ?, resolved_at = ?, resolution_reason = ?
                WHERE ticket_id = ? AND status = 'APPROVED'
                """,
                (ApprovalStatus.CONSUMED.value, now.isoformat(), f"{note} (by {consumer})", ticket_id),
            )
            self._db.commit()
            return cur.rowcount > 0

    def find_pending_ticket(self, operation: str, target: str) -> ApprovalTicket | None:
        """Finds if a PENDING ticket already exists for the given operation and target."""
        with self._lock:
            rows = self._db.execute(
                "SELECT ticket_id, operation, requester, reason, payload, status, created_at, resolved_at, approver, resolution_reason "
                "FROM jhoc_approval_inbox WHERE operation = ? AND status = 'PENDING' ORDER BY created_at DESC",
                (operation,),
            ).fetchall()
            for r in rows:
                ticket = self._row_to_ticket(r)
                if ticket.payload.get("target") == target or ticket.payload.get("command") == target:
                    return ticket
        return None

    def _verify_operator(self, operator_token: str | None = None) -> None:
        import os
        from pathlib import Path
        secret_file = Path(__file__).resolve().parents[3] / "runtime" / ".operator_secret"
        token = operator_token or os.environ.get("JHOC_OPERATOR_TOKEN", "")
        if secret_file.is_file():
            expected = secret_file.read_text(encoding="utf-8").strip()
            if not token or token != expected:
                raise PermissionError("Permission Denied: Invalid or missing operator token.")
        elif os.environ.get("JHOC_MODEL_ID") and not token:
            raise PermissionError("Permission Denied: Autonomous model execution detected. Self-approval is strictly forbidden.")

    def approve(
        self,
        ticket_id: str,
        *,
        approver: str = "operator",
        note: str = "",
        operator_token: str | None = None,
    ) -> ApprovalTicket:
        self._verify_operator(operator_token)
        now = datetime.now(timezone.utc)
        with self._lock:
            current = self.get_ticket(ticket_id)
            if current is None:
                raise KeyError(f"Ticket not found: {ticket_id}")
            if current.status != ApprovalStatus.PENDING:
                raise ValueError(f"Ticket {ticket_id} is already resolved as {current.status.value}")
            self._db.execute(
                """
                UPDATE jhoc_approval_inbox
                SET status = ?, resolved_at = ?, approver = ?, resolution_reason = ?
                WHERE ticket_id = ?
                """,
                (ApprovalStatus.APPROVED.value, now.isoformat(), approver, note, ticket_id),
            )
            self._db.commit()
            return ApprovalTicket(
                current.ticket_id,
                current.operation,
                current.requester,
                current.reason,
                current.payload,
                ApprovalStatus.APPROVED,
                current.created_at,
                now,
                approver,
                note,
            )

    def reject(
        self,
        ticket_id: str,
        *,
        approver: str = "operator",
        reason: str = "",
        operator_token: str | None = None,
    ) -> ApprovalTicket:
        self._verify_operator(operator_token)
        now = datetime.now(timezone.utc)
        with self._lock:
            current = self.get_ticket(ticket_id)
            if current is None:
                raise KeyError(f"Ticket not found: {ticket_id}")
            if current.status != ApprovalStatus.PENDING:
                raise ValueError(f"Ticket {ticket_id} is already resolved as {current.status.value}")
            self._db.execute(
                """
                UPDATE jhoc_approval_inbox
                SET status = ?, resolved_at = ?, approver = ?, resolution_reason = ?
                WHERE ticket_id = ?
                """,
                (ApprovalStatus.REJECTED.value, now.isoformat(), approver, reason, ticket_id),
            )
            self._db.commit()
            return ApprovalTicket(
                current.ticket_id,
                current.operation,
                current.requester,
                current.reason,
                current.payload,
                ApprovalStatus.REJECTED,
                current.created_at,
                now,
                approver,
                reason,
            )

    def is_approved(self, ticket_id: str) -> bool:
        ticket = self.get_ticket(ticket_id)
        return ticket is not None and ticket.status == ApprovalStatus.APPROVED

    @staticmethod
    def _row_to_ticket(row: tuple[Any, ...]) -> ApprovalTicket:
        return ApprovalTicket(
            ticket_id=str(row[0]),
            operation=str(row[1]),
            requester=str(row[2]),
            reason=str(row[3]),
            payload=json.loads(row[4]) if row[4] else {},
            status=ApprovalStatus(str(row[5])),
            created_at=datetime.fromisoformat(row[6]),
            resolved_at=datetime.fromisoformat(row[7]) if row[7] else None,
            approver=str(row[8]) if row[8] else None,
            resolution_reason=str(row[9]) if row[9] else None,
        )


__all__ = ["ApprovalStatus", "ApprovalTicket", "SQLiteApprovalInbox"]
