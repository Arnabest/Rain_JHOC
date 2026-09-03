from __future__ import annotations

from datetime import datetime
import json
import sqlite3

from jhoc.contracts.errors import ContractError, ErrorCode
from jhoc.trust import TrustStore

from .community import Commons, CommunityMessage


class SQLiteCommons(Commons):
    """Durable community archive with Trust-bound publication."""

    def __init__(self, path: str, trust: TrustStore) -> None:
        super().__init__(trust)
        self._db = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS jhoc_commons_message ("
            "message_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
        )
        self._db.commit()
        self._closed = False
        for payload, in self._db.execute(
            "SELECT payload FROM jhoc_commons_message ORDER BY rowid"
        ).fetchall():
            value = json.loads(payload)
            message = CommunityMessage(
                value["message_type"],
                value["author"],
                value["content"],
                tuple(value["evidence_refs"]),
                value["message_id"],
                bool(value["verified"]),
                datetime.fromisoformat(value["created_at"]),
            )
            self._messages[message.message_id] = message

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._db.close()
                self._closed = True

    def publish(
        self,
        message: CommunityMessage,
        *,
        eligible_evidence: bool,
        identity_id: str,
        session_id: str | None = None,
    ) -> CommunityMessage:
        with self._lock:
            payload = json.dumps(
                {
                    "message_type": message.message_type.value,
                    "author": message.author,
                    "content": message.content,
                    "evidence_refs": list(message.evidence_refs),
                    "message_id": message.message_id,
                    "verified": message.verified,
                    "created_at": message.created_at.isoformat(),
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            )
            published = super().publish(
                message,
                eligible_evidence=eligible_evidence,
                identity_id=identity_id,
                session_id=session_id,
            )
            try:
                self._db.execute("BEGIN IMMEDIATE")
                self._db.execute(
                    "INSERT INTO jhoc_commons_message(message_id,payload) VALUES(?,?)",
                    (published.message_id, payload),
                )
                self._db.commit()
            except sqlite3.IntegrityError as error:
                if self._db.in_transaction:
                    self._db.rollback()
                self._messages.pop(published.message_id, None)
                raise ContractError("community message already exists", ErrorCode.IDEMPOTENCY_CONFLICT) from error
            except Exception:
                if self._db.in_transaction:
                    self._db.rollback()
                self._messages.pop(published.message_id, None)
                raise
            return published
