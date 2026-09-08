"""JHOC Thin-Adapter Framework for External & Multi-Modal Tools.

Implements C4 from Phase 2 Architectural Review:
1. Two-Tiered Isolation:
   - Crash & fault isolation: separates process/network boundary failures from harness crashes.
   - Typed exception hierarchy: domain failures return structured failure codes; internal harness
     faults remain typed ContractErrors (never collapsed into fake benign status).
2. Cryptographic Pre-Truncation Integrity:
   - SHA-256 computed on the FULL canonical UTF-8 bytes BEFORE any truncation.
   - Full payload persisted out-of-band to logs/audit/adapter_blobs/ with a storage reference.
3. CJK-Aware Token Budget Truncation:
   - Accounts for CJK density (1.0 - 1.5 chars/token vs 4 chars/token for English).
   - Default budget: 4,000 tokens (approx 6,000 - 8,000 characters for mixed CJK text).
4. Pre-Truncation Schema Validation:
   - Input and full output validated against versioned static JSON schemas before truncation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping
import jsonschema

from jhoc.contracts.errors import ContractError, ErrorCode


@dataclass(frozen=True, slots=True)
class AdapterResult:
    is_success: bool
    status_code: str
    data: Any
    original_length_bytes: int
    full_sha256: str
    is_truncated: bool
    storage_ref: str | None
    diagnostic: str = ""


class ThinAdapter:
    """Bounded, crash-isolated thin adapter wrapper for external tools."""

    def __init__(
        self,
        adapter_name: str,
        workspace_root: Path | str | None = None,
        input_schema: Mapping[str, Any] | None = None,
        output_schema: Mapping[str, Any] | None = None,
        token_ceiling: int = 4000,
    ) -> None:
        self.name = adapter_name
        self.root = Path(workspace_root).resolve() if workspace_root else Path.cwd()
        self.input_schema = input_schema
        self.output_schema = output_schema
        self.token_ceiling = token_ceiling
        self.blob_dir = self.root / "logs" / "audit" / "adapter_blobs"
        self.blob_dir.mkdir(parents=True, exist_ok=True)

    def validate_input(self, payload: Any) -> None:
        """Validate input payload against static schema."""
        if self.input_schema is not None:
            try:
                jsonschema.validate(instance=payload, schema=self.input_schema)
            except jsonschema.ValidationError as exc:
                raise ContractError(f"Adapter '{self.name}' input schema validation failed: {exc.message}", ErrorCode.INVALID_CONTRACT) from exc

    def validate_output(self, payload: Any) -> None:
        """Validate full pre-truncation output payload against static schema."""
        if self.output_schema is not None:
            try:
                jsonschema.validate(instance=payload, schema=self.output_schema)
            except jsonschema.ValidationError as exc:
                raise ContractError(f"Adapter '{self.name}' output schema validation failed: {exc.message}", ErrorCode.INVALID_CONTRACT) from exc

    def _estimate_cjk_tokens(self, text: str) -> int:
        """Estimate token count taking into account high CJK density (1.0 - 1.25 chars/token)."""
        if not text:
            return 0
        ascii_chars = sum(1 for ch in text if ord(ch) < 128)
        non_ascii_chars = len(text) - ascii_chars
        return int((ascii_chars / 3.8) + (non_ascii_chars / 1.15))

    def _truncate_to_token_budget(self, text: str) -> tuple[str, bool]:
        """Truncate text safely within the token ceiling."""
        if self._estimate_cjk_tokens(text) <= self.token_ceiling:
            return text, False

        # Binary search for safe character cutoff
        low, high = 0, len(text)
        cutoff = low
        while low <= high:
            mid = (low + high) // 2
            if self._estimate_cjk_tokens(text[:mid]) <= self.token_ceiling:
                cutoff = mid
                low = mid + 1
            else:
                high = mid - 1

        truncated = text[:cutoff] + "\n...[TRUNCATED_BY_THIN_ADAPTER]..."
        return truncated, True

    def execute(self, runner_fn: Callable[..., Any], *args: Any, **kwargs: Any) -> AdapterResult:
        """Execute external action with schema validation, crash isolation, and pre-truncation hashing."""
        # 0. Validate input schema if configured
        if self.input_schema is not None:
            input_payload = kwargs.get("input_payload") if "input_payload" in kwargs else (args[0] if args else None)
            if input_payload is not None:
                self.validate_input(input_payload)

        try:
            raw_result = runner_fn(*args, **kwargs)
        except ContractError:
            raise
        except Exception as exc:
            # Domain / process execution failure captured without crashing harness
            return AdapterResult(
                is_success=False,
                status_code="EXECUTION_ERROR",
                data=None,
                original_length_bytes=0,
                full_sha256="0" * 64,
                is_truncated=False,
                storage_ref=None,
                diagnostic=f"Adapter '{self.name}' execution failed: {exc}",
            )

        try:
            # 1. Validate full pre-truncation output schema
            self.validate_output(raw_result)

            # 2. Serialize full payload and compute canonical SHA-256
            if isinstance(raw_result, str):
                raw_bytes = raw_result.encode("utf-8")
                raw_text = raw_result
            else:
                raw_text = json.dumps(raw_result, ensure_ascii=False)
                raw_bytes = raw_text.encode("utf-8")

            full_sha256 = hashlib.sha256(raw_bytes).hexdigest()
            orig_len = len(raw_bytes)

            # 3. Truncate payload if it exceeds token ceiling
            truncated_text, is_truncated = self._truncate_to_token_budget(raw_text)

            storage_ref: str | None = None
            if is_truncated:
                now_iso = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                blob_file = self.blob_dir / f"{self.name}_{now_iso}_{full_sha256[:8]}.bin"
                blob_file.write_bytes(raw_bytes)
                storage_ref = str(blob_file.relative_to(self.root)).replace("\\", "/")

            final_data = truncated_text if isinstance(raw_result, str) else json.loads(truncated_text) if not is_truncated else {"truncated_payload": truncated_text}
        except ContractError:
            raise
        except Exception as exc:
            return AdapterResult(
                is_success=False,
                status_code="SERIALIZATION_ERROR",
                data=None,
                original_length_bytes=0,
                full_sha256="0" * 64,
                is_truncated=False,
                storage_ref=None,
                diagnostic=f"Adapter '{self.name}' payload serialization failed: {exc}",
            )

        return AdapterResult(
            is_success=True,
            status_code="SUCCESS",
            data=final_data,
            original_length_bytes=orig_len,
            full_sha256=full_sha256,
            is_truncated=is_truncated,
            storage_ref=storage_ref,
            diagnostic="Execution successful.",
        )
