from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping
from uuid import UUID, uuid4

from .errors import ContractError, ErrorCode

CONTRACT_VERSION = "1.0"


class WorkStatus(StrEnum):
    NEW = "NEW"
    PLAN = "PLAN"
    ACT = "ACT"
    OBSERVE = "OBSERVE"
    VERIFY = "VERIFY"
    COMPLETION_PENDING = "COMPLETION_PENDING"
    COMPLETE = "COMPLETE"
    REPAIR = "REPAIR"
    CLARIFY = "CLARIFY"
    BLOCKED = "BLOCKED"
    DEGRADED = "DEGRADED"
    CANCELLED = "CANCELLED"
    REQUIRES_RECONCILIATION = "REQUIRES_RECONCILIATION"


class ResultStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    DEGRADED = "DEGRADED"


class SideEffectState(StrEnum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"
    UNKNOWN_SIDE_EFFECT = "UNKNOWN_SIDE_EFFECT"
    REQUIRES_RECONCILIATION = "REQUIRES_RECONCILIATION"


class MessageType(StrEnum):
    COMMAND = "command"
    EVENT = "event"
    QUERY = "query"


class PluginType(StrEnum):
    CAPABILITY = "capability"
    GOVERNANCE = "governance"
    ADAPTER = "adapter"
    WORKER = "worker"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid(value: UUID | str | None, label: str) -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ContractError(f"{label} must be a UUID") from exc


@dataclass(frozen=True, slots=True)
class WorkItem:
    task_id: UUID
    kind: str
    input: Mapping[str, Any]
    idempotency_key: str
    priority: int = 50
    work_id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=_utc_now)
    deadline_at: datetime | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CONTRACT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_id", _uuid(self.task_id, "task_id"))
        object.__setattr__(self, "work_id", _uuid(self.work_id, "work_id"))
        if self.schema_version != CONTRACT_VERSION:
            raise ContractError("unsupported WorkItem schema version", ErrorCode.UNSUPPORTED_VERSION)
        if not self.kind or not self.idempotency_key:
            raise ContractError("kind and idempotency_key are required")
        if not 0 <= self.priority <= 100:
            raise ContractError("priority must be between 0 and 100")
        if not isinstance(self.input, Mapping) or not isinstance(self.metadata, Mapping):
            raise ContractError("input and metadata must be mappings")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["task_id"] = str(self.task_id)
        value["work_id"] = str(self.work_id)
        value["created_at"] = self.created_at.isoformat()
        value["deadline_at"] = self.deadline_at.isoformat() if self.deadline_at else None
        return value


@dataclass(frozen=True, slots=True)
class WorkResult:
    task_id: UUID
    work_id: UUID
    status: ResultStatus
    side_effect_state: SideEffectState = SideEffectState.NOT_APPLICABLE
    output: Mapping[str, Any] = field(default_factory=dict)
    evidence_refs: tuple[str, ...] = ()
    completed_at: datetime = field(default_factory=_utc_now)
    error_code: str | None = None
    schema_version: str = CONTRACT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_id", _uuid(self.task_id, "task_id"))
        object.__setattr__(self, "work_id", _uuid(self.work_id, "work_id"))
        object.__setattr__(self, "status", ResultStatus(self.status))
        object.__setattr__(self, "side_effect_state", SideEffectState(self.side_effect_state))
        if self.schema_version != CONTRACT_VERSION:
            raise ContractError("unsupported WorkResult schema version", ErrorCode.UNSUPPORTED_VERSION)
        if not isinstance(self.output, Mapping):
            raise ContractError("output must be a mapping")
        if self.side_effect_state == SideEffectState.UNKNOWN_SIDE_EFFECT and not self.error_code:
            raise ContractError("unknown side effects require an error_code", ErrorCode.UNKNOWN_SIDE_EFFECT)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["task_id"] = str(self.task_id)
        value["work_id"] = str(self.work_id)
        value["status"] = self.status.value
        value["side_effect_state"] = self.side_effect_state.value
        value["evidence_refs"] = list(self.evidence_refs)
        value["completed_at"] = self.completed_at.isoformat()
        return value


@dataclass(frozen=True, slots=True)
class DeliveryState:
    attempt: int = 0
    max_attempts: int = 3
    lease_id: str | None = None

    def __post_init__(self) -> None:
        if self.attempt < 0 or self.max_attempts < 1 or self.attempt > self.max_attempts:
            raise ContractError("invalid delivery attempt bounds")


@dataclass(frozen=True, slots=True)
class MessageEnvelope:
    message_type: MessageType
    channel: str
    producer: str
    payload: Mapping[str, Any]
    correlation_id: UUID
    message_id: UUID = field(default_factory=uuid4)
    occurred_at: datetime = field(default_factory=_utc_now)
    delivery: DeliveryState = field(default_factory=DeliveryState)
    schema_version: str = CONTRACT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "message_type", MessageType(self.message_type))
        object.__setattr__(self, "message_id", _uuid(self.message_id, "message_id"))
        object.__setattr__(self, "correlation_id", _uuid(self.correlation_id, "correlation_id"))
        if self.schema_version != CONTRACT_VERSION:
            raise ContractError("unsupported MessageEnvelope schema version", ErrorCode.UNSUPPORTED_VERSION)
        if not self.channel or not self.producer or not isinstance(self.payload, Mapping):
            raise ContractError("channel, producer and payload are required")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["message_type"] = self.message_type.value
        value["message_id"] = str(self.message_id)
        value["correlation_id"] = str(self.correlation_id)
        value["occurred_at"] = self.occurred_at.isoformat()
        return value


@dataclass(frozen=True, slots=True)
class PluginManifest:
    plugin_id: str
    name: str
    version: str
    protocol_version: str
    plugin_type: PluginType
    capabilities: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    permissions: Mapping[str, Any] = field(default_factory=dict)
    side_effects: tuple[str, ...] = ()
    resource_requirements: Mapping[str, Any] = field(default_factory=dict)
    license: str = "UNLICENSED"
    verification_status: str = "UNVERIFIED"
    shelf_eligible: bool = False
    runtime_selectable: bool = False
    mutable_by_agent: bool = False
    schema_version: str = CONTRACT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "plugin_type", PluginType(self.plugin_type))
        if self.schema_version != CONTRACT_VERSION:
            raise ContractError("unsupported PluginManifest schema version", ErrorCode.UNSUPPORTED_VERSION)
        if not self.plugin_id or not self.name or not self.version or not self.protocol_version:
            raise ContractError("plugin identity and versions are required")
        if self.plugin_type == PluginType.GOVERNANCE:
            if self.shelf_eligible or self.runtime_selectable or self.mutable_by_agent:
                raise ContractError("governance plugins cannot enter the capability shelf", ErrorCode.POLICY_DENIED)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["plugin_type"] = self.plugin_type.value
        value["capabilities"] = list(self.capabilities)
        value["dependencies"] = list(self.dependencies)
        value["side_effects"] = list(self.side_effects)
        return value
