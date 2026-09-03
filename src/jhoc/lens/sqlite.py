from __future__ import annotations

from datetime import datetime
import json
import sqlite3
from typing import Any, Mapping

from .telemetry import LensCollector, LogEntry, _redact


class SQLiteLensCollector(LensCollector):
    """Durable Lens records with separate physical tables per record class."""

    def __init__(self, path: str) -> None:
        super().__init__()
        self._db = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self._closed = False
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS jhoc_lens_log (sequence INTEGER PRIMARY KEY AUTOINCREMENT, module_id TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS jhoc_lens_event (sequence INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS jhoc_lens_audit (sequence INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS jhoc_lens_evidence (sequence INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS jhoc_lens_trace (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                record_type TEXT NOT NULL,
                record_sequence INTEGER NOT NULL,
                task_id TEXT,
                work_id TEXT,
                trace_id TEXT,
                UNIQUE(record_type, record_sequence)
            );
            CREATE INDEX IF NOT EXISTS jhoc_lens_trace_task ON jhoc_lens_trace(task_id, sequence);
            CREATE INDEX IF NOT EXISTS jhoc_lens_trace_work ON jhoc_lens_trace(work_id, sequence);
            CREATE INDEX IF NOT EXISTS jhoc_lens_trace_id ON jhoc_lens_trace(trace_id, sequence);
            """
        )
        self._db.commit()
        records: dict[tuple[str, int], LogEntry | Mapping[str, Any]] = {}
        for sequence, module_id, payload in self._db.execute(
            "SELECT sequence,module_id,payload FROM jhoc_lens_log ORDER BY sequence"
        ).fetchall():
            value = json.loads(payload)
            entry = LogEntry(
                value["message"], module_id, value["severity"], value.get("task_id"), value.get("work_id"),
                value.get("message_id"), value.get("trace_id"), value.get("component_id"), value.get("plugin_id"),
                value.get("policy_ref"), value.get("capability_id"), value.get("fields", {}),
                datetime.fromisoformat(value["occurred_at"]),
            )
            self._logs.setdefault(module_id, []).append(entry)
            records[("log", int(sequence))] = entry
        for record_type, table, attribute in (
            ("event", "jhoc_lens_event", "_events"),
            ("audit", "jhoc_lens_audit", "_audits"),
            ("evidence", "jhoc_lens_evidence", "_evidence"),
        ):
            for sequence, payload in self._db.execute(
                f"SELECT sequence,payload FROM {table} ORDER BY sequence"
            ).fetchall():
                value = json.loads(payload)
                getattr(self, attribute).append(value)
                records[(record_type, int(sequence))] = value
        if records and not self._db.execute("SELECT 1 FROM jhoc_lens_trace LIMIT 1").fetchone():
            self._backfill_trace(records)
        for sequence, record_type, record_sequence in self._db.execute(
            "SELECT sequence,record_type,record_sequence FROM jhoc_lens_trace ORDER BY sequence"
        ).fetchall():
            payload = records.get((record_type, int(record_sequence)))
            if payload is not None:
                self._append_trace(record_type, payload, sequence=int(sequence))

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._db.close()
                self._closed = True

    def emit(self, entry: LogEntry) -> LogEntry:
        with self._lock:
            before = list(self._logs.get(entry.module_id, ()))
            timeline_length = len(self._timeline)
            next_sequence = self._next_sequence
            normalized = LensCollector.emit(self, entry)
            payload = json.dumps({
                "message": normalized.message, "severity": normalized.severity.value, "task_id": normalized.task_id,
                "work_id": normalized.work_id, "message_id": normalized.message_id, "trace_id": normalized.trace_id,
                "component_id": normalized.component_id, "plugin_id": normalized.plugin_id, "policy_ref": normalized.policy_ref,
                "capability_id": normalized.capability_id, "fields": normalized.fields, "occurred_at": normalized.occurred_at.isoformat(),
            }, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
            try:
                self._write_record(
                    "INSERT INTO jhoc_lens_log(module_id,payload) VALUES(?,?)",
                    (normalized.module_id, payload),
                    "log",
                    normalized,
                )
            except Exception:
                if before:
                    self._logs[entry.module_id] = before
                else:
                    self._logs.pop(entry.module_id, None)
                del self._timeline[timeline_length:]
                self._next_sequence = next_sequence
                raise
            return normalized

    def record_event(self, event: Mapping[str, Any]) -> None:
        self._record_collection("_events", "jhoc_lens_event", event, LensCollector.record_event)

    def record_audit(self, audit: Mapping[str, Any]) -> None:
        self._record_collection("_audits", "jhoc_lens_audit", audit, LensCollector.record_audit)

    def record_evidence(self, evidence: Mapping[str, Any]) -> None:
        self._record_collection("_evidence", "jhoc_lens_evidence", evidence, LensCollector.record_evidence)

    def _record_collection(self, attribute: str, table: str, value: Mapping[str, Any], operation) -> None:
        with self._lock:
            collection = getattr(self, attribute)
            before = len(collection)
            timeline_length = len(self._timeline)
            next_sequence = self._next_sequence
            normalized = _redact(value)
            operation(self, value)
            try:
                self._write_record(
                    f"INSERT INTO {table}(payload) VALUES(?)",
                    (json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=True),),
                    table.removeprefix("jhoc_lens_"),
                    normalized,
                )
            except Exception:
                del collection[before:]
                del self._timeline[timeline_length:]
                self._next_sequence = next_sequence
                raise

    def _write_record(
        self,
        sql: str,
        params: tuple[Any, ...],
        record_type: str,
        payload: LogEntry | Mapping[str, Any],
    ) -> None:
        try:
            if self._closed:
                raise RuntimeError("lens collector is closed")
            self._db.execute("BEGIN IMMEDIATE")
            cursor = self._db.execute(sql, params)
            self._db.execute(
                "INSERT INTO jhoc_lens_trace(record_type,record_sequence,task_id,work_id,trace_id) VALUES(?,?,?,?,?)",
                (
                    record_type,
                    int(cursor.lastrowid),
                    self._correlation(payload, "task_id"),
                    self._correlation(payload, "work_id"),
                    self._correlation(payload, "trace_id"),
                ),
            )
            self._db.commit()
        except Exception:
            if self._db.in_transaction:
                self._db.rollback()
            raise

    def _backfill_trace(self, records: Mapping[tuple[str, int], LogEntry | Mapping[str, Any]]) -> None:
        try:
            self._db.execute("BEGIN IMMEDIATE")
            for (record_type, record_sequence), payload in records.items():
                self._db.execute(
                    "INSERT OR IGNORE INTO jhoc_lens_trace(record_type,record_sequence,task_id,work_id,trace_id) VALUES(?,?,?,?,?)",
                    (
                        record_type,
                        record_sequence,
                        self._correlation(payload, "task_id"),
                        self._correlation(payload, "work_id"),
                        self._correlation(payload, "trace_id"),
                    ),
                )
            self._db.commit()
        except Exception:
            if self._db.in_transaction:
                self._db.rollback()
            raise
