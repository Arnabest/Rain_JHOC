"""JHOC RE-TRAC: Recursive Trajectory Compression & Dead-End Blacklisting Engine.

Implements C4, C5, C6, C8 from Phase 3 Architectural Review:
1. Structured Failure Decomposition:
   - 4-Tuple: Evidence, Uncertainties, DeadEnds, NextSteps.
2. Canonical Action Hashing:
   - Normalizes tool name, flag variations, parameter keys, and whitespace.
   - Distinct parameter variations produce distinct keys and are NOT blocked.
3. Transient vs Deterministic Root-Cause Classification:
   - Deterministic errors (SYNTAX_ERROR, CONTRACT_VIOLATION, TEST_FAILURE, PERMISSION_DENIED)
     are blacklisted immediately.
   - Transient errors (TIMEOUT, RESOURCE_BUSY, NETWORK_RESET) route to retry and require
     K >= 2 identical failures before blacklisting.
4. Harness-Only Write Authority (Rule 2):
   - Only external harness verification can insert or expire dead-end entries; model is strictly read-only.
5. Physical Anti-Looping Interceptor:
   - Pre-dispatch gate intercepts blacklisted actions fail-closed (DEAD_END_INTERCEPTED).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
from pathlib import Path
from threading import RLock
from typing import Any, Mapping

from jhoc.contracts.errors import ContractError, ErrorCode
from jhoc.runner.encoding import to_console_ascii


class RootCauseClass(StrEnum):
    # Deterministic classes
    SYNTAX_ERROR = "SYNTAX_ERROR"
    CONTRACT_VIOLATION = "CONTRACT_VIOLATION"
    TEST_FAILURE = "TEST_FAILURE"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    PATH_TRAVERSAL = "PATH_TRAVERSAL"
    # Transient classes
    TIMEOUT = "TIMEOUT"
    RESOURCE_BUSY = "RESOURCE_BUSY"
    NETWORK_RESET = "NETWORK_RESET"
    RATE_LIMITED = "RATE_LIMITED"


_DETERMINISTIC_CLASSES = {
    RootCauseClass.SYNTAX_ERROR,
    RootCauseClass.CONTRACT_VIOLATION,
    RootCauseClass.TEST_FAILURE,
    RootCauseClass.PERMISSION_DENIED,
    RootCauseClass.PATH_TRAVERSAL,
}


def canonicalize_action(tool_name: str, tool_args: Mapping[str, Any] | None) -> tuple[str, str]:
    """Produces a canonical action representation and SHA-256 hash.
    
    Normalizes:
    - Tool name: lowercase, stripped
    - String arguments: whitespace normalized, trimmed
    - Mapping keys: sorted
    """
    clean_tool = to_console_ascii(str(tool_name).strip().lower())
    clean_args: dict[str, Any] = {}
    if tool_args:
        for k, v in sorted(tool_args.items()):
            norm_k = to_console_ascii(str(k).strip().lower())
            if isinstance(v, str):
                norm_v = " ".join(to_console_ascii(v).split())
            elif isinstance(v, (int, float, bool)):
                norm_v = v
            else:
                norm_v = json.dumps(v, sort_keys=True, ensure_ascii=True)
            clean_args[norm_k] = norm_v

    canonical_sig = f"{clean_tool}:{json.dumps(clean_args, sort_keys=True, ensure_ascii=True)}"
    canonical_hash = hashlib.sha256(canonical_sig.encode("utf-8")).hexdigest()
    return canonical_sig, canonical_hash


@dataclass(frozen=True, slots=True)
class DeadEndEntry:
    action_hash: str
    action_sig: str
    root_cause: str
    diagnostic: str
    failure_count: int
    first_seen_at: str
    last_seen_at: str


@dataclass(frozen=True, slots=True)
class FailureTuple:
    evidence: tuple[str, ...]
    uncertainties: tuple[str, ...]
    dead_ends: tuple[str, ...]
    next_steps: tuple[str, ...]
    degraded_at: str

    def to_diagnostic_summary(self) -> str:
        ev_str = "\n".join(f"  - [FACT] {e}" for e in self.evidence) or "  - None"
        un_str = "\n".join(f"  - [UNVERIFIED] {u}" for u in self.uncertainties) or "  - None"
        de_str = "\n".join(f"  - [BLOCKED_LOOP] {d}" for d in self.dead_ends) or "  - None"
        ns_str = "\n".join(f"  - [PIVOT] {n}" for n in self.next_steps) or "  - None"
        return (
            "[RE-TRAC FAILURE SUMMARY]\n"
            f"1. Verified Evidence:\n{ev_str}\n"
            f"2. Uncertainties:\n{un_str}\n"
            f"3. Blacklisted Dead Ends:\n{de_str}\n"
            f"4. Recommended Pivot Steps:\n{ns_str}"
        )


class DeadEndRegistry:
    """Harness-internal registry tracking failed execution paths to physically prevent loops."""

    def __init__(self, transient_threshold: int = 2) -> None:
        self._lock = RLock()
        self.transient_threshold = max(2, transient_threshold)
        self._entries: dict[str, DeadEndEntry] = {}
        self._transient_counts: dict[str, int] = {}

    def check_action(self, tool_name: str, tool_args: Mapping[str, Any] | None) -> tuple[bool, str]:
        """Pre-dispatch check. Returns (is_allowed, reason). Fail-closed on match."""
        try:
            _, act_hash = canonicalize_action(tool_name, tool_args)
        except Exception as exc:
            # Ambiguity resolves fail-closed (C4)
            return False, f"DEAD_END_INTERCEPTED: Canonicalization failed ({exc}). Defaulting to DENY."

        with self._lock:
            if act_hash in self._entries:
                entry = self._entries[act_hash]
                return (
                    False,
                    f"DEAD_END_INTERCEPTED: Action matches blacklisted dead end [{entry.root_cause}]: {entry.diagnostic}",
                )

        return True, "Action allowed."

    def is_action_blocked(self, tool_name: str, tool_args: Mapping[str, Any] | None) -> bool:
        """Convenience check whether an action is blocked as a dead end."""
        allowed, _ = self.check_action(tool_name, tool_args)
        return not allowed

    def record_failure(
        self,
        tool_name: str,
        tool_args: Mapping[str, Any] | None,
        root_cause: RootCauseClass | str,
        diagnostic: str,
    ) -> tuple[bool, str]:
        """Records an execution failure under harness authority.
        
        Returns (is_blacklisted, decision_message).
        """
        try:
            act_sig, act_hash = canonicalize_action(tool_name, tool_args)
        except Exception:
            clean_tool = to_console_ascii(str(tool_name).strip().lower())
            act_sig = f"{clean_tool}:UNSERIALIZABLE"
            act_hash = hashlib.sha256(act_sig.encode("utf-8")).hexdigest()

        clean_diag = to_console_ascii(diagnostic.strip())[:300]
        now_str = datetime.now(timezone.utc).isoformat()
        rc_str = str(root_cause)

        with self._lock:
            if rc_str in _DETERMINISTIC_CLASSES:
                # Deterministic error -> blacklist immediately
                count = self._entries.get(act_hash, None)
                new_count = (count.failure_count + 1) if count else 1
                entry = DeadEndEntry(
                    action_hash=act_hash,
                    action_sig=act_sig,
                    root_cause=rc_str,
                    diagnostic=clean_diag,
                    failure_count=new_count,
                    first_seen_at=count.first_seen_at if count else now_str,
                    last_seen_at=now_str,
                )
                self._entries[act_hash] = entry
                return True, f"Deterministic failure blacklisted immediately: {rc_str}"

            # Transient error -> check threshold
            cur_t = self._transient_counts.get(act_hash, 0) + 1
            self._transient_counts[act_hash] = cur_t

            if cur_t >= self.transient_threshold:
                entry = DeadEndEntry(
                    action_hash=act_hash,
                    action_sig=act_sig,
                    root_cause=rc_str,
                    diagnostic=f"Transient failure threshold exceeded ({cur_t} attempts): {clean_diag}",
                    failure_count=cur_t,
                    first_seen_at=now_str,
                    last_seen_at=now_str,
                )
                self._entries[act_hash] = entry
                return True, f"Transient threshold exceeded ({cur_t}/{self.transient_threshold}); blacklisted: {rc_str}"

            return False, f"Transient failure recorded ({cur_t}/{self.transient_threshold}); eligible for retry."

    def expire_entry(self, tool_name: str, tool_args: Mapping[str, Any] | None) -> bool:
        """Harness API to expire/un-blacklist an entry upon recovered environment."""
        try:
            _, act_hash = canonicalize_action(tool_name, tool_args)
        except Exception:
            return False
        with self._lock:
            self._transient_counts.pop(act_hash, None)
            return bool(self._entries.pop(act_hash, None))

    def reset_transient(self, tool_name: str, tool_args: Mapping[str, Any] | None) -> None:
        """Harness API to reset transient failure counter upon successful execution."""
        try:
            _, act_hash = canonicalize_action(tool_name, tool_args)
        except Exception:
            return
        with self._lock:
            self._transient_counts.pop(act_hash, None)

    def get_blacklisted_signatures(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(f"[{e.root_cause}] {e.action_sig}" for e in self._entries.values())


class TrajectoryCompressor:
    """Extracts compact RE-TRAC 4-tuple upon failure to guide model pivot."""

    @staticmethod
    def compress(
        verified_evidence: list[str],
        unverified_hypotheses: list[str],
        dead_ends: list[str],
        suggested_pivots: list[str],
    ) -> FailureTuple:
        return FailureTuple(
            evidence=tuple(to_console_ascii(e).strip()[:150] for e in verified_evidence if e.strip()),
            uncertainties=tuple(to_console_ascii(u).strip()[:150] for u in unverified_hypotheses if u.strip()),
            dead_ends=tuple(to_console_ascii(d).strip()[:200] for d in dead_ends if d.strip()),
            next_steps=tuple(to_console_ascii(n).strip()[:150] for n in suggested_pivots if n.strip()),
            degraded_at=datetime.now(timezone.utc).isoformat(),
        )


# Alias for backward and forward compatibility with Phase 5 Harness Pipeline
ReTracEngine = DeadEndRegistry
