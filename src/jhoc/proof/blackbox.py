from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
from threading import RLock
from typing import Any, Mapping

from jhoc.contracts.errors import ContractError, ErrorCode


class BlackBoxPlane(StrEnum):
    DATA = "DATA"
    CONTROL = "CONTROL"


class BlackBoxStepType(StrEnum):
    USER = "USER"
    SEEN = "SEEN"
    THINK = "THINK"
    TOOL = "TOOL"
    BACK = "BACK"

    @property
    def plane(self) -> BlackBoxPlane:
        if self in {BlackBoxStepType.USER, BlackBoxStepType.SEEN, BlackBoxStepType.BACK}:
            return BlackBoxPlane.DATA
        return BlackBoxPlane.CONTROL


@dataclass(frozen=True, slots=True)
class BlackBoxEntry:
    sequence: int
    timestamp: str
    step_type: BlackBoxStepType
    actor: str
    content: Mapping[str, Any]
    previous_hash: str
    entry_hash: str

    @property
    def plane(self) -> BlackBoxPlane:
        return self.step_type.plane


    @classmethod
    def compute_hash(
        cls,
        sequence: int,
        timestamp: str,
        step_type: BlackBoxStepType,
        actor: str,
        content: Mapping[str, Any],
        previous_hash: str,
    ) -> str:
        payload = {
            "sequence": sequence,
            "timestamp": timestamp,
            "step_type": step_type.value,
            "actor": actor,
            "content": dict(content),
            "previous_hash": previous_hash,
        }
        raw = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()


class BlackBoxJournal:
    """Append-only, cryptographically-chained AI execution black box trace.

    Records the canonical five-tuple: USER, SEEN, THINK, TOOL, BACK.
    """

    GENESIS_HASH = "0" * 64

    # High-risk keywords for attack-chain early detection
    SUSPICIOUS_TOOL_NAMES = frozenset({
        "cordis_define",
        "cordis_run",
        "subprocess",
        "spawn",
        "shell_exec",
        "system",
        "bash",
    })

    def __init__(self, task_id: str, work_id: str) -> None:
        if not task_id.strip() or not work_id.strip():
            raise ContractError("task_id and work_id must not be empty", ErrorCode.INVALID_CONTRACT)
        self.task_id = task_id
        self.work_id = work_id
        self._entries: list[BlackBoxEntry] = []
        self._lock = RLock()

    @property
    def entries(self) -> tuple[BlackBoxEntry, ...]:
        with self._lock:
            return tuple(self._entries)

    @property
    def length(self) -> int:
        with self._lock:
            return len(self._entries)

    @property
    def latest_hash(self) -> str:
        with self._lock:
            if not self._entries:
                return self.GENESIS_HASH
            return self._entries[-1].entry_hash

    def append(
        self,
        step_type: BlackBoxStepType | str,
        actor: str,
        content: Mapping[str, Any] | str,
    ) -> BlackBoxEntry:
        """Appends a new immutable step to the journal with cryptographic chaining."""
        resolved_type = BlackBoxStepType(step_type)
        payload = {"data": content} if isinstance(content, str) else dict(content)
        timestamp = datetime.now(timezone.utc).isoformat()

        with self._lock:
            seq = len(self._entries) + 1
            prev_hash = self.latest_hash
            curr_hash = BlackBoxEntry.compute_hash(
                seq, timestamp, resolved_type, actor, payload, prev_hash
            )
            entry = BlackBoxEntry(
                sequence=seq,
                timestamp=timestamp,
                step_type=resolved_type,
                actor=actor,
                content=payload,
                previous_hash=prev_hash,
                entry_hash=curr_hash,
            )
            self._entries.append(entry)
            return entry

    def verify_integrity(self) -> bool:
        """Verifies the complete hash chain from genesis to head."""
        with self._lock:
            expected_prev = self.GENESIS_HASH
            for idx, entry in enumerate(self._entries, start=1):
                if entry.sequence != idx:
                    return False
                if entry.previous_hash != expected_prev:
                    return False
                recalculated = BlackBoxEntry.compute_hash(
                    entry.sequence,
                    entry.timestamp,
                    entry.step_type,
                    entry.actor,
                    entry.content,
                    entry.previous_hash,
                )
                if recalculated != entry.entry_hash:
                    return False
                expected_prev = entry.entry_hash
            return True

    def detect_anomalies(self) -> list[str]:
        """Scans the event trail for prompt injection and unauthorized tool chain patterns."""
        anomalies: list[str] = []
        with self._lock:
            saw_injected_hint = False
            for entry in self._entries:
                data_str = json.dumps(dict(entry.content), ensure_ascii=False, default=str).lower()

                if entry.step_type == BlackBoxStepType.SEEN:
                    # Detect potential hidden prompt injection markers in ingested documents
                    if any(m in data_str for m in ["ignore previous", "忽略先前", "system prompt", "【隐藏指令】"]):
                        saw_injected_hint = True
                        anomalies.append(
                            f"seq {entry.sequence}: potential prompt injection indicator detected in context"
                        )

                elif entry.step_type == BlackBoxStepType.TOOL:
                    tool_name = str(entry.content.get("tool", entry.content.get("name", ""))).lower()
                    if tool_name in self.SUSPICIOUS_TOOL_NAMES or any(s in tool_name for s in ["subprocess", "cordis"]):
                        anomalies.append(
                            f"seq {entry.sequence}: unauthorized/suspicious tool invocation attempt: '{tool_name}'"
                        )
                        if saw_injected_hint:
                            anomalies.append(
                                f"seq {entry.sequence}: CRITICAL: prompt injection followed by exploit tool execution!"
                            )

        return anomalies

    def export_evidence_digest(self) -> str:
        """Exports an immutable evidence hash for Gate Proof integration."""
        if not self.verify_integrity():
            raise ContractError("black box journal failed integrity check", ErrorCode.INVALID_CONTRACT)
        summary = {
            "task_id": self.task_id,
            "work_id": self.work_id,
            "entry_count": len(self._entries),
            "latest_hash": self.latest_hash,
        }
        return hashlib.sha256(json.dumps(summary, sort_keys=True).encode("utf-8")).hexdigest()
