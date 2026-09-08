from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from threading import RLock
from typing import Any, Mapping

from jhoc.contracts.errors import ContractError, ErrorCode


@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    key: str
    fingerprint: str
    result: Any = None


class IdempotencyLedger:
    """Process-local claim helper; Runner uses its durable OperationJournal."""

    def __init__(self) -> None:
        self._records: dict[str, IdempotencyRecord] = {}
        self._lock = RLock()

    @staticmethod
    def fingerprint(value: Mapping[str, Any]) -> str:
        canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def claim(self, key: str, request: Mapping[str, Any]) -> IdempotencyRecord:
        if not key.strip():
            raise ContractError("idempotency key is required", ErrorCode.INVALID_CONTRACT)
        fingerprint = self.fingerprint(request)
        with self._lock:
            existing = self._records.get(key)
            if existing is not None:
                if existing.fingerprint != fingerprint:
                    raise ContractError("idempotency key reused for a different request", ErrorCode.IDEMPOTENCY_CONFLICT)
                return existing
            record = IdempotencyRecord(key, fingerprint)
            self._records[key] = record
            return record

    def complete(self, key: str, result: Any) -> IdempotencyRecord:
        with self._lock:
            existing = self._records.get(key)
            if existing is None:
                raise ContractError("cannot complete an unclaimed idempotency key", ErrorCode.INVALID_CONTRACT)
            record = IdempotencyRecord(existing.key, existing.fingerprint, result)
            self._records[key] = record
            return record

    def get(self, key: str) -> IdempotencyRecord | None:
        with self._lock:
            return self._records.get(key)
