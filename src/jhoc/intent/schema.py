from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from uuid import uuid4


class IntentType(StrEnum):
    LATENT_SPACE_ACTIVATION = "LATENT_SPACE_ACTIVATION"
    DETERMINISTIC_ENGINEERING = "DETERMINISTIC_ENGINEERING"
    SECURITY_AUDIT = "SECURITY_AUDIT"
    COUNTER_QUESTIONING = "COUNTER_QUESTIONING"
    PAPER_DISTILLATION = "PAPER_DISTILLATION"
    PLAN_REVIEW = "PLAN_REVIEW"
    KAIGONG = "KAIGONG"
    SHOUGONG = "SHOUGONG"
    POST_TASK_MEMORY = "POST_TASK_MEMORY"
    TOKEN_STATS = "TOKEN_STATS"
    GENERAL_CONVERSATION = "GENERAL_CONVERSATION"


class DetectionTier(StrEnum):
    TIER_1_RULE = "TIER_1_RULE"
    TIER_2_METRIC = "TIER_2_METRIC"
    TIER_3_LLM_ARBITER = "TIER_3_LLM_ARBITER"
    FALLBACK = "FALLBACK"


@dataclass(frozen=True, slots=True)
class IntentDecision:
    intent: IntentType
    confidence: float
    tier_hit: DetectionTier
    matched_keywords: tuple[str, ...] = ()
    banned_tokens: tuple[str, ...] = ()
    enforced_scaffolding: str | None = None
    decision_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "decision_id": self.decision_id,
            "intent": str(self.intent),
            "confidence": float(self.confidence),
            "tier_hit": str(self.tier_hit),
            "matched_keywords": list(self.matched_keywords),
            "banned_tokens": list(self.banned_tokens),
            "enforced_scaffolding": self.enforced_scaffolding,
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class EnforcedPayload:
    original_prompt: str
    effective_prompt: str
    decision: IntentDecision
    was_transformed: bool
