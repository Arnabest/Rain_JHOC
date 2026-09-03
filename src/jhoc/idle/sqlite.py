from __future__ import annotations

from datetime import datetime
import json
import sqlite3
from typing import Any, Callable, Mapping, TypeVar

from .scheduler import IdleJob, IdleScheduler, IdleStatus


_T = TypeVar("_T")


class SQLiteIdleScheduler(IdleScheduler):
    """Durable Idle scheduler preserving checkpoints and preemption state."""

    def __init__(self, path: str) -> None:
        super().__init__()
        self._db = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS jhoc_idle_job (job_id TEXT PRIMARY KEY, name TEXT NOT NULL, priority INTEGER NOT NULL, status TEXT NOT NULL, max_runtime_seconds REAL NOT NULL, ttl_seconds REAL NOT NULL, token_budget INTEGER NOT NULL, created_at TEXT NOT NULL, started_at TEXT, checkpoint TEXT NOT NULL)"
        )
        self._db.commit()
        for row in self._db.execute("SELECT job_id,name,priority,status,max_runtime_seconds,ttl_seconds,token_budget,created_at,started_at,checkpoint FROM jhoc_idle_job").fetchall():
            job = IdleJob(
                row[1], int(row[2]), IdleStatus(row[3]), row[0], float(row[4]), float(row[5]), int(row[6]),
                datetime.fromisoformat(row[7]), datetime.fromisoformat(row[8]) if row[8] else None, json.loads(row[9]),
            )
            self._jobs[job.job_id] = job

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _sync(self) -> None:
        try:
            self._db.execute("BEGIN IMMEDIATE")
            for job in self._jobs.values():
                self._db.execute(
                    "INSERT INTO jhoc_idle_job VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(job_id) DO UPDATE SET name=excluded.name,priority=excluded.priority,status=excluded.status,max_runtime_seconds=excluded.max_runtime_seconds,ttl_seconds=excluded.ttl_seconds,token_budget=excluded.token_budget,created_at=excluded.created_at,started_at=excluded.started_at,checkpoint=excluded.checkpoint",
                    (job.job_id, job.name, job.priority, job.status.value, job.max_runtime_seconds, job.ttl_seconds, job.token_budget, job.created_at.isoformat(), job.started_at.isoformat() if job.started_at else None, json.dumps(job.checkpoint, sort_keys=True)),
                )
            self._db.commit()
        except Exception:
            if self._db.in_transaction:
                self._db.rollback()
            raise

    def _mutate(self, operation: Callable[..., _T], *args: Any, **kwargs: Any) -> _T:
        with self._lock:
            previous = dict(self._jobs)
            try:
                result = operation(*args, **kwargs)
                self._sync()
                return result
            except Exception:
                self._jobs = previous
                raise

    def submit(self, job: IdleJob) -> IdleJob:
        return self._mutate(super().submit, job)

    def start_next(self, *, foreground_active: bool = False, now: datetime | None = None) -> IdleJob | None:
        return self._mutate(super().start_next, foreground_active=foreground_active, now=now)

    def preempt_for_foreground(self) -> None:
        self._mutate(super().preempt_for_foreground)

    def resume(self, job_id: str) -> IdleJob:
        return self._mutate(super().resume, job_id)

    def checkpoint(self, job_id: str, state: Mapping[str, Any]) -> IdleJob:
        return self._mutate(super().checkpoint, job_id, state)

    def complete(self, job_id: str, *, tokens_used: int = 0) -> IdleJob:
        return self._mutate(super().complete, job_id, tokens_used=tokens_used)

    def cancel(self, job_id: str) -> IdleJob:
        return self._mutate(super().cancel, job_id)
