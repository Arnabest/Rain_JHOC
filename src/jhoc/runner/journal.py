from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping

from jhoc.contracts import SideEffectState
from jhoc.contracts.errors import ContractError, ErrorCode
from jhoc.storage import StateStore


class OperationState(StrEnum):
    STARTED = "STARTED"
    EXECUTED = "EXECUTED"
    REQUIRES_RECONCILIATION = "REQUIRES_RECONCILIATION"


@dataclass(frozen=True, slots=True)
class OperationRecord:
    operation_id: str
    task_id: str
    work_id: str
    state: OperationState
    side_effect_state: SideEffectState
    output: Mapping[str, Any]
    version: int
    error_code: str | None = None


class OperationJournal:
    """CAS-protected execution journal backed by the canonical State Store."""

    OWNER = "runner.operation"

    def __init__(self, store: StateStore) -> None:
        self.store = store

    def claim(self, operation_id: str, task_id: str, work_id: str) -> tuple[OperationRecord, bool]:
        self._require(operation_id, task_id, work_id)
        stored = self.store.get(self.OWNER, operation_id)
        if stored is None:
            value = self._encode(
                OperationRecord(
                    operation_id,
                    task_id,
                    work_id,
                    OperationState.STARTED,
                    SideEffectState.NOT_APPLICABLE,
                    {},
                    0,
                )
            )
            try:
                created = self.store.put(self.OWNER, operation_id, value, expected_version=0)
                return self._decode(created.value, created.version), True
            except ContractError as error:
                if error.code != ErrorCode.STALE_STATE:
                    raise
                stored = self.store.get(self.OWNER, operation_id)
                if stored is None:
                    raise
        record = self._decode(stored.value, stored.version)
        if record.task_id != task_id or record.work_id != work_id:
            raise ContractError(
                "operation ID reused for different work", ErrorCode.IDEMPOTENCY_CONFLICT
            )
        return record, False

    def record_execution(
        self,
        record: OperationRecord,
        output: Mapping[str, Any],
        side_effect_state: SideEffectState,
    ) -> OperationRecord:
        if record.state != OperationState.STARTED:
            raise ContractError("only a started operation can record execution", ErrorCode.INVALID_TRANSITION)
        return self._update(
            record,
            OperationState.EXECUTED,
            side_effect_state=side_effect_state,
            output=dict(output),
        )

    def require_reconciliation(self, record: OperationRecord, error_code: str) -> OperationRecord:
        if record.state != OperationState.STARTED:
            return record
        return self._update(
            record,
            OperationState.REQUIRES_RECONCILIATION,
            side_effect_state=SideEffectState.UNKNOWN_SIDE_EFFECT,
            output={},
            error_code=error_code,
        )

    def get(self, operation_id: str) -> OperationRecord | None:
        stored = self.store.get(self.OWNER, operation_id)
        return self._decode(stored.value, stored.version) if stored else None

    def _update(
        self,
        record: OperationRecord,
        state: OperationState,
        *,
        side_effect_state: SideEffectState,
        output: Mapping[str, Any],
        error_code: str | None = None,
    ) -> OperationRecord:
        value = OperationRecord(
            record.operation_id,
            record.task_id,
            record.work_id,
            state,
            side_effect_state,
            dict(output),
            record.version,
            error_code,
        )
        stored = self.store.put(
            self.OWNER,
            record.operation_id,
            self._encode(value),
            expected_version=record.version,
        )
        return self._decode(stored.value, stored.version)

    @staticmethod
    def _encode(record: OperationRecord) -> dict[str, Any]:
        return {
            "operation_id": record.operation_id,
            "task_id": record.task_id,
            "work_id": record.work_id,
            "state": record.state.value,
            "side_effect_state": record.side_effect_state.value,
            "output": dict(record.output),
            "error_code": record.error_code,
        }

    @staticmethod
    def _decode(value: Mapping[str, Any], version: int) -> OperationRecord:
        return OperationRecord(
            str(value["operation_id"]),
            str(value["task_id"]),
            str(value["work_id"]),
            OperationState(str(value["state"])),
            SideEffectState(str(value["side_effect_state"])),
            dict(value.get("output", {})),
            version,
            str(value["error_code"]) if value.get("error_code") else None,
        )

    @staticmethod
    def _require(operation_id: str, task_id: str, work_id: str) -> None:
        if any(not value.strip() for value in (operation_id, task_id, work_id)):
            raise ContractError("operation, task and work IDs are required")
