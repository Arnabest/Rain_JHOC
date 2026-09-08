from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from threading import RLock
from typing import Any, Mapping

from jhoc.contracts.errors import ContractError, ErrorCode


@dataclass(frozen=True, slots=True)
class VersionedValue:
    owner: str
    key: str
    version: int
    value: Any
    updated_at: datetime


class StateStore:
    """Versioned state store with owner-scoped compare-and-swap writes."""

    def __init__(self) -> None:
        self._records: dict[tuple[str, str], VersionedValue] = {}
        self._lock = RLock()

    def get(self, owner: str, key: str) -> VersionedValue | None:
        self._validate(owner, key)
        with self._lock:
            record = self._records.get((owner, key))
            return deepcopy(record) if record else None

    def put(self, owner: str, key: str, value: Any, *, expected_version: int | None = None) -> VersionedValue:
        self._validate(owner, key)
        with self._lock:
            current = self._records.get((owner, key))
            current_version = current.version if current else 0
            if expected_version is not None and expected_version != current_version:
                raise ContractError("state version mismatch", ErrorCode.STALE_STATE)
            record = VersionedValue(owner, key, current_version + 1, deepcopy(value), datetime.now(timezone.utc))
            self._records[(owner, key)] = record
            return deepcopy(record)

    def delete(self, owner: str, key: str, *, expected_version: int | None = None) -> None:
        self._validate(owner, key)
        with self._lock:
            current = self._records.get((owner, key))
            if current is None:
                return
            if expected_version is not None and expected_version != current.version:
                raise ContractError("state version mismatch", ErrorCode.STALE_STATE)
            del self._records[(owner, key)]

    @staticmethod
    def _validate(owner: str, key: str) -> None:
        if not owner.strip() or not key.strip():
            raise ContractError("state owner and key are required")


class EventStore:
    """Append-only event store; event IDs are immutable and idempotent."""

    def __init__(self) -> None:
        self._events: dict[str, Mapping[str, Any]] = {}
        self._lock = RLock()

    def append(self, event_id: str, event: Mapping[str, Any]) -> bool:
        if not event_id.strip() or not isinstance(event, Mapping):
            raise ContractError("event_id and event are required")
        snapshot = deepcopy(dict(event))
        with self._lock:
            previous = self._events.get(event_id)
            if previous is not None:
                if previous != snapshot:
                    raise ContractError("event ID reused with different payload", ErrorCode.IDEMPOTENCY_CONFLICT)
                return False
            self._events[event_id] = snapshot
            return True

    def read(self, event_id: str) -> Mapping[str, Any] | None:
        with self._lock:
            event = self._events.get(event_id)
            return deepcopy(event) if event else None


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    artifact_id: str
    owner: str
    content_type: str
    size: int
    sha256: str


class ArtifactStore:
    """Content-addressed bytes store with explicit owner references."""

    def __init__(self) -> None:
        self._blobs: dict[str, bytes] = {}
        self._refs: dict[str, ArtifactRef] = {}
        self._lock = RLock()

    def put(self, owner: str, data: bytes, *, content_type: str = "application/octet-stream") -> ArtifactRef:
        if not owner.strip() or not isinstance(data, bytes):
            raise ContractError("artifact owner and bytes are required")
        digest = hashlib.sha256(data).hexdigest()
        artifact_id = f"sha256:{digest}"
        reference = ArtifactRef(artifact_id, owner, content_type, len(data), digest)
        with self._lock:
            self._blobs.setdefault(artifact_id, bytes(data))
            self._refs.setdefault(artifact_id, reference)
            return reference

    def get(self, reference: ArtifactRef, *, owner: str) -> bytes:
        if owner != reference.owner:
            raise ContractError("artifact owner mismatch", ErrorCode.POLICY_DENIED)
        with self._lock:
            blob = self._blobs.get(reference.artifact_id)
            if blob is None:
                raise ContractError("artifact not found")
            return bytes(blob)

