"""Strong-typed data contracts for JHOC Governance Engine."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Mapping


class AssetType(StrEnum):
    SKILL = "SKILL"
    LESSON = "LESSON"
    SCRIPT = "SCRIPT"
    TEST = "TEST"
    SCHEMA = "SCHEMA"


class IntentType(StrEnum):
    MULTI_MODEL_CO_REVIEW = "MULTI_MODEL_CO_REVIEW"
    PLAN_REVIEW = "PLAN_REVIEW"
    COUNTER_QUESTIONING = "COUNTER_QUESTIONING"
    KAIGONG = "KAIGONG"
    SHOUGONG = "SHOUGONG"
    PAPER_DISTILLATION = "PAPER_DISTILLATION"
    LATENT_SPACE_ACTIVATION = "LATENT_SPACE_ACTIVATION"
    TOKEN_STATS = "TOKEN_STATS"
    SECURITY_AUDIT = "SECURITY_AUDIT"
    DETERMINISTIC_ENGINEERING = "DETERMINISTIC_ENGINEERING"
    GENERAL_CONVERSATION = "GENERAL_CONVERSATION"


@dataclass(frozen=True, slots=True)
class NegativeLesson:
    lesson_id: str
    symptom: str
    root_cause: str
    rule: str
    is_candidate: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AssetRecord:
    asset_id: str
    asset_type: AssetType
    title: str
    path: str
    intent_affinity: tuple[str, ...]
    triggers: tuple[str, ...]
    executable_tools: tuple[str, ...] = field(default_factory=tuple)
    negative_lessons: tuple[dict[str, str], ...] = field(default_factory=tuple)
    content_summary: str = ""
    source_sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["asset_type"] = self.asset_type.value
        return d

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> AssetRecord:
        atype = AssetType(data.get("asset_type", "SKILL"))
        return cls(
            asset_id=str(data.get("asset_id", "")),
            asset_type=atype,
            title=str(data.get("title", "")),
            path=str(data.get("path", "")),
            intent_affinity=tuple(data.get("intent_affinity", ())),
            triggers=tuple(data.get("triggers", ())),
            executable_tools=tuple(data.get("executable_tools", ())),
            negative_lessons=tuple(data.get("negative_lessons", ())),
            content_summary=str(data.get("content_summary", "")),
            source_sha256=str(data.get("source_sha256", "")),
        )


@dataclass(frozen=True, slots=True)
class IntentMatchResult:
    intent: IntentType
    confidence: float
    tier_hit: str  # TIER_1_RULE | TIER_2_TOPOLOGY | TIER_3_FALLBACK
    matched_asset: AssetRecord | None = None
    is_execution: bool = True
    matched_triggers: tuple[str, ...] = field(default_factory=tuple)
    ephemeral_lines: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent.value,
            "confidence": self.confidence,
            "tier_hit": self.tier_hit,
            "matched_asset": self.matched_asset.to_dict() if self.matched_asset else None,
            "is_execution": self.is_execution,
            "matched_triggers": list(self.matched_triggers),
            "ephemeral_lines": list(self.ephemeral_lines),
        }
