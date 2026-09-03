from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from jhoc.contracts.models import SideEffectState


class RetryDecision(StrEnum):
    RETRY = "RETRY"
    FAIL = "FAIL"
    RECONCILE = "RECONCILE"


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 0.25
    max_delay_seconds: float = 30.0
    multiplier: float = 2.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if self.base_delay_seconds < 0 or self.max_delay_seconds < 0:
            raise ValueError("retry delays cannot be negative")
        if self.base_delay_seconds > self.max_delay_seconds:
            raise ValueError("base delay cannot exceed max delay")
        if self.multiplier < 1:
            raise ValueError("multiplier must be >= 1")

    def delay_seconds(self, attempt: int) -> float:
        """Return deterministic exponential backoff for a 1-based failed attempt."""
        if attempt < 1:
            raise ValueError("attempt must be >= 1")
        return min(self.max_delay_seconds, self.base_delay_seconds * self.multiplier ** (attempt - 1))

    def decide(
        self,
        attempt: int,
        *,
        retryable: bool,
        side_effect_state: SideEffectState = SideEffectState.NOT_APPLICABLE,
    ) -> RetryDecision:
        if side_effect_state in {
            SideEffectState.UNKNOWN_SIDE_EFFECT,
            SideEffectState.PARTIAL,
            SideEffectState.REQUIRES_RECONCILIATION,
        }:
            return RetryDecision.RECONCILE
        if not retryable or attempt >= self.max_attempts:
            return RetryDecision.FAIL
        return RetryDecision.RETRY

