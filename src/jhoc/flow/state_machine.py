from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from threading import Event, RLock
from typing import Callable, Iterable, TypeVar

from jhoc.contracts.errors import ContractError, ErrorCode
from jhoc.contracts.models import WorkStatus


T = TypeVar("T")


class FlowStateError(ContractError):
    """Raised when a flow transition violates state or concurrency rules."""


class FlowActor(StrEnum):
    RUNNER = "runner"
    GATE = "gate"
    GUARD = "guard"
    OPERATOR = "operator"
    SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class StateTransition:
    sequence: int
    from_state: WorkStatus
    to_state: WorkStatus
    actor: FlowActor
    reason: str
    occurred_at: datetime


class CancellationToken:
    """A one-way cancellation signal shared by flow participants."""

    def __init__(self) -> None:
        self._event = Event()

    def cancel(self) -> bool:
        was_cancelled = self._event.is_set()
        self._event.set()
        return not was_cancelled

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise FlowStateError("flow cancellation requested", ErrorCode.CANCELLED)


_TRANSITIONS: dict[WorkStatus, frozenset[WorkStatus]] = {
    WorkStatus.NEW: frozenset({WorkStatus.PLAN, WorkStatus.CLARIFY, WorkStatus.BLOCKED, WorkStatus.CANCELLED}),
    WorkStatus.PLAN: frozenset({WorkStatus.ACT, WorkStatus.CLARIFY, WorkStatus.BLOCKED, WorkStatus.CANCELLED}),
    WorkStatus.ACT: frozenset({WorkStatus.OBSERVE, WorkStatus.REPAIR, WorkStatus.BLOCKED, WorkStatus.DEGRADED, WorkStatus.CANCELLED}),
    WorkStatus.OBSERVE: frozenset({WorkStatus.VERIFY, WorkStatus.REPAIR, WorkStatus.BLOCKED, WorkStatus.DEGRADED, WorkStatus.CANCELLED}),
    WorkStatus.VERIFY: frozenset({WorkStatus.COMPLETION_PENDING, WorkStatus.REPAIR, WorkStatus.BLOCKED, WorkStatus.DEGRADED, WorkStatus.CANCELLED}),
    WorkStatus.COMPLETION_PENDING: frozenset({WorkStatus.COMPLETE, WorkStatus.REPAIR, WorkStatus.BLOCKED, WorkStatus.REQUIRES_RECONCILIATION, WorkStatus.CANCELLED}),
    WorkStatus.REPAIR: frozenset({WorkStatus.ACT, WorkStatus.BLOCKED, WorkStatus.CANCELLED}),
    WorkStatus.CLARIFY: frozenset({WorkStatus.PLAN, WorkStatus.BLOCKED, WorkStatus.CANCELLED}),
    WorkStatus.DEGRADED: frozenset({WorkStatus.ACT, WorkStatus.OBSERVE, WorkStatus.VERIFY, WorkStatus.BLOCKED, WorkStatus.CANCELLED}),
    WorkStatus.COMPLETE: frozenset(),
    WorkStatus.BLOCKED: frozenset(),
    WorkStatus.CANCELLED: frozenset(),
    WorkStatus.REQUIRES_RECONCILIATION: frozenset(),
}


class FlowStateMachine:
    """Thread-safe, explicit state machine for one work item.

    Completion is owned by Gate: only a gate actor can commit COMPLETE from
    COMPLETION_PENDING. `expected_version` prevents stale-snapshot writes.
    """

    def __init__(self, initial: WorkStatus = WorkStatus.NEW) -> None:
        self._state = WorkStatus(initial)
        self._version = 0
        self._history: list[StateTransition] = []
        self._lock = RLock()

    @property
    def state(self) -> WorkStatus:
        with self._lock:
            return self._state

    @property
    def version(self) -> int:
        with self._lock:
            return self._version

    def history(self) -> tuple[StateTransition, ...]:
        with self._lock:
            return tuple(self._history)

    def transition(
        self,
        target: WorkStatus,
        *,
        actor: FlowActor | str,
        reason: str,
        expected_version: int | None = None,
    ) -> StateTransition:
        target = WorkStatus(target)
        actor = FlowActor(actor)
        if not reason.strip():
            raise FlowStateError("transition reason is required", ErrorCode.INVALID_TRANSITION)
        with self._lock:
            if expected_version is not None and expected_version != self._version:
                raise FlowStateError("stale flow version", ErrorCode.STALE_STATE)
            if target not in _TRANSITIONS[self._state]:
                raise FlowStateError(
                    f"invalid transition {self._state} -> {target}", ErrorCode.INVALID_TRANSITION
                )
            if target == WorkStatus.COMPLETE and actor != FlowActor.GATE:
                raise FlowStateError("only Gate may commit COMPLETE", ErrorCode.INVALID_TRANSITION)
            self._version += 1
            transition = StateTransition(
                self._version,
                self._state,
                target,
                actor,
                reason.strip(),
                datetime.now(timezone.utc),
            )
            self._state = target
            self._history.append(transition)
            return transition

    def transition_many(
        self,
        targets: Iterable[WorkStatus],
        *,
        actor: FlowActor | str,
        reason: str,
    ) -> tuple[StateTransition, ...]:
        transitions = []
        for target in targets:
            transitions.append(self.transition(target, actor=actor, reason=reason))
        return tuple(transitions)

    def transition_with(
        self,
        target: WorkStatus,
        *,
        effect: Callable[[], T],
        actor: FlowActor | str,
        reason: str,
        expected_version: int | None = None,
    ) -> tuple[StateTransition, T]:
        """Commit an external effect while the validated transition is locked."""
        target = WorkStatus(target)
        actor = FlowActor(actor)
        if not reason.strip():
            raise FlowStateError("transition reason is required", ErrorCode.INVALID_TRANSITION)
        with self._lock:
            if expected_version is not None and expected_version != self._version:
                raise FlowStateError("stale flow version", ErrorCode.STALE_STATE)
            if target not in _TRANSITIONS[self._state]:
                raise FlowStateError(
                    f"invalid transition {self._state} -> {target}", ErrorCode.INVALID_TRANSITION
                )
            if target == WorkStatus.COMPLETE and actor != FlowActor.GATE:
                raise FlowStateError("only Gate may commit COMPLETE", ErrorCode.INVALID_TRANSITION)
            effect_result = effect()
            self._version += 1
            transition = StateTransition(
                self._version,
                self._state,
                target,
                actor,
                reason.strip(),
                datetime.now(timezone.utc),
            )
            self._state = target
            self._history.append(transition)
            return transition, effect_result
