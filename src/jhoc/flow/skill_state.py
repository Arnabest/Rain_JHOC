"""JHOC Skill State Machine with O(1) Context Window & CoT Ephemeral Scrubbing.

Implements C2, C3, C8, C9 from Phase 3 Architectural Review:
1. Bounded 3-element context tuple:
   - Immutable Skill Spec (<= 400 tokens / 1600 chars)
   - Structured State (<= 300 tokens / 1200 chars, max 10 resident keys)
   - Latest Observation (<= 500 tokens / 2000 chars)
   Total assembled step prompt strictly bounded <= 1200 tokens across arbitrarily long workflows.
2. Ephemeral CoT Use-and-Burn:
   - Intermediate reasoning traces are archived to out-of-band sidecars in logs/op-log/ and incinerated
     from active context memory upon state promotion.
3. Durable persistence with CAS versioning via SQLite StateStore.
4. Pure ASCII and Zero-Emoji enforcement (Rule 7).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping
from uuid import UUID

from jhoc.contracts.errors import ContractError, ErrorCode
from jhoc.runner.encoding import to_console_ascii
from jhoc.storage import StateStore


MAX_SPEC_CHARS = 1600
MAX_STATE_CHARS = 1200
MAX_OBSERVATION_CHARS = 2000
MAX_RESIDENT_KEYS = 10


@dataclass(frozen=True, slots=True)
class ContextTuple:
    skill_spec: str
    structured_state: str
    latest_observation: str
    step_number: int
    version: int

    def to_assembled_prompt(self) -> str:
        return (
            f"[SKILL SPECIFICATION]\n{self.skill_spec}\n\n"
            f"[STRUCTURED STATE (Step {self.step_number}, v{self.version})]\n{self.structured_state}\n\n"
            f"[LATEST OBSERVATION]\n{self.latest_observation}"
        )


@dataclass(frozen=True, slots=True)
class StepState:
    step_number: int
    version: int
    state_variables: Mapping[str, Any]
    latest_observation: str
    promoted_at: str
    sidecar_cot_ref: str | None = None


class SkillStateMachine:
    """Deterministic, O(1) state machine managing execution context transitions."""

    def __init__(
        self,
        skill_name: str,
        skill_spec: str,
        workspace_root: Path | str | None = None,
        initial_variables: Mapping[str, Any] | None = None,
    ) -> None:
        self.skill_name = skill_name
        self.root = Path(workspace_root).resolve() if workspace_root else Path.cwd()
        self.op_log_dir = self.root / "logs" / "op-log"
        self.op_log_dir.mkdir(parents=True, exist_ok=True)

        clean_spec = to_console_ascii(skill_spec.strip())
        if len(clean_spec) > MAX_SPEC_CHARS:
            clean_spec = clean_spec[:MAX_SPEC_CHARS - 30] + "\n...[SPEC_TRUNCATED]..."
        self.skill_spec = clean_spec

        self.current_step = 0
        self.version = 1
        self._persisted_version = 0
        self._state_vars: dict[str, Any] = dict(initial_variables or {})
        self.latest_observation = "INITIAL_STATE"

    @property
    def state_variables(self) -> dict[str, Any]:
        return dict(self._state_vars)

    def assemble_context(self) -> ContextTuple:
        """Assembles bounded 3-element execution context."""
        # 1. Structured state block (bounded to <= 10 keys and <= MAX_STATE_CHARS)
        # Evict oldest keys if exceeding resident limit
        if len(self._state_vars) > MAX_RESIDENT_KEYS:
            keys_to_keep = list(self._state_vars.keys())[-MAX_RESIDENT_KEYS:]
            self._state_vars = {k: self._state_vars[k] for k in keys_to_keep}

        state_json = json.dumps(self._state_vars, sort_keys=True, ensure_ascii=True)
        if len(state_json) > MAX_STATE_CHARS:
            compact_vars = {k: str(v)[:80] for k, v in list(self._state_vars.items())[:MAX_RESIDENT_KEYS]}
            state_json = json.dumps(compact_vars, sort_keys=True, ensure_ascii=True)[:MAX_STATE_CHARS]

        # 2. Observation block
        clean_obs = to_console_ascii(self.latest_observation)
        if len(clean_obs) > MAX_OBSERVATION_CHARS:
            clean_obs = clean_obs[:MAX_OBSERVATION_CHARS - 40] + "\n...[OBSERVATION_TRUNCATED]..."

        return ContextTuple(
            skill_spec=self.skill_spec,
            structured_state=state_json,
            latest_observation=clean_obs,
            step_number=self.current_step,
            version=self.version,
        )

    def advance(
        self,
        state_delta: Mapping[str, Any],
        observation: str,
        cot_scratch: str = "",
        expected_version: int | None = None,
    ) -> StepState:
        """Advances state, persists intermediate CoT to sidecar, and incinerates scratch."""
        if expected_version is not None and expected_version != self.version:
            raise ContractError(
                f"State version mismatch: expected v{expected_version}, current v{self.version}",
                ErrorCode.IDEMPOTENCY_CONFLICT,
            )

        sidecar_ref: str | None = None
        clean_cot = to_console_ascii(cot_scratch.strip())
        if clean_cot:
            # Ephemeral CoT use-and-burn: archive to out-of-band sidecar
            now_iso = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
            cot_hash = hashlib.sha256(clean_cot.encode("utf-8")).hexdigest()[:8]
            sidecar_file = self.op_log_dir / f"cot_{self.skill_name}_{now_iso}_{cot_hash}.log"
            temp_file = self.op_log_dir / f".tmp_{sidecar_file.name}"
            temp_file.write_text(clean_cot, encoding="utf-8")
            temp_file.replace(sidecar_file)
            sidecar_ref = str(sidecar_file.relative_to(self.root)).replace("\\", "/")

        # Apply state delta (ASCII sanitized)
        for k, v in state_delta.items():
            clean_k = to_console_ascii(str(k)).strip()
            clean_v = to_console_ascii(str(v)).strip() if isinstance(v, str) else v
            self._state_vars[clean_k] = clean_v

        # Enforce <= 10 resident keys limit
        if len(self._state_vars) > MAX_RESIDENT_KEYS:
            keys_to_keep = list(self._state_vars.keys())[-MAX_RESIDENT_KEYS:]
            self._state_vars = {k: self._state_vars[k] for k in keys_to_keep}

        clean_obs = to_console_ascii(observation.strip())
        self.latest_observation = clean_obs

        self.current_step += 1
        self.version += 1
        now_str = datetime.now(timezone.utc).isoformat()

        return StepState(
            step_number=self.current_step,
            version=self.version,
            state_variables=dict(self._state_vars),
            latest_observation=clean_obs,
            promoted_at=now_str,
            sidecar_cot_ref=sidecar_ref,
        )

    def persist_to_store(self, state_store: Any, task_id: UUID | str) -> int:
        """Persists current state snapshot into StateStore or SQLiteStore with CAS versioning."""
        owner = "skill_state"
        key = f"{self.skill_name}:{task_id}"

        # Enforce <= 10 resident keys and value truncation bounds on persisted snapshot
        if len(self._state_vars) > MAX_RESIDENT_KEYS:
            keys_to_keep = list(self._state_vars.keys())[-MAX_RESIDENT_KEYS:]
            self._state_vars = {k: self._state_vars[k] for k in keys_to_keep}

        bounded_vars = {k: (str(v)[:120] if isinstance(v, str) else v) for k, v in self._state_vars.items()}

        payload = {
            "skill_name": self.skill_name,
            "skill_spec": self.skill_spec,
            "current_step": self.current_step,
            "version": self.version,
            "state_variables": bounded_vars,
            "latest_observation": self.latest_observation,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        exp_ver = self._persisted_version if self._persisted_version > 0 else 0
        res = None
        if hasattr(state_store, "state_put"):
            res = state_store.state_put(owner, key, payload, expected_version=exp_ver)
        elif hasattr(state_store, "put"):
            res = state_store.put(owner, key, payload, expected_version=exp_ver)
        if res and hasattr(res, "version"):
            self._persisted_version = res.version
        return self.version

    @classmethod
    def load_from_store(
        cls,
        state_store: Any,
        skill_name: str,
        task_id: UUID | str,
        workspace_root: Path | str | None = None,
    ) -> SkillStateMachine:
        """Reconstructs state machine from durable store snapshot."""
        owner = "skill_state"
        key = f"{skill_name}:{task_id}"
        record = None
        if hasattr(state_store, "state_get"):
            record = state_store.state_get(owner, key)
        elif hasattr(state_store, "get"):
            record = state_store.get(owner, key)

        if not record:
            raise ContractError(f"No state snapshot found for {owner}:{key}", ErrorCode.STALE_STATE)

        val = record.value if hasattr(record, "value") else record
        if isinstance(val, str):
            data = json.loads(val)
        elif isinstance(val, dict):
            data = val
        else:
            raise ContractError(f"Invalid state data format: {type(val)}", ErrorCode.INVALID_CONTRACT)

        sm = cls(
            skill_name=data["skill_name"],
            skill_spec=data["skill_spec"],
            workspace_root=workspace_root,
            initial_variables=data.get("state_variables"),
        )
        sm.current_step = int(data["current_step"])
        sm.version = int(data["version"])
        sm._persisted_version = record.version if hasattr(record, "version") else 0
        sm.latest_observation = data.get("latest_observation", "")
        return sm
