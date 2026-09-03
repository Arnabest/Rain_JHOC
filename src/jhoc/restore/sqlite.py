from __future__ import annotations

import json
import sqlite3
from threading import RLock

from .recovery import RecoveryAudit, RecoveryManager, RecoveryStage


class SQLiteRecoveryManager(RecoveryManager):
    """Recovery manager with durable operation audit records."""

    def __init__(self, path: str) -> None:
        super().__init__()
        self._db = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("CREATE TABLE IF NOT EXISTS jhoc_recovery_audit (sequence INTEGER PRIMARY KEY AUTOINCREMENT, operation_id TEXT NOT NULL, operation TEXT NOT NULL, status TEXT NOT NULL, snapshot_id TEXT, mode TEXT, stages TEXT NOT NULL, error TEXT)")
        self._db.commit()
        self._lock = RLock()
        for row in self._db.execute("SELECT operation_id,operation,status,snapshot_id,mode,stages,error FROM jhoc_recovery_audit ORDER BY sequence").fetchall():
            self._audits.append(RecoveryAudit(row[0], row[1], row[2], row[3], row[4], tuple(RecoveryStage(item) for item in json.loads(row[5])), row[6]))

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _record_audit(self, audit: RecoveryAudit) -> None:
        with self._lock:
            try:
                self._db.execute(
                    "INSERT INTO jhoc_recovery_audit(operation_id,operation,status,snapshot_id,mode,stages,error) VALUES(?,?,?,?,?,?,?)",
                    (audit.operation_id, audit.operation, audit.status, audit.snapshot_id, audit.mode, json.dumps([stage.value for stage in audit.stages]), audit.error),
                )
                self._db.commit()
            except Exception:
                if self._db.in_transaction:
                    self._db.rollback()
                raise
            self._audits.append(audit)
