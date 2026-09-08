from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from threading import RLock
from typing import Any
from uuid import UUID, uuid4

from jhoc.config import RuntimeMode
from jhoc.contracts.errors import ContractError, ErrorCode
from jhoc.contracts.sensitivity import SensitivityLevel
from jhoc.trust import Identity


class Decision(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"


class RuleEffect(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"


class SensitivityPolicy:
    """Clearance comparison used by source activation and migration review."""

    _RANK = {level: index for index, level in enumerate(SensitivityLevel)}

    @classmethod
    def allows(cls, clearance: str | SensitivityLevel, requested: str | SensitivityLevel) -> bool:
        try:
            granted = SensitivityLevel(str(clearance).upper())
            needed = SensitivityLevel(str(requested).upper())
        except (TypeError, ValueError) as exc:
            raise ContractError("unknown sensitivity level", ErrorCode.POLICY_DENIED) from exc
        return cls._RANK[granted] >= cls._RANK[needed]


@dataclass(frozen=True, slots=True)
class PolicyRequest:
    operation: str
    risk_level: int
    permission: str | None = None
    external_side_effect: bool = False
    requires_network: bool = False
    sensitive: bool = False
    request_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if not self.operation.strip() or not 0 <= self.risk_level <= 4:
            raise ContractError("operation and risk_level are invalid")


@dataclass(frozen=True, slots=True)
class PolicyRule:
    rule_id: str
    effect: RuleEffect
    operations: frozenset[str] = frozenset()
    max_risk_level: int = 0
    external_side_effect: bool | None = None
    requires_network: bool | None = None
    sensitive: bool | None = None
    required_permission: str | None = None
    priority: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "effect", RuleEffect(self.effect))
        if not self.rule_id.strip() or not 0 <= self.max_risk_level <= 4:
            raise ContractError("invalid policy rule")

    def matches(self, request: PolicyRequest) -> bool:
        return (
            (not self.operations or request.operation in self.operations)
            and request.risk_level <= self.max_risk_level
            and (self.external_side_effect is None or request.external_side_effect == self.external_side_effect)
            and (self.requires_network is None or request.requires_network == self.requires_network)
            and (self.sensitive is None or request.sensitive == self.sensitive)
            and (self.required_permission is None or request.permission == self.required_permission)
        )


@dataclass(frozen=True, slots=True)
class PolicyBundle:
    version: str
    source: str
    rules: tuple[PolicyRule, ...]

    def __post_init__(self) -> None:
        if not self.version.strip() or not self.source.strip() or not self.rules:
            raise ContractError("policy bundle requires version, source, and rules")
        ids = [rule.rule_id for rule in self.rules]
        if len(ids) != len(set(ids)):
            raise ContractError("policy rule IDs must be unique")


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    decision: Decision
    request_id: UUID
    policy_ref: str
    matched_rules: tuple[str, ...]
    reason: str
    evaluated_at: datetime
    operation: str = ""
    identity_id: str | None = None
    mode: str = RuntimeMode.OFFLINE.value


class GuardRuntime:
    """Default-deny policy evaluator with no authority to execute or mutate work."""

    def __init__(self) -> None:
        self._bundle: PolicyBundle | None = None
        self._bundle_history: list[PolicyBundle] = []
        self._decisions: list[PolicyDecision] = []
        self._lock = RLock()

    def load(self, bundle: PolicyBundle) -> None:
        with self._lock:
            self._store_bundle(bundle)
            self._bundle = bundle

    def evaluate(self, identity: Identity | None, request: PolicyRequest, *, mode: RuntimeMode = RuntimeMode.OFFLINE) -> PolicyDecision:
        with self._lock:
            bundle = self._bundle
        now = datetime.now(timezone.utc)
        if bundle is None:
            return self._decision(Decision.DENY, request, "no policy bundle loaded", (), "unloaded", identity, mode)
        if mode in {RuntimeMode.OFFLINE, RuntimeMode.EMERGENCY_SAFE_MODE} and request.requires_network:
            return self._decision(Decision.DENY, request, "network unavailable in current mode", (), bundle.version, identity, mode)
        if request.permission and (identity is None or not identity.active or not identity.permissions.allows(request.permission)):
            return self._decision(Decision.DENY, request, "required permission not granted", (), bundle.version, identity, mode)
        matches = sorted((rule for rule in bundle.rules if rule.matches(request)), key=lambda rule: -rule.priority)
        if not matches:
            return self._decision(Decision.DENY, request, "no matching rule; default deny", (), bundle.version, identity, mode)
        top_priority = matches[0].priority
        top = [rule for rule in matches if rule.priority == top_priority]
        effects = {rule.effect for rule in top}
        matched_ids = tuple(rule.rule_id for rule in top)
        if len(effects) > 1:
            return self._decision(Decision.DENY, request, "conflicting policy rules", matched_ids, bundle.version, identity, mode)
        effect = top[0].effect
        return self._decision(Decision(effect), request, f"matched policy {top[0].rule_id}", matched_ids, bundle.version, identity, mode)

    def decisions(self, *, policy_ref: str | None = None) -> tuple[PolicyDecision, ...]:
        with self._lock:
            return tuple(
                decision for decision in self._decisions if policy_ref is None or decision.policy_ref == policy_ref
            )

    def bundle_history(self) -> tuple[PolicyBundle, ...]:
        with self._lock:
            return tuple(self._bundle_history)

    def _decision(
        self,
        decision: Decision,
        request: PolicyRequest,
        reason: str,
        matched: tuple[str, ...],
        policy_ref: str,
        identity: Identity | None,
        mode: RuntimeMode,
    ) -> PolicyDecision:
        receipt = PolicyDecision(
            decision,
            request.request_id,
            policy_ref,
            matched,
            reason,
            datetime.now(timezone.utc),
            request.operation,
            str(identity.identity_id) if identity else None,
            RuntimeMode(mode).value,
        )
        with self._lock:
            self._store_decision(receipt)
        return receipt

    def _store_bundle(self, bundle: PolicyBundle) -> None:
        self._bundle_history.append(bundle)

    def _store_decision(self, decision: PolicyDecision) -> None:
        self._decisions.append(decision)
