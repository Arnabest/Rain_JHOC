from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Mapping

from jhoc.contracts.errors import ContractError, ErrorCode


@dataclass(frozen=True, slots=True)
class ParameterTemplate:
    """Pre-compiled command skeleton with typed placeholder slots."""

    tool_id: str
    command_skeleton: tuple[str, ...]
    param_keys: tuple[str, ...]
    allowed_flags: frozenset[str] = field(default_factory=frozenset)
    allow_shell: bool = False  # Fixed invariant: shell invocation is strictly disabled

    def __post_init__(self) -> None:
        if not self.tool_id.strip():
            raise ContractError("tool_id must not be empty", ErrorCode.INVALID_CONTRACT)
        if not self.command_skeleton:
            raise ContractError("command_skeleton must not be empty", ErrorCode.INVALID_CONTRACT)
        if self.allow_shell:
            raise ContractError(
                "allow_shell must be false: shell execution is forbidden",
                ErrorCode.POLICY_DENIED,
            )


class ParameterizedInvocationEngine:
    """SQL Prepared-Statement style invocation binder.

    Ensures arguments remain passive string literals and cannot inject shell operators or code primitives.
    """

    # Characters that alter shell command grammar or spawn subshells
    _DANGEROUS_SHELL_METACHARS_RE = re.compile(r"[;&|><$`\\]|\n|\r|\t|\x00")

    @classmethod
    def validate_literal_argument(cls, key: str, value: Any) -> str:
        """Validates that a parameter argument is a pure passive literal without shell operator semantics."""
        val_str = str(value)
        if cls._DANGEROUS_SHELL_METACHARS_RE.search(val_str):
            raise ContractError(
                f"parameter '{key}' contains dangerous shell operator characters: {val_str!r}",
                ErrorCode.POLICY_DENIED,
            )
        return val_str

    @classmethod
    def compile_and_bind(
        cls,
        template: ParameterTemplate,
        params: Mapping[str, Any],
        *,
        active_flags: tuple[str, ...] = (),
    ) -> tuple[str, ...]:
        """Binds incoming parameters strictly to the pre-compiled template skeleton."""
        if template.allow_shell:
            raise ContractError("shell invocation strictly forbidden", ErrorCode.POLICY_DENIED)

        bound_args: list[str] = list(template.command_skeleton)

        # 1. Bind validated optional flags from allowed whitelist
        for flag in active_flags:
            if flag not in template.allowed_flags:
                raise ContractError(
                    f"flag '{flag}' not in allowed template flags for '{template.tool_id}'",
                    ErrorCode.POLICY_DENIED,
                )
            bound_args.append(flag)

        # 2. Bind positional parameter slots
        for key in template.param_keys:
            if key not in params:
                raise ContractError(
                    f"missing required parameter slot '{key}' for tool '{template.tool_id}'",
                    ErrorCode.INVALID_CONTRACT,
                )
            clean_val = cls.validate_literal_argument(key, params[key])
            bound_args.append(clean_val)

        return tuple(bound_args)
