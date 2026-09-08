from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from threading import RLock
from typing import Any, Callable, Mapping
from uuid import uuid4


class IdleStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"
    COMPLETE = "COMPLETE"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True, slots=True)
class IdleJob:
    name: str
    priority: int = 0
    status: IdleStatus = IdleStatus.QUEUED
    job_id: str = ""
    max_runtime_seconds: float = 300.0
    ttl_seconds: float = 3600.0
    token_budget: int = 10_000
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    checkpoint: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.job_id:
            object.__setattr__(self, "job_id", f"idle:{uuid4()}")
        if not self.name.strip() or self.max_runtime_seconds <= 0 or self.ttl_seconds <= 0 or self.token_budget < 1:
            raise ValueError("idle job limits must be positive")


class IdleScheduler:
    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._jobs: dict[str, IdleJob] = {}
        self._lock = RLock()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def submit(self, job: IdleJob) -> IdleJob:
        with self._lock:
            self._jobs[job.job_id] = job
            return job

    def start_next(self, *, foreground_active: bool = False, now: datetime | None = None) -> IdleJob | None:
        with self._lock:
            now = now or self._clock()
            self._expire_unlocked(now)
            if foreground_active:
                return None
            queued = sorted((job for job in self._jobs.values() if job.status == IdleStatus.QUEUED), key=lambda item: -item.priority)
            if not queued:
                return None
            job = replace(queued[0], status=IdleStatus.RUNNING, started_at=now)
            self._jobs[job.job_id] = job
            return job

    def preempt_for_foreground(self) -> None:
        with self._lock:
            for key, job in tuple(self._jobs.items()):
                if job.status == IdleStatus.RUNNING:
                    self._jobs[key] = replace(job, status=IdleStatus.PAUSED)

    def resume(self, job_id: str) -> IdleJob:
        with self._lock:
            job = self._jobs[job_id]
            if job.status != IdleStatus.PAUSED:
                return job
            job = replace(job, status=IdleStatus.QUEUED)
            self._jobs[job_id] = job
            return job

    def checkpoint(self, job_id: str, state: Mapping[str, Any]) -> IdleJob:
        with self._lock:
            job = self._jobs[job_id]
            if job.status not in {IdleStatus.RUNNING, IdleStatus.PAUSED}:
                return job
            updated = replace(job, checkpoint=dict(state))
            self._jobs[job_id] = updated
            return updated

    def complete(self, job_id: str, *, tokens_used: int = 0) -> IdleJob:
        with self._lock:
            job = self._jobs[job_id]
            if tokens_used < 0 or tokens_used > job.token_budget:
                raise ValueError("idle token budget exceeded")
            updated = replace(job, status=IdleStatus.COMPLETE)
            self._jobs[job_id] = updated
            return updated

    def cancel(self, job_id: str) -> IdleJob:
        with self._lock:
            job = self._jobs[job_id]
            updated = replace(job, status=IdleStatus.CANCELLED)
            self._jobs[job_id] = updated
            return updated

    def get(self, job_id: str) -> IdleJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def jobs(self) -> tuple[IdleJob, ...]:
        with self._lock:
            return tuple(self._jobs.values())

    def _expire_unlocked(self, now: datetime) -> None:
        for key, job in tuple(self._jobs.items()):
            if job.status in {IdleStatus.COMPLETE, IdleStatus.CANCELLED, IdleStatus.EXPIRED}:
                continue
            if now > job.created_at + timedelta(seconds=job.ttl_seconds):
                self._jobs[key] = replace(job, status=IdleStatus.EXPIRED)
            elif job.status == IdleStatus.RUNNING and job.started_at is not None and now > job.started_at + timedelta(seconds=job.max_runtime_seconds):
                self._jobs[key] = replace(job, status=IdleStatus.EXPIRED)
