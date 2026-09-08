from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Mapping

from jhoc.contracts.errors import ContractError, ErrorCode
from jhoc.contracts.sensitivity import normalize_sensitivity
from jhoc.storage import StateStore


@dataclass(frozen=True, slots=True)
class ContextSource:
    source_id: str
    data: Mapping[str, Any]
    sensitivity: str
    expires_at: datetime
    allowed_consumers: frozenset[str]
    provenance: tuple[str, ...]
    confidence: float = 1.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "sensitivity", normalize_sensitivity(self.sensitivity))
        try:
            object.__setattr__(self, "allowed_consumers", frozenset(self.allowed_consumers))
            object.__setattr__(self, "provenance", tuple(self.provenance))
        except TypeError as error:
            raise ContractError("invalid context source") from error
        if (
            not self.source_id.strip()
            or not isinstance(self.data, Mapping)
            or not 0 <= self.confidence <= 1
            or not isinstance(self.expires_at, datetime)
            or self.expires_at.tzinfo is None
            or self.expires_at.utcoffset() is None
            or not self.allowed_consumers
            or any(not item.strip() for item in self.allowed_consumers)
            or not self.provenance
            or any(not item.strip() for item in self.provenance)
        ):
            raise ContractError("invalid context source")


@dataclass(frozen=True, slots=True)
class PassAContext:
    user_input: str
    metadata: Mapping[str, Any]
    policy_ref: str


@dataclass(frozen=True, slots=True)
class ContextPackage:
    pass_a: PassAContext
    sources: tuple[ContextSource, ...]
    resource_plan_ref: str
    consumer_id: str
    snapshot_id: str


class ContextOrchestrator:
    """Assembles only explicitly authorized sources and produces a rebuildable snapshot."""

    OWNER = "context.snapshot"
    MAX_REDACTION_DEPTH = 64
    MAX_REDACTION_NODES = 10_000

    def __init__(self, state_store: StateStore | None = None) -> None:
        self.state_store = state_store or StateStore()

    def pass_a(self, user_input: str, metadata: Mapping[str, Any], *, policy_ref: str) -> PassAContext:
        if not user_input.strip() or not policy_ref.strip() or not isinstance(metadata, Mapping):
            raise ContractError("Pass A requires user input and policy reference")
        return PassAContext(user_input, dict(metadata), policy_ref)

    def pass_b(
        self,
        pass_a: PassAContext,
        sources: tuple[ContextSource, ...],
        *,
        authorized_source_ids: frozenset[str],
        consumer_id: str,
        resource_plan_ref: str,
        budget: int = 16,
        redact_keys: frozenset[str] = frozenset(),
        now: datetime | None = None,
    ) -> ContextPackage:
        if budget < 1 or not resource_plan_ref.strip() or not consumer_id.strip():
            raise ContractError("invalid context budget/resource plan")
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ContractError("context evaluation time must be timezone-aware")
        normalized_redact_keys = frozenset(str(key).strip().lower() for key in redact_keys)
        selected = tuple(
            ContextSource(
                source.source_id,
                self._redact(source.data, normalized_redact_keys),
                source.sensitivity,
                source.expires_at,
                source.allowed_consumers,
                source.provenance,
                source.confidence,
            )
            for source in sources
            if source.source_id in authorized_source_ids
            and source.expires_at > now
            and (consumer_id in source.allowed_consumers or "*" in source.allowed_consumers)
        )[:budget]
        canonical = {
            "user_input": pass_a.user_input,
            "metadata": pass_a.metadata,
            "policy_ref": pass_a.policy_ref,
            "sources": [
                {
                    "source_id": source.source_id,
                    "data": source.data,
                    "sensitivity": source.sensitivity,
                    "confidence": source.confidence,
                    "expires_at": source.expires_at.isoformat(),
                    "allowed_consumers": sorted(source.allowed_consumers),
                    "provenance": list(source.provenance),
                }
                for source in selected
            ],
            "consumer_id": consumer_id,
            "resource_plan_ref": resource_plan_ref,
        }
        try:
            encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        except (RecursionError, TypeError, ValueError) as error:
            raise ContractError("context snapshot must be JSON serializable") from error
        snapshot_id = "context:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        existing = self.state_store.get(self.OWNER, snapshot_id)
        if existing is None:
            try:
                self.state_store.put(self.OWNER, snapshot_id, canonical, expected_version=0)
            except ContractError as error:
                if error.code != ErrorCode.STALE_STATE:
                    raise
                existing = self.state_store.get(self.OWNER, snapshot_id)
        if existing is not None and existing.value != canonical:
            raise ContractError("context snapshot digest collision", ErrorCode.IDEMPOTENCY_CONFLICT)
        return ContextPackage(pass_a, selected, resource_plan_ref, consumer_id, snapshot_id)

    def rebuild(self, snapshot_id: str) -> ContextPackage:
        if not snapshot_id.strip():
            raise ContractError("context snapshot ID is required")
        stored = self.state_store.get(self.OWNER, snapshot_id)
        if stored is None:
            raise ContractError("context snapshot not found")
        value = stored.value
        pass_a = PassAContext(value["user_input"], value["metadata"], value["policy_ref"])
        sources = tuple(
            ContextSource(
                item["source_id"],
                item["data"],
                item["sensitivity"],
                datetime.fromisoformat(item["expires_at"]),
                frozenset(item["allowed_consumers"]),
                tuple(item["provenance"]),
                float(item["confidence"]),
            )
            for item in value["sources"]
        )
        return ContextPackage(
            pass_a,
            sources,
            value["resource_plan_ref"],
            value["consumer_id"],
            snapshot_id,
        )

    @classmethod
    def _redact(cls, value: Any, keys: frozenset[str]) -> Any:
        return cls._redact_value(value, keys, depth=0, nodes=[0], active=set())

    @classmethod
    def _redact_value(
        cls,
        value: Any,
        keys: frozenset[str],
        *,
        depth: int,
        nodes: list[int],
        active: set[int],
    ) -> Any:
        nodes[0] += 1
        if depth > cls.MAX_REDACTION_DEPTH or nodes[0] > cls.MAX_REDACTION_NODES:
            raise ContractError("context data exceeds redaction limits", ErrorCode.POLICY_DENIED)
        if isinstance(value, Mapping):
            identity = id(value)
            if identity in active:
                raise ContractError("cyclic context data is not allowed", ErrorCode.POLICY_DENIED)
            active.add(identity)
            try:
                return {
                    key: "[REDACTED]"
                    if str(key).strip().lower() in keys
                    else cls._redact_value(item, keys, depth=depth + 1, nodes=nodes, active=active)
                    for key, item in value.items()
                }
            finally:
                active.remove(identity)
        if isinstance(value, (list, tuple)):
            identity = id(value)
            if identity in active:
                raise ContractError("cyclic context data is not allowed", ErrorCode.POLICY_DENIED)
            active.add(identity)
            try:
                return [
                    cls._redact_value(item, keys, depth=depth + 1, nodes=nodes, active=active)
                    for item in value
                ]
            finally:
                active.remove(identity)
        return value
