from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from threading import RLock
from typing import Any, Mapping
from uuid import uuid4

from jhoc.contracts.errors import ContractError, ErrorCode
from jhoc.contracts.sensitivity import normalize_sensitivity


class MemoryType(StrEnum):
    USER = "UserMemory"
    PROJECT = "ProjectMemory"
    TASK = "TaskMemory"
    ERROR = "ErrorMemory"
    EXPERIENCE = "ExperienceMemory"


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    content: Mapping[str, Any]
    memory_type: MemoryType
    source_ref: str
    sensitivity: str
    record_id: str = ""
    project_id: str = "jhoc"

    def __post_init__(self) -> None:
        object.__setattr__(self, "memory_type", MemoryType(self.memory_type))
        object.__setattr__(self, "sensitivity", normalize_sensitivity(self.sensitivity))
        if not self.record_id:
            object.__setattr__(self, "record_id", f"memory:{uuid4()}")
        if not self.project_id:
            object.__setattr__(self, "project_id", "jhoc")
        if not isinstance(self.content, Mapping) or not self.source_ref.strip() or not self.sensitivity.strip():
            raise ContractError("memory content, source_ref, and sensitivity are required")


class MemoryStore:
    def __init__(self) -> None:
        self._records: dict[str, MemoryRecord] = {}
        self._lock = RLock()

    def write(self, record: MemoryRecord, *, approved: bool = False) -> MemoryRecord:
        if not approved:
            raise ContractError("memory write gate denied", ErrorCode.POLICY_DENIED)
        with self._lock:
            if record.record_id in self._records:
                raise ContractError("memory record already exists", ErrorCode.IDEMPOTENCY_CONFLICT)
            self._records[record.record_id] = record
            return record

    def get(self, record_id: str) -> MemoryRecord | None:
        with self._lock:
            return self._records.get(record_id)

    def records(self, project_id: str | None = None) -> tuple[MemoryRecord, ...]:
        with self._lock:
            if project_id:
                return tuple(r for r in self._records.values() if r.project_id == project_id)
            return tuple(self._records.values())
