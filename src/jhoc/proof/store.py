from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
from threading import RLock
from typing import Any, Callable, Mapping

from jhoc.contracts.errors import ContractError, ErrorCode


@dataclass(frozen=True, slots=True)
class EvidencePackage:
    task_id: str
    work_id: str
    policy_ref: str
    capability_version: str
    expected: Mapping[str, Any]
    execution: Mapping[str, Any]
    verification: Mapping[str, Any]
    side_effect_state: str
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        required = (self.task_id, self.work_id, self.policy_ref, self.capability_version, self.side_effect_state)
        if any(not value.strip() for value in required):
            raise ContractError("evidence package references are required")
        if not self.evidence_refs:
            raise ContractError("evidence package requires references")

    @property
    def digest(self) -> str:
        value = {
            "task_id": self.task_id, "work_id": self.work_id, "policy_ref": self.policy_ref,
            "capability_version": self.capability_version, "expected": self.expected,
            "execution": self.execution, "verification": self.verification,
            "side_effect_state": self.side_effect_state, "evidence_refs": self.evidence_refs,
        }
        return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class AuditRecord:
    audit_id: str
    event: Mapping[str, Any]
    recorded_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True, slots=True)
class GateAcceptanceReceipt:
    evidence_digest: str
    task_id: str
    work_id: str
    accepted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    state: "GateAcceptanceState" = field(default_factory=lambda: GateAcceptanceState.ACCEPTED)


class GateAcceptanceState(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"


class ProofStore:
    def __init__(self) -> None:
        self._evidence: dict[str, EvidencePackage] = {}
        self._acceptances: dict[str, GateAcceptanceReceipt] = {}
        self._audits: dict[str, AuditRecord] = {}
        self._lock = RLock()
        self._gate_writer_bound = False

    def record_evidence(self, package: EvidencePackage) -> str:
        digest = package.digest
        with self._lock:
            existing = self._evidence.get(digest)
            if existing is not None and existing != package:
                raise ContractError("evidence digest collision", ErrorCode.IDEMPOTENCY_CONFLICT)
            self._evidence[digest] = package
            return digest

    def record_audit(self, record: AuditRecord) -> None:
        with self._lock:
            if record.audit_id in self._audits and self._audits[record.audit_id] != record:
                raise ContractError("audit ID conflict", ErrorCode.IDEMPOTENCY_CONFLICT)
            self._audits[record.audit_id] = record

    def evidence(self, digest: str) -> EvidencePackage | None:
        with self._lock:
            return self._evidence.get(digest)

    def _bind_gate_writer(
        self,
    ) -> tuple[Callable[[EvidencePackage], str], Callable[[str], None], Callable[[str], None]]:
        with self._lock:
            if self._gate_writer_bound:
                raise ContractError("ProofStore already has a Gate writer", ErrorCode.POLICY_DENIED)
            self._gate_writer_bound = True

        def prepare(package: EvidencePackage) -> str:
            digest = package.digest
            receipt = GateAcceptanceReceipt(
                digest,
                package.task_id,
                package.work_id,
                state=GateAcceptanceState.PENDING,
            )
            with self._lock:
                existing_evidence = self._evidence.get(digest)
                if existing_evidence is not None and existing_evidence != package:
                    raise ContractError("evidence digest collision", ErrorCode.IDEMPOTENCY_CONFLICT)
                existing = self._acceptances.get(digest)
                if existing is not None:
                    if (existing.task_id, existing.work_id) != (receipt.task_id, receipt.work_id):
                        raise ContractError("Gate acceptance conflict", ErrorCode.IDEMPOTENCY_CONFLICT)
                    return digest
                evidence_was_new = existing_evidence is None
                try:
                    self._evidence[digest] = package
                    self._acceptances[digest] = receipt
                except BaseException:
                    self._acceptances.pop(digest, None)
                    if evidence_was_new:
                        self._evidence.pop(digest, None)
                    raise
            return digest

        def finalize(digest: str) -> None:
            with self._lock:
                receipt = self._acceptances.get(digest)
                if receipt is None:
                    raise ContractError("pending Gate acceptance not found", ErrorCode.INVALID_CONTRACT)
                if receipt.state == GateAcceptanceState.ACCEPTED:
                    return
                self._acceptances[digest] = replace(
                    receipt,
                    accepted_at=datetime.now(timezone.utc),
                    state=GateAcceptanceState.ACCEPTED,
                )

        def abort(digest: str) -> None:
            with self._lock:
                receipt = self._acceptances.get(digest)
                if receipt is not None and receipt.state == GateAcceptanceState.PENDING:
                    del self._acceptances[digest]

        return prepare, finalize, abort

    def acceptance(self, digest: str) -> GateAcceptanceReceipt | None:
        with self._lock:
            receipt = self._acceptances.get(digest)
            return receipt if receipt is not None and receipt.state == GateAcceptanceState.ACCEPTED else None

    def pending_acceptance(self, digest: str) -> GateAcceptanceReceipt | None:
        with self._lock:
            receipt = self._acceptances.get(digest)
            return receipt if receipt is not None and receipt.state == GateAcceptanceState.PENDING else None
