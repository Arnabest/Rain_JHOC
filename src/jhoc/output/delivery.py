from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from threading import RLock
from typing import Callable, Any
from uuid import uuid4

from jhoc.contracts.errors import ContractError, ErrorCode
from jhoc.proof import ProofStore
from jhoc.storage import StateStore


class DeliveryState(StrEnum):
    PENDING = "PENDING"
    SENDING = "SENDING"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    REQUIRES_RECONCILIATION = "REQUIRES_RECONCILIATION"


@dataclass(frozen=True, slots=True)
class DeliveryRecord:
    delivery_id: str
    state: DeliveryState
    attempts: int = 0
    error: str | None = None
    runtime_id: str | None = None


class OutputRuntime:
    """Sends only a Gate-accepted package; failure never calls Runner."""

    OWNER = "output"

    def __init__(self, proof: ProofStore, state_store: StateStore | None = None) -> None:
        self.proof = proof
        self.state_store = state_store or StateStore()
        self._runtime_id = str(uuid4())
        self._lock = RLock()

    def publish(self, evidence_digest: str, sender: Callable[[str], Any]) -> DeliveryRecord:
        if (
            not evidence_digest.strip()
            or self.proof.evidence(evidence_digest) is None
            or self.proof.acceptance(evidence_digest) is None
        ):
            raise ContractError("only accepted evidence may be published", ErrorCode.POLICY_DENIED)
        with self._lock:
            current, version = self._load(evidence_digest)
            if current is not None:
                if current.state == DeliveryState.DELIVERED:
                    return current
                if current.state == DeliveryState.SENDING:
                    if current.runtime_id == self._runtime_id:
                        raise ContractError("delivery is already in progress", ErrorCode.IDEMPOTENCY_CONFLICT)
                    reconciled = DeliveryRecord(
                        current.delivery_id,
                        DeliveryState.REQUIRES_RECONCILIATION,
                        current.attempts,
                        "previous runtime stopped during delivery",
                    )
                    self._save(evidence_digest, reconciled, expected_version=version)
                    raise ContractError("delivery outcome requires reconciliation", ErrorCode.UNKNOWN_SIDE_EFFECT)
                raise ContractError("existing delivery must be retried or reconciled", ErrorCode.IDEMPOTENCY_CONFLICT)
            record = DeliveryRecord(
                str(uuid4()), DeliveryState.SENDING, 1, runtime_id=self._runtime_id
            )
            claimed = self._save(evidence_digest, record, expected_version=0)
        try:
            sender(evidence_digest)
        except Exception as error:
            failed = DeliveryRecord(
                record.delivery_id,
                DeliveryState.FAILED,
                record.attempts,
                str(error),
                self._runtime_id,
            )
            self._save(evidence_digest, failed, expected_version=claimed)
            return failed
        except BaseException as error:
            self._persist_reconciliation(
                evidence_digest,
                record,
                claimed,
                f"delivery interrupted: {error.__class__.__name__}",
            )
            raise
        delivered = DeliveryRecord(
            record.delivery_id,
            DeliveryState.DELIVERED,
            record.attempts,
            runtime_id=self._runtime_id,
        )
        self._save(evidence_digest, delivered, expected_version=claimed)
        return delivered

    def retry(self, evidence_digest: str, sender: Callable[[str], Any]) -> DeliveryRecord:
        with self._lock:
            current, version = self._load(evidence_digest)
            if current is None or current.state != DeliveryState.FAILED:
                raise ContractError("only failed deliveries may be retried")
            retrying = DeliveryRecord(
                current.delivery_id,
                DeliveryState.RETRYING,
                current.attempts + 1,
                runtime_id=self._runtime_id,
            )
            claimed = self._save(evidence_digest, retrying, expected_version=version)
        try:
            sender(evidence_digest)
        except Exception as error:
            failed = DeliveryRecord(
                current.delivery_id,
                DeliveryState.FAILED,
                retrying.attempts,
                str(error),
                self._runtime_id,
            )
            self._save(evidence_digest, failed, expected_version=claimed)
            return failed
        except BaseException as error:
            self._persist_reconciliation(
                evidence_digest,
                retrying,
                claimed,
                f"delivery interrupted: {error.__class__.__name__}",
            )
            raise
        delivered = DeliveryRecord(
            current.delivery_id,
            DeliveryState.DELIVERED,
            retrying.attempts,
            runtime_id=self._runtime_id,
        )
        self._save(evidence_digest, delivered, expected_version=claimed)
        return delivered

    def reconcile(
        self,
        evidence_digest: str,
        *,
        delivered: bool,
        reason: str = "operator reconciled delivery outcome",
    ) -> DeliveryRecord:
        """Resolve an interrupted send without invoking the sender again.

        ``delivered=False`` returns the record to ``FAILED`` so the caller can
        explicitly retry. ``delivered=True`` records a terminal delivery.
        """
        if (
            not evidence_digest.strip()
            or self.proof.evidence(evidence_digest) is None
            or self.proof.acceptance(evidence_digest) is None
        ):
            raise ContractError("only accepted evidence may be reconciled", ErrorCode.POLICY_DENIED)
        if not reason.strip():
            raise ContractError("reconciliation reason is required", ErrorCode.INVALID_CONTRACT)
        with self._lock:
            current, version = self._load(evidence_digest)
            if current is None or current.state != DeliveryState.REQUIRES_RECONCILIATION:
                raise ContractError("only interrupted deliveries may be reconciled", ErrorCode.INVALID_CONTRACT)
            state = DeliveryState.DELIVERED if delivered else DeliveryState.FAILED
            record = DeliveryRecord(
                current.delivery_id,
                state,
                current.attempts,
                None if delivered else reason.strip(),
                self._runtime_id,
            )
            self._save(evidence_digest, record, expected_version=version)
            return record

    def record(self, evidence_digest: str) -> DeliveryRecord | None:
        record, _ = self._load(evidence_digest)
        return record

    def _load(self, evidence_digest: str) -> tuple[DeliveryRecord | None, int]:
        stored = self.state_store.get(self.OWNER, evidence_digest)
        if stored is None:
            return None, 0
        value = stored.value
        return (
            DeliveryRecord(
                value["delivery_id"],
                DeliveryState(value["state"]),
                int(value["attempts"]),
                value.get("error"),
                value.get("runtime_id"),
            ),
            stored.version,
        )

    def _save(
        self,
        evidence_digest: str,
        record: DeliveryRecord,
        *,
        expected_version: int,
    ) -> int:
        stored = self.state_store.put(
            self.OWNER,
            evidence_digest,
            {
                "delivery_id": record.delivery_id,
                "state": record.state.value,
                "attempts": record.attempts,
                "error": record.error,
                "runtime_id": record.runtime_id,
            },
            expected_version=expected_version,
        )
        return stored.version

    def _persist_reconciliation(
        self,
        evidence_digest: str,
        record: DeliveryRecord,
        expected_version: int,
        error: str,
    ) -> None:
        """Record an unknown sender outcome while preserving the original interrupt.

        A state-store failure here means both the delivery outcome AND its
        reconciliation marker are unknown. That double fault must stay visible:
        we append a durable local fault record (so a restart can still see the
        in-doubt delivery) and re-raise the persistence error chained to the
        original interrupt, instead of silently dropping the marker.
        """
        reconciled = DeliveryRecord(
            record.delivery_id,
            DeliveryState.REQUIRES_RECONCILIATION,
            record.attempts,
            error,
            self._runtime_id,
        )
        try:
            self._save(evidence_digest, reconciled, expected_version=expected_version)
        except Exception as persistence_error:
            self._record_persistence_fault(
                evidence_digest,
                f"reconciliation persist failed: {persistence_error!r}; outcome unknown: {error}",
            )
            raise persistence_error from None

    def _record_persistence_fault(self, evidence_digest: str, detail: str) -> None:
        """Best-effort durable fault note; never masks the failure being reported."""
        fault = DeliveryRecord(
            str(uuid4()),
            DeliveryState.REQUIRES_RECONCILIATION,
            0,
            detail,
            self._runtime_id,
        )
        try:
            self.state_store.put(
                f"{self.OWNER}:fault",
                evidence_digest,
                {
                    "delivery_id": fault.delivery_id,
                    "state": fault.state.value,
                    "attempts": fault.attempts,
                    "error": fault.error,
                    "runtime_id": fault.runtime_id,
                },
                expected_version=None,
            )
        except Exception:
            # The primary fault is the state store being unavailable; this log
            # is a secondary best-effort trace, never the reported failure.
            pass
