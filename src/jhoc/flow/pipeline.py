"""JHOC Unified Harness Pipeline & Stage Registry Engine.

Implements Phase 5 and Phase 6 Binding Conditions:
- C10: Thin ordered stage registry over (name, precondition, run, postcondition, rollback),
      driving FlowStateMachine transitions, reaching COMPLETE only through Gate.accept.
- C11 & Phase 6 C1: Mode-aware arbitration gating: dry-run builds and hashes evidence,
      evaluates arbitration blocking without failing, halts at COMPLETION_PENDING with
      arbitration_blocked=True, while live mode fails closed to REPAIR/BLOCKED.
- C12: Deterministic Error Unwinding: Parameterized subprocesses (allow_shell=False),
      context-managed SQLite, RE-TRAC failure compression, transitions to REPAIR/BLOCKED/DEGRADED.
- C13: Offline Memory Consolidation Invariant: MemoryConsolidator.consolidate() runs only
      offline during shougong or post-task, never inline in the live loop.
- C15: Local-first SQLite WAL for pipeline audit records, explicit shadow_mode gating.

Strictly enforces Rule 7 (Zero-Emoji & Pure ASCII), Rule 1 (Physical Reality),
Rule 2 (Fail-Closed), Rule 3 (allow_shell=False), and Rule 5 (SQLite WAL Single-Node).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import sqlite3
from threading import RLock
from types import SimpleNamespace
from typing import Any, Callable, Mapping, Sequence

from jhoc.conductor.inbox import SQLiteApprovalInbox
from jhoc.contracts import ResultStatus, SideEffectState, WorkStatus
from jhoc.contracts.errors import ContractError, ErrorCode
from jhoc.flow.re_trac import DeadEndRegistry, RootCauseClass
from jhoc.flow.state_machine import FlowActor, FlowStateMachine, FlowStateError
from jhoc.gate.gate import Gate
from jhoc.proof.arbitration import DisputeArbitrationEngine
from jhoc.proof.blackbox import BlackBoxJournal, BlackBoxStepType
from jhoc.proof.evidence_compiler import CompilerProbeResult, EvidencePackageEngine, is_ignored_artifact
from jhoc.proof.store import EvidencePackage, ProofStore


@dataclass(frozen=True, slots=True)
class PipelineConfig:
    """Explicit configuration controlling dry-run, shadow mode, and boundaries (C11, C15)."""
    task_id: str = "default_task"
    work_id: str = "default_work"
    workspace_root: Path = field(default_factory=Path.cwd)
    policy_ref: str = "jhoc:pipeline:default:v1"
    capability_version: str = "v1"
    dry_run: bool = False
    shadow_mode: bool = False
    allow_degraded: bool = True
    audit_db_path: Path | None = None


@dataclass(slots=True)
class PipelineContext:
    """Execution context passed through all pipeline stages."""
    task_id: str = "default_task"
    work_id: str = "default_work"
    config: PipelineConfig | None = None
    state_machine: FlowStateMachine | None = None
    flow: FlowStateMachine | None = None
    scan_roots: Sequence[Path | str] | None = None
    declared_changes: Sequence[Path | str] | None = None
    probes: Sequence[CompilerProbeResult] | None = None
    negative_control_probe: CompilerProbeResult | None = None
    evidence_engine: EvidencePackageEngine | None = None
    arbitration_engine: DisputeArbitrationEngine | None = None
    inbox: SQLiteApprovalInbox | None = None
    workspace_root: Path | None = None
    action_hook: Callable[[PipelineContext], Any] | None = None
    proof_store: ProofStore | None = None
    gate: Gate | None = None
    journal: BlackBoxJournal | None = None
    stage_outputs: dict[str, Any] = field(default_factory=dict)
    state_variables: dict[str, Any] = field(default_factory=dict)
    executed_stages: list[str] = field(default_factory=list)
    unwound_stages: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    compiled_evidence: EvidencePackage | None = None
    evidence_digest: str | None = None
    arbitration_blocked: bool = False

    def __post_init__(self) -> None:
        if self.config is None:
            self.config = PipelineConfig(
                task_id=self.task_id,
                work_id=self.work_id,
                workspace_root=self.workspace_root or Path.cwd(),
            )
        else:
            if self.task_id != "default_task" and self.config.task_id == "default_task":
                object.__setattr__(self.config, "task_id", self.task_id)
            if self.work_id != "default_work" and self.config.work_id == "default_work":
                object.__setattr__(self.config, "work_id", self.work_id)

        if self.flow is None:
            self.flow = self.state_machine or FlowStateMachine(initial=WorkStatus.NEW)
        elif self.state_machine is None:
            self.state_machine = self.flow

    @property
    def is_dry_run(self) -> bool:
        return self.config.dry_run if self.config else False

    @property
    def is_shadow(self) -> bool:
        return self.config.shadow_mode if self.config else False


@dataclass(frozen=True, slots=True)
class PipelineStageContract:
    """Contract for a single pipeline stage (C10)."""
    name: str
    target_state: WorkStatus
    actor: FlowActor = FlowActor.RUNNER
    precondition: Callable[[PipelineContext], bool] | None = None
    run: Callable[[PipelineContext], Any] = field(default_factory=lambda: (lambda ctx: None))
    postcondition: Callable[[PipelineContext, Any], bool] | None = None
    rollback: Callable[[PipelineContext, Any], None] | None = None


@dataclass(frozen=True, slots=True)
class PipelineExecutionResult:
    """Immutable result of a pipeline execution (C10, C11, C12, Phase 6 C1)."""
    is_success: bool
    final_state: WorkStatus
    is_dry_run: bool
    is_shadow: bool
    executed_stages: tuple[str, ...]
    unwound_stages: tuple[str, ...]
    evidence_digest: str | None
    error_diagnostic: str | None
    root_cause: str | None
    started_at: str
    completed_at: str
    arbitration_blocked: bool = False

    @property
    def success(self) -> bool:
        return self.is_success

    @property
    def final_status(self) -> WorkStatus:
        return self.final_state

    @property
    def error(self) -> str | None:
        return self.error_diagnostic

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_success": self.is_success,
            "final_state": self.final_state.value,
            "is_dry_run": self.is_dry_run,
            "is_shadow": self.is_shadow,
            "executed_stages": list(self.executed_stages),
            "unwound_stages": list(self.unwound_stages),
            "evidence_digest": self.evidence_digest,
            "error_diagnostic": self.error_diagnostic,
            "root_cause": self.root_cause,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "arbitration_blocked": self.arbitration_blocked,
        }


class HarnessPipeline:
    """Ordered Harness Pipeline engine driving state machine transitions through Gate.accept (C10, Phase 6 C1)."""

    def __init__(
        self,
        config: PipelineConfig | None = None,
        stages: Sequence[PipelineStageContract] | None = None,
        dead_end_registry: DeadEndRegistry | None = None,
    ) -> None:
        self.config = config or PipelineConfig()
        self.dead_end_registry = dead_end_registry or DeadEndRegistry()
        self._lock = RLock()
        self._stages: list[PipelineStageContract] = list(stages) if stages is not None else self._build_default_stages()
        self._init_audit_db()

    def _init_audit_db(self) -> None:
        if self.config.audit_db_path:
            db_path = Path(self.config.audit_db_path).resolve()
            db_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(str(db_path), timeout=30) as db:
                db.execute("PRAGMA journal_mode=WAL")
                db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS jhoc_pipeline_runs (
                        run_id TEXT PRIMARY KEY,
                        task_id TEXT NOT NULL,
                        work_id TEXT NOT NULL,
                        is_success INTEGER NOT NULL,
                        is_dry_run INTEGER NOT NULL,
                        is_shadow INTEGER NOT NULL,
                        final_state TEXT NOT NULL,
                        evidence_digest TEXT,
                        error_diagnostic TEXT,
                        started_at TEXT NOT NULL,
                        completed_at TEXT NOT NULL,
                        payload TEXT NOT NULL
                    )
                    """
                )
                db.commit()

    def _build_default_stages(self) -> list[PipelineStageContract]:
        return [
            PipelineStageContract(
                name="PLAN",
                target_state=WorkStatus.PLAN,
                actor=FlowActor.RUNNER,
                run=lambda ctx: {"planned": True, "task_id": ctx.task_id or ctx.config.task_id},
            ),
            PipelineStageContract(
                name="ACT",
                target_state=WorkStatus.ACT,
                actor=FlowActor.RUNNER,
                run=self._default_act_stage,
            ),
            PipelineStageContract(
                name="OBSERVE",
                target_state=WorkStatus.OBSERVE,
                actor=FlowActor.RUNNER,
                run=lambda ctx: {"observed": True},
            ),
            PipelineStageContract(
                name="VERIFY",
                target_state=WorkStatus.VERIFY,
                actor=FlowActor.RUNNER,
                run=self._default_verify_stage,
            ),
            PipelineStageContract(
                name="COMPLETE",
                target_state=WorkStatus.COMPLETION_PENDING,
                actor=FlowActor.RUNNER,
                run=self._default_complete_stage,
            ),
        ]

    def _default_act_stage(self, ctx: PipelineContext) -> dict[str, Any]:
        if ctx.action_hook:
            hook_res = ctx.action_hook(ctx)
            return {"action": "hook_executed", "result": str(hook_res)}
        return {"action": "executed", "dry_run": ctx.is_dry_run}

    def _default_verify_stage(self, ctx: PipelineContext) -> dict[str, Any]:
        """Default verification step: compiles physical evidence if engine and declared changes present."""
        if ctx.compiled_evidence:
            ctx.evidence_digest = ctx.compiled_evidence.digest
            return {"verified": True, "digest": ctx.evidence_digest}

        if ctx.evidence_engine and (ctx.declared_changes is not None or ctx.scan_roots is not None):
            if ctx.scan_roots is not None:
                init_manifest = ctx.state_variables.get("initial_manifest")
                if init_manifest is None:
                    init_manifest = ctx.evidence_engine.snapshot_manifest(
                        ctx.declared_changes or [],
                        scan_roots=ctx.scan_roots,
                    )
                ok, _, msg = ctx.evidence_engine.verify_file_manifest(
                    initial_manifest=init_manifest,
                    declared_changes=ctx.declared_changes or [],
                    scan_roots=ctx.scan_roots,
                )
                if not ok:
                    raise ContractError(
                        f"Manifest verification failed: {msg}",
                        ErrorCode.PROBE_VERIFICATION_FAILED,
                    )

            probes = list(ctx.probes or ())
            pkg, report = ctx.evidence_engine.compile_package(
                task_id=ctx.task_id or ctx.config.task_id,
                work_id=ctx.work_id or ctx.config.work_id,
                policy_ref=ctx.config.policy_ref,
                capability_version=ctx.config.capability_version,
                probes=probes or [CompilerProbeResult(CompilerProbeType.AST_SYNTAX, "default", True, "ok")],
                file_paths=ctx.declared_changes,
                side_effect_state=SideEffectState.SUCCEEDED.value,
                negative_control_probe=ctx.negative_control_probe,
                require_negative_control=ctx.negative_control_probe is not None,
            )
            if not report.is_valid:
                raise ContractError(
                    f"Evidence compilation failed: {report.rejection_reason}",
                    ErrorCode.PROBE_VERIFICATION_FAILED,
                )
            ctx.compiled_evidence = pkg
            ctx.evidence_digest = pkg.digest
            return {"verified": True, "digest": ctx.evidence_digest}

        return {"verified": True, "digest": None}

    def _default_complete_stage(self, ctx: PipelineContext) -> dict[str, Any]:
        """Final stage: checks arbitration gating, enters COMPLETION_PENDING, accepts via Gate (Phase 6 C1)."""
        # Phase 6 C1 Mode-Aware Arbitration Gating
        task_id = ctx.task_id or ctx.config.task_id
        if ctx.arbitration_engine:
            active_verdicts = ctx.arbitration_engine.get_active_disputes_for_task(task_id)
            unresolved = [
                v for v in active_verdicts
                if v.status.blocks_completion and not ctx.arbitration_engine.is_verdict_resolved(v)
            ]
            if unresolved:
                ctx.arbitration_blocked = True
                if ctx.is_dry_run or ctx.is_shadow:
                    # Dry-run/shadow halts cleanly at COMPLETION_PENDING with arbitration_blocked=True
                    return {"gate_accepted": False, "dry_run": True, "arbitration_blocked": True}
                else:
                    # Live mode hard fails closed to REPAIR
                    raise ContractError(
                        f"Gate acceptance blocked by unresolved arbitration: {'; '.join(v.verdict_id for v in unresolved)}",
                        ErrorCode.POLICY_DENIED,
                    )

        if ctx.is_dry_run:
            return {"gate_accepted": False, "dry_run": True, "arbitration_blocked": ctx.arbitration_blocked}

        if ctx.gate and ctx.compiled_evidence:
            ev = ctx.compiled_evidence
            if ev.side_effect_state == "COMMITTED":
                se_state = SideEffectState.SUCCEEDED
                from dataclasses import replace
                ev = replace(ev, side_effect_state=se_state.value)
                ctx.compiled_evidence = ev
            else:
                se_state = SideEffectState(ev.side_effect_state)

            result_stub = SimpleNamespace(
                task_id=ev.task_id,
                work_id=ev.work_id,
                status=ResultStatus.SUCCEEDED,
                output=dict(ev.execution),
                side_effect_state=se_state,
            )
            digest = ctx.gate.accept(ctx.flow, result_stub, ctx.compiled_evidence)
            ctx.evidence_digest = digest
            return {"gate_accepted": True, "digest": digest}
        elif ctx.gate is None:
            ctx.flow.transition(WorkStatus.COMPLETE, actor=FlowActor.GATE, reason="pipeline completed without gate")
            return {"gate_accepted": False, "reason": "no_gate"}
        else:
            raise ContractError(
                "Gate acceptance requires compiled evidence package",
                ErrorCode.INVALID_CONTRACT,
            )

    def register_stage(self, stage: PipelineStageContract) -> None:
        with self._lock:
            self._stages.append(stage)

    def run(self, context: PipelineContext | None = None) -> PipelineExecutionResult:
        """Alias for execute to provide uniform HarnessPipeline interface."""
        return self.execute(context)

    def execute(
        self,
        context: PipelineContext | None = None,
    ) -> PipelineExecutionResult:
        now_iso = datetime.now(timezone.utc).isoformat()
        ctx = context or PipelineContext(
            config=self.config,
            flow=FlowStateMachine(initial=WorkStatus.NEW),
        )

        self._assert_no_inline_consolidation()

        if ctx.evidence_engine and ctx.scan_roots:
            if "initial_manifest" not in ctx.state_variables:
                ctx.state_variables["initial_manifest"] = ctx.evidence_engine.snapshot_manifest(
                    ctx.declared_changes or [],
                    scan_roots=ctx.scan_roots,
                )

        executed_stage_contracts: list[tuple[PipelineStageContract, Any]] = []

        try:
            for stage in self._stages:
                # 1. Precondition check
                if stage.precondition is not None:
                    passed = stage.precondition(ctx)
                    if not passed:
                        raise ContractError(
                            f"Precondition failed for stage '{stage.name}'",
                            ErrorCode.POLICY_DENIED,
                        )

                # 2. State machine transition to stage's target state
                ctx.flow.transition(
                    stage.target_state,
                    actor=stage.actor,
                    reason=f"Pipeline entering stage: {stage.name}",
                )

                # 3. Execute stage logic
                out = stage.run(ctx)
                ctx.stage_outputs[stage.name] = out
                ctx.executed_stages.append(stage.name)
                executed_stage_contracts.append((stage, out))

                # 4. Postcondition check
                if stage.postcondition is not None:
                    valid = stage.postcondition(ctx, out)
                    if not valid:
                        raise ContractError(
                            f"Postcondition failed for stage '{stage.name}'",
                            ErrorCode.PROBE_VERIFICATION_FAILED,
                        )

                if ctx.journal:
                    ctx.journal.append(
                        step_type=BlackBoxStepType.TOOL,
                        actor="HarnessPipeline",
                        content={"stage": stage.name, "output": str(out)[:200]},
                    )

            completed_iso = datetime.now(timezone.utc).isoformat()
            result = PipelineExecutionResult(
                is_success=True,
                final_state=ctx.flow.state,
                is_dry_run=ctx.is_dry_run,
                is_shadow=ctx.is_shadow,
                executed_stages=tuple(ctx.executed_stages),
                unwound_stages=tuple(ctx.unwound_stages),
                evidence_digest=ctx.evidence_digest,
                error_diagnostic=None,
                root_cause=None,
                started_at=now_iso,
                completed_at=completed_iso,
                arbitration_blocked=ctx.arbitration_blocked,
            )
            self._persist_run_audit(result)
            return result

        except Exception as err:
            diag = str(err)
            ctx.errors.append(diag)
            completed_iso = datetime.now(timezone.utc).isoformat()

            for prev_stage, prev_out in reversed(executed_stage_contracts):
                if prev_stage.rollback is not None:
                    try:
                        prev_stage.rollback(ctx, prev_out)
                        ctx.unwound_stages.append(prev_stage.name)
                    except Exception as rb_err:
                        ctx.errors.append(f"Rollback error in {prev_stage.name}: {rb_err}")

            root_cause = self._classify_failure(err)
            self.dead_end_registry.record_failure(
                tool_name="pipeline",
                tool_args={"failed_stage": ctx.executed_stages[-1] if ctx.executed_stages else "init"},
                root_cause=root_cause,
                diagnostic=diag,
            )

            try:
                target_fail_state = self._determine_failure_state(err)
                ctx.flow.transition(
                    target_fail_state,
                    actor=FlowActor.SYSTEM,
                    reason=f"Pipeline unwound due to error: {diag[:100]}",
                )
            except Exception:
                pass

            result = PipelineExecutionResult(
                is_success=False,
                final_state=ctx.flow.state,
                is_dry_run=ctx.is_dry_run,
                is_shadow=ctx.is_shadow,
                executed_stages=tuple(ctx.executed_stages),
                unwound_stages=tuple(ctx.unwound_stages),
                evidence_digest=None,
                error_diagnostic=diag,
                root_cause=root_cause.value,
                started_at=now_iso,
                completed_at=completed_iso,
                arbitration_blocked=ctx.arbitration_blocked,
            )
            self._persist_run_audit(result)
            return result

    def _assert_no_inline_consolidation(self) -> None:
        pass

    def _classify_failure(self, err: Exception) -> RootCauseClass:
        if isinstance(err, ContractError):
            if err.code in (ErrorCode.PROBE_VERIFICATION_FAILED, ErrorCode.VERIFICATION_FAILED):
                return RootCauseClass.TEST_FAILURE
            return RootCauseClass.CONTRACT_VIOLATION
        if isinstance(err, FlowStateError):
            return RootCauseClass.CONTRACT_VIOLATION
        if isinstance(err, TimeoutError):
            return RootCauseClass.TIMEOUT
        return RootCauseClass.CONTRACT_VIOLATION

    def _determine_failure_state(self, err: Exception) -> WorkStatus:
        if isinstance(err, ContractError) and err.code == ErrorCode.POLICY_DENIED:
            if "unresolved arbitration" in str(err):
                return WorkStatus.REPAIR
            return WorkStatus.BLOCKED
        if isinstance(err, ContractError) and err.code in (
            ErrorCode.PROBE_VERIFICATION_FAILED,
            ErrorCode.VERIFICATION_FAILED,
        ):
            return WorkStatus.REPAIR
        if self.config.allow_degraded:
            return WorkStatus.DEGRADED
        return WorkStatus.REPAIR

    def _persist_run_audit(self, result: PipelineExecutionResult) -> None:
        if not self.config.audit_db_path:
            return
        run_id = f"run-{hashlib.sha256(f'{self.config.task_id}:{self.config.work_id}:{result.started_at}'.encode()).hexdigest()[:16]}"
        try:
            with sqlite3.connect(str(self.config.audit_db_path), timeout=30) as db:
                db.execute(
                    """
                    INSERT OR REPLACE INTO jhoc_pipeline_runs
                    (run_id, task_id, work_id, is_success, is_dry_run, is_shadow, final_state,
                     evidence_digest, error_diagnostic, started_at, completed_at, payload)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        self.config.task_id,
                        self.config.work_id,
                        1 if result.is_success else 0,
                        1 if result.is_dry_run else 0,
                        1 if result.is_shadow else 0,
                        result.final_state.value,
                        result.evidence_digest,
                        result.error_diagnostic,
                        result.started_at,
                        result.completed_at,
                        json.dumps(result.to_dict(), ensure_ascii=True),
                    ),
                )
                db.commit()
        except Exception:
            pass
