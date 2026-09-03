from __future__ import annotations

import json

from jhoc.contracts import ResultStatus, SideEffectState, WorkStatus
from jhoc.flow import FlowActor, FlowStateMachine
from jhoc.proof import EvidencePackage, ProofStore
from jhoc.contracts.errors import ContractError, ErrorCode


class Gate:
    """Accepts completion only when execution and evidence satisfy policy."""

    def __init__(self, proof: ProofStore) -> None:
        self.proof = proof
        self._prepare_acceptance, self._finalize_acceptance, self._abort_acceptance = (
            proof._bind_gate_writer()
        )

    def accept(self, flow: FlowStateMachine, result, evidence: EvidencePackage) -> str:
        if flow.state != WorkStatus.COMPLETION_PENDING:
            raise ContractError("Gate requires COMPLETION_PENDING")
        self._validate(result, evidence)
        prepared: list[str] = []

        def prepare() -> str:
            digest = self._prepare_acceptance(evidence)
            prepared.append(digest)
            return digest

        try:
            _, digest = flow.transition_with(
                WorkStatus.COMPLETE,
                effect=prepare,
                actor=FlowActor.GATE,
                reason="evidence accepted",
            )
        except BaseException:
            if prepared:
                self._abort_acceptance(prepared[0])
            raise
        self._finalize_acceptance(digest)
        return digest

    def reconcile_acceptance(
        self,
        flow: FlowStateMachine,
        result,
        evidence: EvidencePackage,
    ) -> str:
        """Finalize a previously prepared receipt without rerunning Runner."""
        self._validate(result, evidence)
        digest = evidence.digest
        if self.proof.acceptance(digest) is not None:
            return digest
        if self.proof.pending_acceptance(digest) is None:
            raise ContractError("pending Gate acceptance not found", ErrorCode.INVALID_CONTRACT)
        if flow.state == WorkStatus.COMPLETION_PENDING:
            flow.transition(WorkStatus.COMPLETE, actor=FlowActor.GATE, reason="pending evidence reconciled")
        elif flow.state != WorkStatus.COMPLETE:
            raise ContractError("Gate reconciliation requires pending or complete flow")
        self._finalize_acceptance(digest)
        return digest

    @staticmethod
    def _validate(result, evidence: EvidencePackage) -> None:
        if result.status != ResultStatus.SUCCEEDED:
            raise ContractError("Gate cannot accept non-success result", ErrorCode.POLICY_DENIED)
        if str(result.task_id) != evidence.task_id or str(result.work_id) != evidence.work_id:
            raise ContractError("evidence does not match result", ErrorCode.INVALID_CONTRACT)
        if Gate._canonical(evidence.execution) != Gate._canonical(result.output):
            raise ContractError("evidence execution does not match result output", ErrorCode.INVALID_CONTRACT)
        if evidence.side_effect_state != result.side_effect_state.value:
            raise ContractError("evidence side effect does not match result", ErrorCode.INVALID_CONTRACT)
        if evidence.side_effect_state in {SideEffectState.UNKNOWN_SIDE_EFFECT.value, SideEffectState.REQUIRES_RECONCILIATION.value, SideEffectState.PARTIAL.value}:
            raise ContractError("uncertain side effect requires reconciliation", ErrorCode.UNKNOWN_SIDE_EFFECT)

    def reject(self, flow: FlowStateMachine, *, reconcile: bool = False) -> None:
        target = WorkStatus.REQUIRES_RECONCILIATION if reconcile else WorkStatus.BLOCKED
        flow.transition(target, actor=FlowActor.GATE, reason="completion evidence rejected")

    @staticmethod
    def _canonical(value) -> str:
        """Compare nested execution payloads independent of mapping insertion order."""
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=repr)
