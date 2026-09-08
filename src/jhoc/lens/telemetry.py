from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from threading import RLock
from typing import Any, Mapping


class Severity(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True, slots=True)
class LogEntry:
    message: str
    module_id: str
    severity: Severity = Severity.INFO
    task_id: str | None = None
    work_id: str | None = None
    message_id: str | None = None
    trace_id: str | None = None
    component_id: str | None = None
    plugin_id: str | None = None
    policy_ref: str | None = None
    capability_id: str | None = None
    fields: Mapping[str, Any] = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not self.module_id.strip() or not self.message.strip():
            raise ValueError("module_id and message are required")
        object.__setattr__(self, "severity", Severity(self.severity))


@dataclass(frozen=True, slots=True)
class TraceRecord:
    sequence: int
    record_type: str
    payload: LogEntry | Mapping[str, Any]


_SENSITIVE = {"token", "access_token", "api_key", "apikey", "cookie", "password", "secret", "credential"}


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: "[REDACTED]" if isinstance(key, str) and key.lower() in _SENSITIVE else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value


class LensCollector:
    """Collects observations while keeping physical routes separate."""

    def __init__(self) -> None:
        self._logs: dict[str, list[LogEntry]] = {}
        self._events: list[Mapping[str, Any]] = []
        self._audits: list[Mapping[str, Any]] = []
        self._evidence: list[Mapping[str, Any]] = []
        self._timeline: list[TraceRecord] = []
        self._next_sequence = 1
        self._lock = RLock()

    def emit(self, entry: LogEntry) -> LogEntry:
        normalized = LogEntry(
            message=entry.message,
            module_id=entry.module_id,
            severity=Severity(entry.severity),
            task_id=entry.task_id,
            work_id=entry.work_id,
            message_id=entry.message_id,
            trace_id=entry.trace_id,
            component_id=entry.component_id,
            plugin_id=entry.plugin_id,
            policy_ref=entry.policy_ref,
            capability_id=entry.capability_id,
            fields=_redact(entry.fields),
            occurred_at=entry.occurred_at,
        )
        with self._lock:
            self._logs.setdefault(normalized.module_id, []).append(normalized)
            self._append_trace("log", normalized)
        return normalized

    def record_event(self, event: Mapping[str, Any]) -> None:
        with self._lock:
            normalized = _redact(event)
            self._events.append(normalized)
            self._append_trace("event", normalized)

    def record_audit(self, audit: Mapping[str, Any]) -> None:
        with self._lock:
            normalized = _redact(audit)
            self._audits.append(normalized)
            self._append_trace("audit", normalized)

    def record_evidence(self, evidence: Mapping[str, Any]) -> None:
        with self._lock:
            normalized = _redact(evidence)
            self._evidence.append(normalized)
            self._append_trace("evidence", normalized)

    def module_logs(self, module_id: str) -> tuple[LogEntry, ...]:
        with self._lock:
            return tuple(self._logs.get(module_id, ()))

    @property
    def events(self) -> tuple[Mapping[str, Any], ...]:
        with self._lock:
            return tuple(self._events)

    @property
    def audits(self) -> tuple[Mapping[str, Any], ...]:
        with self._lock:
            return tuple(self._audits)

    @property
    def evidence(self) -> tuple[Mapping[str, Any], ...]:
        with self._lock:
            return tuple(self._evidence)

    def reconstruct(
        self,
        *,
        task_id: str | None = None,
        work_id: str | None = None,
        trace_id: str | None = None,
    ) -> tuple[TraceRecord, ...]:
        """Return the causal observation stream matching every supplied correlation ID."""

        filters = {"task_id": task_id, "work_id": work_id, "trace_id": trace_id}
        if not any(value is not None and str(value).strip() for value in filters.values()):
            raise ValueError("at least one correlation ID is required")
        with self._lock:
            return tuple(
                item
                for item in self._timeline
                if all(value is None or self._correlation(item.payload, name) == value for name, value in filters.items())
            )

    def _append_trace(
        self,
        record_type: str,
        payload: LogEntry | Mapping[str, Any],
        *,
        sequence: int | None = None,
    ) -> None:
        position = self._next_sequence if sequence is None else sequence
        self._timeline.append(TraceRecord(position, record_type, payload))
        self._next_sequence = max(self._next_sequence, position + 1)

    @staticmethod
    def _correlation(payload: LogEntry | Mapping[str, Any], name: str) -> Any:
        return getattr(payload, name) if isinstance(payload, LogEntry) else payload.get(name)
