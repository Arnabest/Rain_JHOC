from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping

from jhoc.contracts.errors import ContractError, ErrorCode


class RuntimeMode(StrEnum):
    ONLINE = "ONLINE"
    LIMITED_NETWORK = "LIMITED_NETWORK"
    OFFLINE = "OFFLINE"
    DEGRADED = "DEGRADED"
    EMERGENCY_SAFE_MODE = "EMERGENCY_SAFE_MODE"


_KNOWN_KEYS = frozenset({"mode", "allow_network", "max_concurrency", "max_task_seconds"})


@dataclass(frozen=True, slots=True)
class ConfigSnapshot:
    """Immutable configuration with one explicit source and monotonic version."""

    values: Mapping[str, Any]
    source: str = "defaults"
    version: int = 1
    _frozen_values: Mapping[str, Any] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.version < 1 or not self.source.strip():
            raise ContractError("config source and version are required")
        unknown = set(self.values) - _KNOWN_KEYS
        if unknown:
            raise ContractError(f"unknown config keys: {sorted(unknown)}", ErrorCode.INVALID_CONTRACT)
        try:
            mode = RuntimeMode(self.values.get("mode", RuntimeMode.OFFLINE))
        except ValueError as exc:
            raise ContractError("unknown runtime mode", ErrorCode.INVALID_CONTRACT) from exc
        allow_network = bool(self.values.get("allow_network", False))
        max_concurrency = self.values.get("max_concurrency", 1)
        max_task_seconds = self.values.get("max_task_seconds", 300)
        if mode in {RuntimeMode.OFFLINE, RuntimeMode.EMERGENCY_SAFE_MODE} and allow_network:
            raise ContractError("network cannot be enabled in offline/safe mode", ErrorCode.POLICY_DENIED)
        if not isinstance(max_concurrency, int) or not 1 <= max_concurrency <= 128:
            raise ContractError("max_concurrency must be between 1 and 128")
        if not isinstance(max_task_seconds, int) or not 1 <= max_task_seconds <= 86400:
            raise ContractError("max_task_seconds must be between 1 and 86400")
        normalized = dict(self.values)
        normalized.update(
            mode=mode.value,
            allow_network=allow_network,
            max_concurrency=max_concurrency,
            max_task_seconds=max_task_seconds,
        )
        object.__setattr__(self, "_frozen_values", MappingProxyType(normalized))

    @property
    def mode(self) -> RuntimeMode:
        return RuntimeMode(self._frozen_values["mode"])

    def get(self, key: str, default: Any = None) -> Any:
        return self._frozen_values.get(key, default)

    def as_dict(self) -> dict[str, Any]:
        return dict(self._frozen_values)
