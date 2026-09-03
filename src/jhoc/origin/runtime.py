from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from threading import RLock
from typing import Any, Mapping

from jhoc.config import ConfigSnapshot, RuntimeMode
from jhoc.contracts.errors import ContractError, ErrorCode
from jhoc.trust import TrustStore


class StartupState(StrEnum):
    CREATED = "CREATED"
    TRUST_READY = "TRUST_READY"
    CONFIG_READY = "CONFIG_READY"
    RUNNING = "RUNNING"
    SAFE_MODE = "SAFE_MODE"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    STOPPED = "STOPPED"


@dataclass(frozen=True, slots=True)
class OriginHealth:
    state: StartupState
    mode: RuntimeMode | None
    providers: int
    trust_ready: bool
    config_ready: bool


class OriginRuntime:
    """Starts without models, memory, plugins, network, or legacy services."""

    def __init__(self, trust: TrustStore | None = None) -> None:
        self.trust = trust or TrustStore()
        self.config: ConfigSnapshot | None = None
        self.state = StartupState.CREATED
        self._providers: set[str] = set()
        self._lock = RLock()

    def start(self, config: ConfigSnapshot | None = None) -> OriginHealth:
        with self._lock:
            if self.state not in {StartupState.CREATED, StartupState.STOPPED}:
                raise ContractError("origin can only start from CREATED or STOPPED", ErrorCode.INVALID_CONTRACT)
            try:
                self.state = StartupState.TRUST_READY
                self.config = config or ConfigSnapshot({})
                self.state = StartupState.CONFIG_READY
                self.state = (
                    StartupState.SAFE_MODE
                    if self.config.mode == RuntimeMode.EMERGENCY_SAFE_MODE
                    else StartupState.RUNNING
                )
                return self.health()
            except Exception:
                self.state = StartupState.FAILED
                raise

    def stop(self) -> None:
        with self._lock:
            if self.state == StartupState.STOPPED:
                return
            self._providers.clear()
            self.state = StartupState.STOPPED

    def register_provider(self, provider_id: str) -> None:
        with self._lock:
            if self.state not in {StartupState.RUNNING, StartupState.DEGRADED}:
                raise ContractError("providers can only register after safe startup", ErrorCode.INVALID_CONTRACT)
            if not provider_id.strip():
                raise ContractError("provider_id is required")
            self._providers.add(provider_id)

    def can_execute(self, *, risk_level: int, external_side_effect: bool = False) -> bool:
        if self.state not in {StartupState.RUNNING, StartupState.DEGRADED, StartupState.SAFE_MODE}:
            return False
        if self.state == StartupState.SAFE_MODE:
            return risk_level <= 0 and not external_side_effect
        return 0 <= risk_level <= 2 and not external_side_effect

    def health(self) -> OriginHealth:
        config = self.config
        return OriginHealth(
            self.state,
            config.mode if config else None,
            len(self._providers),
            self.state not in {StartupState.CREATED, StartupState.FAILED},
            config is not None,
        )

