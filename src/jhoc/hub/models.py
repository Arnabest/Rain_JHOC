"""Data contracts and schemas for the unified JHOC Multi-Model Hub."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping


class ModelPresenceState(StrEnum):
    OFFLINE = "OFFLINE"
    IDLE = "IDLE"
    PLANNING = "PLANNING"
    CODING = "CODING"
    VERIFYING = "VERIFYING"
    CO_REVIEWING = "CO_REVIEWING"


class LeaseStatus(StrEnum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class MessageStatus(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class ModelPresence:
    model_id: str
    state: ModelPresenceState
    task_id: str | None
    pid: int | None
    last_heartbeat: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["state"] = self.state.value
        return d


@dataclass(frozen=True, slots=True)
class FileLease:
    lease_id: str
    file_path: str
    locked_by_model: str
    task_id: str | None
    granted_at: str
    expires_at: str
    ttl_seconds: int
    status: LeaseStatus

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    def is_valid(self, now_iso: str | None = None) -> bool:
        if self.status != LeaseStatus.ACTIVE:
            return False
        current_ts = datetime.fromisoformat(now_iso) if now_iso else datetime.now(timezone.utc)
        exp_ts = datetime.fromisoformat(self.expires_at)
        return current_ts < exp_ts


@dataclass(frozen=True, slots=True)
class HubEnvelope:
    message_id: str
    source_model: str
    target_model: str
    operation: str
    payload: Mapping[str, Any]
    correlation_id: str
    status: MessageStatus
    created_at: str
    updated_at: str
    reply_payload: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass(frozen=True, slots=True)
class TaskSlot:
    task_id: str
    owner_model: str
    title: str
    workspace: str
    baseline_sha: str
    status: str
    armed_at: str
    closed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
