from __future__ import annotations

from enum import StrEnum

from .errors import ContractError, ErrorCode


class SensitivityLevel(StrEnum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    RESTRICTED = "RESTRICTED"


def normalize_sensitivity(value: str | SensitivityLevel) -> str:
    try:
        normalized = str(value).strip().upper()
        aliases = {"SECRET": SensitivityLevel.RESTRICTED.value, "PRIVATE": SensitivityLevel.RESTRICTED.value}
        if normalized in aliases:
            return aliases[normalized]
        return SensitivityLevel(normalized).value
    except (TypeError, ValueError) as exc:
        raise ContractError("unknown sensitivity level", ErrorCode.POLICY_DENIED) from exc
