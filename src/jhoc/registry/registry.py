from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from threading import RLock
from typing import Mapping

from jhoc.contracts.errors import ContractError, ErrorCode
from jhoc.contracts.models import PluginManifest, PluginType


class VerificationStatus(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    REVOKED = "REVOKED"


@dataclass(frozen=True, slots=True)
class CapabilityRecord:
    capability_id: str
    version: str
    manifest: PluginManifest
    input_schema_ref: str
    output_schema_ref: str
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    health: str = "UNKNOWN"

    def __post_init__(self) -> None:
        object.__setattr__(self, "verification_status", VerificationStatus(self.verification_status))
        if not self.capability_id.strip() or not self.version.strip() or not self.input_schema_ref.strip() or not self.output_schema_ref.strip():
            raise ContractError("capability identity and schemas are required")
        if self.manifest.plugin_type == PluginType.GOVERNANCE:
            raise ContractError("governance plugins cannot be registered as shelf capabilities", ErrorCode.POLICY_DENIED)


class CapabilityRegistry:
    def __init__(self) -> None:
        self._records: dict[tuple[str, str], CapabilityRecord] = {}
        self._lock = RLock()

    def register(self, record: CapabilityRecord) -> None:
        with self._lock:
            key = (record.capability_id, record.version)
            if key in self._records:
                raise ContractError("capability version already registered", ErrorCode.IDEMPOTENCY_CONFLICT)
            self._records[key] = record

    def verify(self, capability_id: str, version: str, *, health: str = "HEALTHY") -> CapabilityRecord:
        with self._lock:
            key = (capability_id, version)
            current = self._records.get(key)
            if current is None:
                raise ContractError("capability not found")
            updated = replace(current, verification_status=VerificationStatus.VERIFIED, health=health)
            self._records[key] = updated
            return updated

    def revoke(self, capability_id: str, version: str) -> CapabilityRecord:
        with self._lock:
            current = self._records.get((capability_id, version))
            if current is None:
                raise ContractError("capability not found")
            updated = replace(current, verification_status=VerificationStatus.REVOKED, health="REVOKED")
            self._records[(capability_id, version)] = updated
            return updated

    def get(self, capability_id: str, version: str) -> CapabilityRecord | None:
        with self._lock:
            return self._records.get((capability_id, version))

