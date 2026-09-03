from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from threading import RLock
from typing import Any
from uuid import uuid4

from jhoc.contracts.errors import ContractError, ErrorCode


class CandidateStatus(StrEnum):
    OBSERVED = "OBSERVED"
    CANDIDATE = "CANDIDATE"
    EVALUATING = "EVALUATING"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    CANARY = "CANARY"
    PROMOTED = "PROMOTED"
    REJECTED = "REJECTED"
    ROLLED_BACK = "ROLLED_BACK"


@dataclass(frozen=True, slots=True)
class Candidate:
    change: str
    evidence_refs: tuple[str, ...]
    status: CandidateStatus = CandidateStatus.OBSERVED
    candidate_id: str = ""
    benchmark_ref: str | None = None
    approved_by: str | None = None
    canary_score: float | None = None
    rollback_reason: str | None = None
    version: str = "1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", CandidateStatus(self.status))
        if not self.candidate_id:
            object.__setattr__(self, "candidate_id", f"candidate:{uuid4()}")
        if not self.change.strip() or not self.evidence_refs:
            raise ContractError("evolution candidates require change and evidence")
        if not self.version.strip():
            raise ContractError("candidate version is required")


@dataclass(frozen=True, slots=True)
class CanaryObservation:
    sequence: int
    healthy: bool
    score: float
    evidence_ref: str

    def __post_init__(self) -> None:
        if self.sequence < 1 or not 0 <= self.score <= 1 or not self.evidence_ref.strip():
            raise ContractError("invalid canary observation")


class Forge:
    _FORBIDDEN_CHANGE_TOKENS = ("governance", "permission", "protocol", "completion gate", "policy authority")

    def __init__(self) -> None:
        self._candidates: dict[str, Candidate] = {}
        self._canary_observations: dict[str, list[CanaryObservation]] = {}
        self._lock = RLock()

    def observe(self, candidate: Candidate) -> Candidate:
        with self._lock:
            self._candidates[candidate.candidate_id] = candidate
            self._canary_observations.setdefault(candidate.candidate_id, [])
            return candidate

    def evaluate(
        self,
        candidate_id: str,
        *,
        regression_free: bool,
        replay_complete: bool = True,
        safety_passed: bool = True,
        benchmark_ref: str = "bench:legacy-compatible",
        benchmark_result: Any | None = None,
    ) -> Candidate:
        with self._lock:
            candidate = self._candidates[candidate_id]
            candidate = replace(candidate, status=CandidateStatus.EVALUATING)
            forbidden = any(token in candidate.change.lower() for token in self._FORBIDDEN_CHANGE_TOKENS)
            benchmark_ok = benchmark_result is None or (
                getattr(benchmark_result, "total", 0) > 0 and getattr(benchmark_result, "pass_rate", 0.0) == 1.0
            )
            accepted = regression_free and replay_complete and safety_passed and benchmark_ok and bool(benchmark_ref.strip()) and not forbidden
            candidate = replace(
                candidate,
                status=CandidateStatus.APPROVAL_REQUIRED if accepted else CandidateStatus.REJECTED,
                benchmark_ref=benchmark_ref if accepted else None,
            )
            self._candidates[candidate_id] = candidate
            return candidate

    def promote(self, candidate_id: str, *, approved: bool, approved_by: str = "operator") -> Candidate:
        with self._lock:
            candidate = self._candidates[candidate_id]
            if candidate.status != CandidateStatus.APPROVAL_REQUIRED or not approved or not approved_by.strip():
                raise ContractError("candidate requires explicit approval", ErrorCode.POLICY_DENIED)
            candidate = replace(candidate, status=CandidateStatus.CANARY, approved_by=approved_by)
            self._candidates[candidate_id] = candidate
            return candidate

    def complete_canary(self, candidate_id: str, *, healthy: bool, score: float, rollback_reason: str | None = None) -> Candidate:
        if not 0 <= score <= 1:
            raise ContractError("canary score must be between zero and one")
        with self._lock:
            candidate = self._candidates[candidate_id]
            if candidate.status != CandidateStatus.CANARY:
                raise ContractError("candidate is not in canary", ErrorCode.INVALID_TRANSITION)
            if healthy:
                candidate = replace(candidate, status=CandidateStatus.PROMOTED, canary_score=score)
            else:
                reason = (rollback_reason or "canary health failed").strip()
                candidate = replace(candidate, status=CandidateStatus.ROLLED_BACK, canary_score=score, rollback_reason=reason)
            self._candidates[candidate_id] = candidate
            return candidate

    def observe_canary(self, candidate_id: str, *, healthy: bool, score: float, evidence_ref: str) -> CanaryObservation:
        with self._lock:
            candidate = self._candidates[candidate_id]
            if candidate.status != CandidateStatus.CANARY:
                raise ContractError("candidate is not in canary", ErrorCode.INVALID_TRANSITION)
            history = self._canary_observations.setdefault(candidate_id, [])
            observation = CanaryObservation(len(history) + 1, healthy, score, evidence_ref)
            history.append(observation)
            return observation

    def canary_history(self, candidate_id: str) -> tuple[CanaryObservation, ...]:
        with self._lock:
            return tuple(self._canary_observations.get(candidate_id, ()))

    def get(self, candidate_id: str) -> Candidate | None:
        with self._lock:
            return self._candidates.get(candidate_id)
