from __future__ import annotations

import json
import sqlite3
from threading import RLock

from jhoc.contracts.errors import ContractError, ErrorCode
from .store import KnowledgeRecord, KnowledgeStatus, _ALLOWED


class SQLiteAtlasStore:
    """Durable Atlas content and version history owned by the Atlas domain."""

    def __init__(self, path: str) -> None:
        self._db = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS jhoc_knowledge (record_id TEXT PRIMARY KEY, content TEXT NOT NULL, knowledge_type TEXT NOT NULL, source_ref TEXT NOT NULL, sensitivity TEXT NOT NULL, status TEXT NOT NULL, version INTEGER NOT NULL)"
        )
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS jhoc_knowledge_history (record_id TEXT NOT NULL, version INTEGER NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(record_id,version))"
        )
        self._db.commit()
        self._lock = RLock()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    @staticmethod
    def _payload(record: KnowledgeRecord) -> str:
        return json.dumps({
            "content": record.content, "knowledge_type": record.knowledge_type.value,
            "source_ref": record.source_ref, "sensitivity": record.sensitivity,
            "status": record.status.value, "record_id": record.record_id, "version": record.version,
        }, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _record(payload: str) -> KnowledgeRecord:
        value = json.loads(payload)
        return KnowledgeRecord(value["content"], value["knowledge_type"], value["source_ref"], value["sensitivity"], value["status"], value["record_id"], int(value["version"]))

    def ingest(self, record: KnowledgeRecord) -> KnowledgeRecord:
        payload = self._payload(record)
        with self._lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                self._db.execute(
                    "INSERT INTO jhoc_knowledge VALUES(?,?,?,?,?,?,?)",
                    (record.record_id, json.dumps(record.content, sort_keys=True), record.knowledge_type.value, record.source_ref, record.sensitivity, record.status.value, record.version),
                )
                self._db.execute("INSERT INTO jhoc_knowledge_history VALUES(?,?,?)", (record.record_id, record.version, payload))
                self._db.commit()
            except sqlite3.IntegrityError as exc:
                if self._db.in_transaction:
                    self._db.rollback()
                raise ContractError("knowledge record already exists", ErrorCode.IDEMPOTENCY_CONFLICT) from exc
            except Exception:
                if self._db.in_transaction:
                    self._db.rollback()
                raise
        return record

    def transition(self, record_id: str, status: KnowledgeStatus, *, expected_version: int | None = None) -> KnowledgeRecord:
        status = KnowledgeStatus(status)
        with self._lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                row = self._db.execute("SELECT content,knowledge_type,source_ref,sensitivity,status,version FROM jhoc_knowledge WHERE record_id=?", (record_id,)).fetchone()
                if row is None:
                    raise ContractError("knowledge record not found")
                current = KnowledgeRecord(json.loads(row[0]), row[1], row[2], row[3], row[4], record_id, int(row[5]))
                if expected_version is not None and current.version != expected_version:
                    raise ContractError("knowledge version mismatch", ErrorCode.STALE_STATE)
                if status not in _ALLOWED[current.status]:
                    raise ContractError(f"invalid knowledge transition {current.status} -> {status}", ErrorCode.INVALID_TRANSITION)
                updated = KnowledgeRecord(current.content, current.knowledge_type, current.source_ref, current.sensitivity, status, current.record_id, current.version + 1)
                self._db.execute("UPDATE jhoc_knowledge SET status=?,version=? WHERE record_id=?", (status.value, updated.version, record_id))
                self._db.execute("INSERT INTO jhoc_knowledge_history VALUES(?,?,?)", (record_id, updated.version, self._payload(updated)))
                self._db.commit()
                return updated
            except Exception:
                if self._db.in_transaction:
                    self._db.rollback()
                raise

    def get(self, record_id: str) -> KnowledgeRecord | None:
        with self._lock:
            row = self._db.execute("SELECT content,knowledge_type,source_ref,sensitivity,status,version FROM jhoc_knowledge WHERE record_id=?", (record_id,)).fetchone()
        return None if row is None else KnowledgeRecord(json.loads(row[0]), row[1], row[2], row[3], row[4], record_id, int(row[5]))

    def history(self, record_id: str) -> tuple[KnowledgeRecord, ...]:
        with self._lock:
            rows = self._db.execute("SELECT payload FROM jhoc_knowledge_history WHERE record_id=? ORDER BY version", (record_id,)).fetchall()
        return tuple(self._record(row[0]) for row in rows)

    def records(self) -> tuple[KnowledgeRecord, ...]:
        with self._lock:
            ids = [row[0] for row in self._db.execute("SELECT record_id FROM jhoc_knowledge ORDER BY record_id").fetchall()]
        return tuple(record for record_id in ids if (record := self.get(record_id)) is not None)
