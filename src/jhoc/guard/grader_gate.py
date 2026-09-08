"""JHOC Grader Sanity Gate, Shadow Audit & Emergency Anti-Lockout Mechanism.

Implements C2 & C5 from Phase 2 Architectural Review:
1. Grader Self-Test with Negative Controls:
   - Validates that grading/hook rules properly fail on known-bad inputs and pass on known-good inputs.
   - Fails gracefully toward high-severity audit logging rather than hard-bricking the harness on gate self-defect.
2. Shadow-Audit Mode:
   - Evaluates policy decisions without blocking execution when `shadow_mode=True` or `JHOC_GATE_SHADOW_MODE=1`.
   - Records violations to `logs/audit/shadow_gate.jsonl` to measure false-positive rates.
3. Cryptographically Bounded Emergency Override:
   - Prevents gate lockout defects using an out-of-band HMAC-SHA256 signed token.
   - Single-use, time-bound (<= 15 min TTL), scope-bound, non-replayable.
   - Generates high-severity immutable audit entries in `logs/audit/gate_overrides.jsonl`.
4. Native integration with `jhoc.guard.policy.Decision` and `jhoc.config.RuntimeMode`.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
from threading import RLock
import time
from typing import Any, Callable

from jhoc.config import RuntimeMode
from jhoc.contracts.errors import ContractError, ErrorCode
from jhoc.guard.policy import Decision


class GraderSanityGate:
    """Safeguards the evaluation and hook gate from self-lockouts and broken rules."""

    def __init__(
        self,
        workspace_root: Path | str | None = None,
        shadow_mode: bool = False,
    ) -> None:
        self.root = Path(workspace_root).resolve() if workspace_root else Path.cwd()
        self.shadow_mode = shadow_mode or (os.environ.get("JHOC_GATE_SHADOW_MODE", "0") in ("1", "true", "TRUE"))
        self.audit_dir = self.root / "logs" / "audit"
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        self.shadow_log = self.audit_dir / "shadow_gate.jsonl"
        self.override_log = self.audit_dir / "gate_overrides.jsonl"
        self._lock = RLock()
        self._used_nonces: set[str] = set()
        self._ledger_corrupt: bool = False
        self._load_persisted_nonces()

    def _load_persisted_nonces(self) -> None:
        """Re-hydrate consumed nonces from disk to make single-use defense cross-instance durable."""
        if not self.override_log.is_file():
            return
        try:
            content = self.override_log.read_text(encoding="utf-8", errors="replace")
        except Exception:
            self._ledger_corrupt = True
            return

        for line in content.splitlines():
            line_str = line.strip()
            if not line_str:
                continue
            try:
                data = json.loads(line_str)
                if n := data.get("nonce"):
                    self._used_nonces.add(n)
            except Exception:
                # Corrupt line in security audit ledger -> mark corrupt to fail-closed
                self._ledger_corrupt = True

    def evaluate_with_shadow(
        self,
        rule_name: str,
        violation_detected: bool,
        violation_detail: str,
        context: dict[str, Any] | None = None,
    ) -> tuple[Decision, str]:
        """Evaluate a rule decision, respecting shadow mode if enabled.
        
        If shadow mode is active, violations are logged without blocking execution.
        """
        if not violation_detected:
            return Decision.ALLOW, "Rule check passed."

        if self.shadow_mode:
            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "rule": rule_name,
                "detail": violation_detail,
                "shadow_verdict": "WOULD_DENY",
                "context": context or {},
            }
            try:
                with self.shadow_log.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
            except Exception:
                pass
            return Decision.ALLOW, f"[SHADOW_AUDIT_LOGGED] Would have denied: {violation_detail}"

        return Decision.DENY, violation_detail

    @classmethod
    def generate_emergency_override_token(
        cls,
        signing_secret: str,
        task_id: str,
        scope: str,
        ttl_seconds: int = 900,
    ) -> str:
        """Generates a cryptographically signed, single-use emergency override token.
        
        Format: override:<task_id>:<expiry_unix>:<nonce>:<hex_signature>
        """
        if not signing_secret or len(signing_secret) < 16:
            raise ContractError("signing_secret must be at least 16 bytes", ErrorCode.INVALID_CONTRACT)

        expiry = int(time.time()) + min(ttl_seconds, 900)  # max 15 mins
        nonce = secrets.token_hex(8)
        message = f"{task_id}:{scope}:{expiry}:{nonce}"

        sig = hmac.new(signing_secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"override:{task_id}:{expiry}:{nonce}:{sig}"

    def verify_and_consume_override_token(
        self,
        token: str,
        signing_secret: str,
        current_task_id: str,
        target_scope: str,
    ) -> tuple[bool, str]:
        """Validates and consumes an emergency override token to unblock the harness."""
        if not token.startswith("override:"):
            return False, "Token format invalid (must start with 'override:')."

        parts = token.split(":")
        if len(parts) != 5:
            return False, "Malformed override token structure."

        _, task_id, expiry_str, nonce, signature = parts

        if task_id != current_task_id:
            return False, f"Token task_id mismatch: expected '{current_task_id}', got '{task_id}'."

        try:
            expiry = int(expiry_str)
        except ValueError:
            return False, "Invalid expiry timestamp."

        if time.time() > expiry:
            return False, "Emergency override token has expired."

        with self._lock:
            self._load_persisted_nonces()
            if self._ledger_corrupt:
                return False, "Emergency override rejected: security audit ledger is corrupted or unreadable (fail-closed)."
            if nonce in self._used_nonces:
                return False, "Replay detected: emergency token nonce has already been consumed."

            message = f"{task_id}:{target_scope}:{expiry}:{nonce}"
            expected_sig = hmac.new(signing_secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()

            if not hmac.compare_digest(signature, expected_sig):
                return False, "Cryptographic signature verification failed."

            # Record high-severity security audit event before marking consumed
            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": "EMERGENCY_OVERRIDE_ACTIVATED",
                "task_id": task_id,
                "scope": target_scope,
                "nonce": nonce,
                "mode": RuntimeMode.EMERGENCY_SAFE_MODE.value,
            }
            try:
                with self.override_log.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
            except Exception as exc:
                return False, f"Emergency override rejected: security audit log persistence failed ({exc})."

            # Mark nonce as consumed
            self._used_nonces.add(nonce)

        return True, "Emergency override successfully verified and consumed."

    def run_negative_controls_self_test(
        self,
        rule_evaluator: Callable[[Any], bool],
        known_valid_samples: list[Any],
        known_invalid_samples: list[Any],
    ) -> tuple[bool, str]:
        """Verifies that a rule properly discriminates valid from invalid inputs.
        
        Returns (is_healthy, diagnostic). If unhealthy, harness should enter shadow fallback.
        """
        for s in known_valid_samples:
            try:
                allowed = rule_evaluator(s)
                if not allowed:
                    return False, f"False Positive on valid sample: {s}"
            except Exception as e:
                return False, f"Exception on valid sample {s}: {e}"

        for s in known_invalid_samples:
            try:
                allowed = rule_evaluator(s)
                if allowed:
                    return False, f"False Negative (leak) on invalid sample: {s}"
            except Exception as e:
                return False, f"Exception on invalid sample {s}: {e}"

        return True, "All negative and positive control tests PASSED."
