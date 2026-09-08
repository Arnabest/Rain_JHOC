from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Any
from uuid import UUID

from jhoc.contracts import ContractError, ResultStatus, SideEffectState, WorkResult, WorkStatus
from jhoc.flow import FlowActor, FlowStateMachine
from jhoc.storage import StateStore

from .journal import OperationJournal, OperationState


@dataclass(frozen=True, slots=True)
class ExecutionRecord:
    result: WorkResult
    state: WorkStatus
    trace: tuple[WorkStatus, ...]


class Runner:
    """Executes one action and stops at COMPLETION_PENDING; Gate owns completion."""

    def __init__(self, journal: OperationJournal | None = None) -> None:
        self.journal = journal or OperationJournal(StateStore())

    def execute(
        self,
        task_id: UUID,
        work_id: UUID,
        flow: FlowStateMachine,
        action: Callable[[], Mapping[str, Any]],
        *,
        operation_id: str | None = None,
        side_effecting: bool = False,
    ) -> ExecutionRecord:
        trace = [flow.state]
        operation = None
        action_started = False
        try:
            if side_effecting and (not isinstance(operation_id, str) or not operation_id.strip()):
                raise ContractError("side-effecting actions require a stable operation ID")
            self._advance(flow, trace, WorkStatus.PLAN, WorkStatus.ACT)
            if operation_id is not None:
                operation, claimed = self.journal.claim(operation_id, str(task_id), str(work_id))
            else:
                claimed = True
            if operation is not None and not claimed:
                if operation.state == OperationState.EXECUTED:
                    output = operation.output
                    side_effect_state = operation.side_effect_state
                else:
                    if operation.state == OperationState.STARTED:
                        operation = self.journal.require_reconciliation(operation, "IN_DOUBT_OPERATION")
                    flow.transition(WorkStatus.BLOCKED, actor=FlowActor.RUNNER, reason="operation requires reconciliation")
                    trace.append(WorkStatus.BLOCKED)
                    return ExecutionRecord(
                        WorkResult(
                            task_id,
                            work_id,
                            ResultStatus.FAILED,
                            SideEffectState.UNKNOWN_SIDE_EFFECT,
                            error_code=operation.error_code or "IN_DOUBT_OPERATION",
                        ),
                        flow.state,
                        tuple(trace),
                    )
            else:
                action_started = True
                output = action()
                side_effect_state = SideEffectState.SUCCEEDED if side_effecting else SideEffectState.NOT_APPLICABLE
                if operation is not None:
                    operation = self.journal.record_execution(operation, output, side_effect_state)
            self._advance(flow, trace, WorkStatus.OBSERVE, WorkStatus.VERIFY)
            flow.transition(WorkStatus.COMPLETION_PENDING, actor=FlowActor.RUNNER, reason="execution verified")
            trace.append(WorkStatus.COMPLETION_PENDING)
            result = WorkResult(
                task_id,
                work_id,
                ResultStatus.SUCCEEDED,
                side_effect_state=side_effect_state,
                output=output,
            )
            return ExecutionRecord(result, flow.state, tuple(trace))
        except Exception as error:
            side_effect_state = (
                SideEffectState.UNKNOWN_SIDE_EFFECT
                if side_effecting and action_started
                else SideEffectState.NOT_APPLICABLE
            )
            reconciliation_error: Exception | None = None
            if operation is not None and operation.state == OperationState.STARTED and side_effecting and action_started:
                try:
                    operation = self.journal.require_reconciliation(operation, type(error).__name__)
                except Exception as journal_error:
                    reconciliation_error = journal_error
            if flow.state not in {WorkStatus.BLOCKED, WorkStatus.CANCELLED, WorkStatus.COMPLETE}:
                try:
                    flow.transition(WorkStatus.BLOCKED, actor=FlowActor.RUNNER, reason=f"execution failed: {error}")
                    trace.append(WorkStatus.BLOCKED)
                except Exception:
                    pass
            if reconciliation_error is not None:
                raise reconciliation_error from error
            result = WorkResult(
                task_id,
                work_id,
                ResultStatus.FAILED,
                side_effect_state=side_effect_state,
                error_code=error.code.value if isinstance(error, ContractError) else type(error).__name__,
            )
            return ExecutionRecord(result, flow.state, tuple(trace))
        except BaseException as interrupt:
            # Interrupts (KeyboardInterrupt, SystemExit, ...) must not vanish:
            # the durable operation stays explicitly in-doubt and the flow lands
            # in a terminal blocked state before the original interrupt is re-raised.
            # This mirrors OutputRuntime's BaseException reconciliation path.
            if operation is not None and operation.state == OperationState.STARTED and side_effecting and action_started:
                try:
                    self.journal.require_reconciliation(operation, type(interrupt).__name__)
                except Exception:
                    pass
            if flow.state not in {WorkStatus.BLOCKED, WorkStatus.CANCELLED, WorkStatus.COMPLETE}:
                try:
                    flow.transition(
                        WorkStatus.BLOCKED,
                        actor=FlowActor.RUNNER,
                        reason=f"execution interrupted: {type(interrupt).__name__}",
                    )
                    trace.append(WorkStatus.BLOCKED)
                except Exception:
                    pass
            raise

    @staticmethod
    def _advance(flow: FlowStateMachine, trace: list[WorkStatus], *targets: WorkStatus) -> None:
        for target in targets:
            flow.transition(target, actor=FlowActor.RUNNER, reason=f"runner {target.value.lower()}")
            trace.append(target)
