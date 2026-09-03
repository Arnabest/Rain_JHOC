from __future__ import annotations

import json
import sqlite3
from threading import RLock

from jhoc.contracts.errors import ContractError, ErrorCode
from .store import MemoryRecord


class SQLiteMemoryStore:
    """Durable, approval-gated Memory records with multi-tenant project_id partition."""

    def __init__(self, path: str) -> None:
        self._db = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS jhoc_memory ("
            "record_id TEXT PRIMARY KEY, "
            "content TEXT NOT NULL, "
            "memory_type TEXT NOT NULL, "
            "source_ref TEXT NOT NULL, "
            "sensitivity TEXT NOT NULL, "
            "project_id TEXT NOT NULL DEFAULT 'jhoc')"
        )
        # Check if project_id column needs to be migrated in existing database
        cols = [r[1] for r in self._db.execute("PRAGMA table_info(jhoc_memory)").fetchall()]
        if "project_id" not in cols:
            self._db.execute("ALTER TABLE jhoc_memory ADD COLUMN project_id TEXT NOT NULL DEFAULT 'jhoc'")
        self._db.execute("CREATE INDEX IF NOT EXISTS idx_jhoc_memory_project ON jhoc_memory(project_id)")
        self._db.commit()
        self._lock = RLock()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def write(self, record: MemoryRecord, *, approved: bool = False) -> MemoryRecord:
        if not approved:
            raise ContractError("memory write gate denied", ErrorCode.POLICY_DENIED)
        with self._lock:
            try:
                self._db.execute(
                    "INSERT INTO jhoc_memory (record_id, content, memory_type, source_ref, sensitivity, project_id) VALUES(?,?,?,?,?,?)",
                    (record.record_id, json.dumps(record.content, sort_keys=True), record.memory_type.value, record.source_ref, record.sensitivity, record.project_id),
                )
                self._db.commit()
            except sqlite3.IntegrityError as exc:
                if self._db.in_transaction:
                    self._db.rollback()
                raise ContractError("memory record already exists", ErrorCode.IDEMPOTENCY_CONFLICT) from exc
            except Exception:
                if self._db.in_transaction:
                    self._db.rollback()
                raise
        return record

    def get(self, record_id: str) -> MemoryRecord | None:
        with self._lock:
            row = self._db.execute("SELECT content,memory_type,source_ref,sensitivity,project_id FROM jhoc_memory WHERE record_id=?", (record_id,)).fetchone()
        return None if row is None else MemoryRecord(json.loads(row[0]), row[1], row[2], row[3], record_id, row[4])

    def records(self, project_id: str | None = None) -> tuple[MemoryRecord, ...]:
        with self._lock:
            if project_id:
                rows = self._db.execute(
                    "SELECT record_id,content,memory_type,source_ref,sensitivity,project_id FROM jhoc_memory WHERE project_id=? ORDER BY record_id",
                    (project_id,),
                ).fetchall()
            else:
                rows = self._db.execute(
                    "SELECT record_id,content,memory_type,source_ref,sensitivity,project_id FROM jhoc_memory ORDER BY record_id"
                ).fetchall()
        return tuple(MemoryRecord(json.loads(row[1]), row[2], row[3], row[4], row[0], row[5]) for row in rows)
