from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from jhoc.config import RuntimeMode
from jhoc.contracts.errors import ContractError
from jhoc.guard import Decision, GuardRuntime, PolicyRequest
from jhoc.quota import QuotaManager, ResourceLease, ResourcePlan
from jhoc.registry import CapabilityRegistry, VerificationStatus
from jhoc.shelf import Shelf
from jhoc.trust import Identity


class PlanDecision(StrEnum):
    SELECTED = "SELECTED"
    REJECTED = "REJECTED"
    REQUIRES_APPROVAL = "REQUIRES_APPROVAL"


class CandidateDecision(StrEnum):
    SELECTED = "SELECTED"
    REJECTED = "REJECTED"
    NOT_EVALUATED = "NOT_EVALUATED"


@dataclass(frozen=True, slots=True)
class CapabilityRequest:
    operation: str
    candidates: tuple[tuple[str, str], ...]
    resource_plan: ResourcePlan

    def __post_init__(self) -> None:
        if not self.operation.strip() or not self.candidates:
            raise ContractError("capability request requires operation and candidates")
        if any(not capability_id.strip() or not version.strip() for capability_id, version in self.candidates):
            raise ContractError("capability candidates require IDs and versions")


@dataclass(frozen=True, slots=True)
class CapabilityPlan:
    decision: PlanDecision
    operation: str
    selected: tuple[str, str] | None
    lease_id: str | None
    reason: str
    considered: tuple[tuple[str, str], ...]
    assessments: tuple["CandidateAssessment", ...] = ()


@dataclass(frozen=True, slots=True)
class CandidateAssessment:
    capability_id: str
    version: str
    decision: CandidateDecision
    reason: str


class Conductor:
    """The only runtime selector; Guard and Quota remain authoritative."""

    def __init__(self, registry: CapabilityRegistry, shelf: Shelf, quota: QuotaManager, guard: GuardRuntime) -> None:
        self.registry = registry
        self.shelf = shelf
        self.quota = quota
        self.guard = guard

    def select(
        self,
        identity: Identity | None,
        policy_request: PolicyRequest,
        request: CapabilityRequest,
        *,
        mode: RuntimeMode = RuntimeMode.OFFLINE,
    ) -> CapabilityPlan:
        if policy_request.operation != request.operation:
            raise ContractError("policy and capability operations must match")
        considered = tuple(request.candidates)
        decision = self.guard.evaluate(identity, policy_request, mode=mode)
        if decision.decision == Decision.REQUIRE_APPROVAL:
            return CapabilityPlan(
                PlanDecision.REQUIRES_APPROVAL, request.operation, None, None, decision.reason, considered,
                self._not_evaluated(considered, "guard approval required"),
            )
        if decision.decision != Decision.ALLOW:
            return CapabilityPlan(
                PlanDecision.REJECTED, request.operation, None, None, decision.reason, considered,
                self._not_evaluated(considered, "guard denied capability evaluation"),
            )
        assessments: list[CandidateAssessment] = []
        for index, (capability_id, version) in enumerate(request.candidates):
            record = self.registry.get(capability_id, version)
            entry = self.shelf.get(capability_id, version)
            if record is None:
                assessments.append(CandidateAssessment(capability_id, version, CandidateDecision.REJECTED, "not registered"))
                continue
            if record.verification_status != VerificationStatus.VERIFIED:
                assessments.append(CandidateAssessment(capability_id, version, CandidateDecision.REJECTED, "registry record is not verified"))
                continue
            if entry is None:
                assessments.append(CandidateAssessment(capability_id, version, CandidateDecision.REJECTED, "not admitted to shelf"))
                continue
            if entry.health not in {"HEALTHY", "READY"}:
                assessments.append(CandidateAssessment(capability_id, version, CandidateDecision.REJECTED, f"shelf health is {entry.health}"))
                continue
            try:
                lease = self.quota.acquire(f"{request.operation}:{capability_id}", request.resource_plan)
            except ContractError as error:
                assessments.append(CandidateAssessment(capability_id, version, CandidateDecision.REJECTED, f"quota denied: {error}"))
                continue
            assessments.append(CandidateAssessment(capability_id, version, CandidateDecision.SELECTED, "verified, healthy and admitted by quota"))
            assessments.extend(
                self._not_evaluated(request.candidates[index + 1 :], "not evaluated after earlier selection")
            )
            return CapabilityPlan(
                PlanDecision.SELECTED, request.operation, (capability_id, version), lease.lease_id,
                f"selected verified capability {capability_id}@{version}", considered, tuple(assessments),
            )
        return CapabilityPlan(
            PlanDecision.REJECTED, request.operation, None, None,
            "no verified healthy capability admitted by quota", tuple(considered), tuple(assessments),
        )

    def release(self, plan: CapabilityPlan) -> None:
        if plan.lease_id:
            self.quota.release(plan.lease_id)

    @staticmethod
    def _not_evaluated(
        candidates: Iterable[tuple[str, str]], reason: str
    ) -> tuple[CandidateAssessment, ...]:
        return tuple(
            CandidateAssessment(capability_id, version, CandidateDecision.NOT_EVALUATED, reason)
            for capability_id, version in candidates
        )
