from enum import StrEnum


class ErrorCode(StrEnum):
    INVALID_CONTRACT = "JHOC-CONTRACT-001"
    UNSUPPORTED_VERSION = "JHOC-CONTRACT-002"
    POLICY_DENIED = "JHOC-GUARD-001"
    IDEMPOTENCY_CONFLICT = "JHOC-FLOW-001"
    UNKNOWN_SIDE_EFFECT = "JHOC-FLOW-002"
    INVALID_TRANSITION = "JHOC-FLOW-003"
    STALE_STATE = "JHOC-FLOW-004"
    CANCELLED = "JHOC-FLOW-005"
    RETRY_EXHAUSTED = "JHOC-FLOW-006"
    PLUGIN_PROTOCOL_MISMATCH = "JHOC-PLUGIN-001"
    PLUGIN_STATE_ERROR = "JHOC-PLUGIN-002"
    PLUGIN_VALIDATION_FAILED = "JHOC-PLUGIN-003"


class ContractError(ValueError):
    """Raised when a native contract violates its boundary invariants."""

    def __init__(self, message: str, code: ErrorCode = ErrorCode.INVALID_CONTRACT):
        super().__init__(message)
        self.code = code
