from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from threading import RLock
from typing import Any, Mapping
from uuid import uuid4

from jhoc.contracts.errors import ContractError, ErrorCode
from jhoc.contracts.sensitivity import normalize_sensitivity


class KnowledgeStatus(StrEnum):
    RECEIVED = "RECEIVED"
    QUARANTINED = "QUARANTINED"
    PARSED = "PARSED"
    NORMALIZED = "NORMALIZED"
    CANDIDATE = "CANDIDATE"
    VERIFIED = "VERIFIED"
    PUBLISHED = "PUBLISHED"
    EXPIRED = "EXPIRED"
    RETRACTED = "RETRACTED"
    ARCHIVED = "ARCHIVED"
    REJECTED = "REJECTED"


class KnowledgeType(StrEnum):
    FACT = "FACT"
    RULE_REFERENCE = "RULE_REFERENCE"
    PROJECT_KNOWLEDGE = "PROJECT_KNOWLEDGE"
    USER_PREFERENCE = "USER_PREFERENCE"
    TASK_EXPERIENCE = "TASK_EXPERIENCE"
    ERROR_PATTERN = "ERROR_PATTERN"
    OBSERVATION = "OBSERVATION"
    HYPOTHESIS = "HYPOTHESIS"
    PROCEDURE = "PROCEDURE"
    EVIDENCE = "EVIDENCE"
    COMMUNITY_CONCLUSION = "COMMUNITY_CONCLUSION"
    MODEL_CAPABILITY = "MODEL_CAPABILITY"


@dataclass(frozen=True, slots=True)
class KnowledgeRecord:
    content: Mapping[str, Any]
    knowledge_type: KnowledgeType
    source_ref: str
    sensitivity: str
    status: KnowledgeStatus = KnowledgeStatus.RECEIVED
    record_id: str = ""
    version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "knowledge_type", KnowledgeType(self.knowledge_type))
        object.__setattr__(self, "status", KnowledgeStatus(self.status))
        object.__setattr__(self, "sensitivity", normalize_sensitivity(self.sensitivity))
        if not self.record_id:
            object.__setattr__(self, "record_id", f"knowledge:{uuid4()}")
        if not self.source_ref.strip() or not isinstance(self.content, Mapping):
            raise ContractError("knowledge content, source_ref, and sensitivity are required")


_ALLOWED = {
    KnowledgeStatus.RECEIVED: {KnowledgeStatus.QUARANTINED, KnowledgeStatus.PARSED, KnowledgeStatus.REJECTED, KnowledgeStatus.ARCHIVED},
    KnowledgeStatus.QUARANTINED: {KnowledgeStatus.PARSED, KnowledgeStatus.ARCHIVED},
    KnowledgeStatus.PARSED: {KnowledgeStatus.NORMALIZED, KnowledgeStatus.QUARANTINED},
    KnowledgeStatus.NORMALIZED: {KnowledgeStatus.CANDIDATE, KnowledgeStatus.QUARANTINED},
    KnowledgeStatus.CANDIDATE: {KnowledgeStatus.VERIFIED, KnowledgeStatus.RETRACTED, KnowledgeStatus.ARCHIVED},
    KnowledgeStatus.VERIFIED: {KnowledgeStatus.PUBLISHED, KnowledgeStatus.RETRACTED},
    KnowledgeStatus.PUBLISHED: {KnowledgeStatus.EXPIRED, KnowledgeStatus.RETRACTED, KnowledgeStatus.ARCHIVED},
    KnowledgeStatus.EXPIRED: {KnowledgeStatus.ARCHIVED},
    KnowledgeStatus.RETRACTED: {KnowledgeStatus.ARCHIVED},
    KnowledgeStatus.ARCHIVED: set(),
    KnowledgeStatus.REJECTED: {KnowledgeStatus.ARCHIVED},
}


class AtlasStore:
    def __init__(self) -> None:
        self._records: dict[str, KnowledgeRecord] = {}
        self._history: dict[str, list[KnowledgeRecord]] = {}
        self._lock = RLock()

    def ingest(self, record: KnowledgeRecord) -> KnowledgeRecord:
        with self._lock:
            if record.record_id in self._records:
                raise ContractError("knowledge record already exists", ErrorCode.IDEMPOTENCY_CONFLICT)
            self._records[record.record_id] = record
            self._history[record.record_id] = [record]
            return record

    def transition(self, record_id: str, status: KnowledgeStatus, *, expected_version: int | None = None) -> KnowledgeRecord:
        with self._lock:
            record = self._records.get(record_id)
            if record is None:
                raise ContractError("knowledge record not found")
            if expected_version is not None and record.version != expected_version:
                raise ContractError("knowledge version mismatch", ErrorCode.STALE_STATE)
            status = KnowledgeStatus(status)
            if status not in _ALLOWED[record.status]:
                raise ContractError(f"invalid knowledge transition {record.status} -> {status}", ErrorCode.INVALID_TRANSITION)
            updated = replace(record, status=status, version=record.version + 1)
            self._records[record_id] = updated
            self._history.setdefault(record_id, []).append(updated)
            return updated

    def get(self, record_id: str) -> KnowledgeRecord | None:
        with self._lock:
            return self._records.get(record_id)

    def history(self, record_id: str) -> tuple[KnowledgeRecord, ...]:
        with self._lock:
            return tuple(self._history.get(record_id, ()))

    def records(self) -> tuple[KnowledgeRecord, ...]:
        with self._lock:
            return tuple(self._records.values())
