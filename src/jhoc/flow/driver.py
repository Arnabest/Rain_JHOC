"""JHOC Skill Step Loop Driver.

Implements C1, C2, C4, C5, C8 from Phase 3 Architectural Review:
Integrates SkillStateMachine, DeadEndRegistry, SubagentSandbox, and ThinAdapter into a concrete
multi-step execution loop driver with pre-dispatch dead-end interception, CoT use-and-burn, and O(1) context bounding.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from jhoc.flow.re_trac import DeadEndRegistry, RootCauseClass
from jhoc.flow.skill_state import SkillStateMachine, StepState
from jhoc.runner.adapter import ThinAdapter


@dataclass(frozen=True, slots=True)
class DriverStepResult:
    is_success: bool
    step_number: int
    version: int
    diagnostic: str
    is_intercepted_dead_end: bool
    state: StepState


class SkillStepLoopDriver:
    """Orchestrates single and multi-step workflows with anti-loop interception and O(1) context."""

    def __init__(
        self,
        state_machine: SkillStateMachine,
        dead_end_registry: DeadEndRegistry | None = None,
        workspace_root: Path | str | None = None,
    ) -> None:
        self.state_machine = state_machine
        self.registry = dead_end_registry or DeadEndRegistry()
        self.root = Path(workspace_root).resolve() if workspace_root else Path.cwd()
        self.adapter = ThinAdapter(
            adapter_name="step_loop_driver",
            workspace_root=self.root,
            token_ceiling=2000,
        )

    def step(
        self,
        tool_name: str,
        tool_args: Mapping[str, Any] | None,
        runner_fn: Callable[..., Any],
        cot_scratch: str = "",
        state_delta: Mapping[str, Any] | None = None,
    ) -> DriverStepResult:
        """Executes a single step in the loop with pre-dispatch dead-end check and CoT burn."""
        # 1. Pre-dispatch Anti-Looping Interceptor (C4)
        is_allowed, check_reason = self.registry.check_action(tool_name, tool_args)
        if not is_allowed:
            dummy_state = StepState(
                step_number=self.state_machine.current_step,
                version=self.state_machine.version,
                state_variables=self.state_machine.state_variables,
                latest_observation=f"[INTERCEPTED] {check_reason}",
                promoted_at="",
            )
            return DriverStepResult(
                is_success=False,
                step_number=self.state_machine.current_step,
                version=self.state_machine.version,
                diagnostic=check_reason,
                is_intercepted_dead_end=True,
                state=dummy_state,
            )

        # 2. Crash-isolated execution via ThinAdapter (C1, C4)
        def run_action() -> Any:
            if tool_args:
                try:
                    return runner_fn(**tool_args)
                except TypeError:
                    try:
                        return runner_fn(tool_args)
                    except TypeError:
                        pass
            return runner_fn()

        adapter_res = self.adapter.execute(run_action)

        if not adapter_res.is_success:
            # Action failed -> Record in DeadEndRegistry
            rc_class = RootCauseClass.CONTRACT_VIOLATION if "Contract" in adapter_res.diagnostic else RootCauseClass.TEST_FAILURE
            self.registry.record_failure(
                tool_name=tool_name,
                tool_args=tool_args,
                root_cause=rc_class,
                diagnostic=adapter_res.diagnostic,
            )
            # Advance state with failure observation and burn CoT
            new_state = self.state_machine.advance(
                state_delta={"last_error": adapter_res.diagnostic[:100]},
                observation=f"[FAILURE] {adapter_res.diagnostic}",
                cot_scratch=cot_scratch,
            )
            return DriverStepResult(
                is_success=False,
                step_number=new_state.step_number,
                version=new_state.version,
                diagnostic=adapter_res.diagnostic,
                is_intercepted_dead_end=False,
                state=new_state,
            )

        # 3. Execution succeeded -> reset transient failures, promote verified state delta & burn CoT
        self.registry.reset_transient(tool_name, tool_args)
        delta = dict(state_delta or {})
        delta["last_success_tool"] = tool_name
        obs_str = str(adapter_res.data)[:500]

        new_state = self.state_machine.advance(
            state_delta=delta,
            observation=f"[SUCCESS] {obs_str}",
            cot_scratch=cot_scratch,
        )

        return DriverStepResult(
            is_success=True,
            step_number=new_state.step_number,
            version=new_state.version,
            diagnostic="Step executed and promoted successfully.",
            is_intercepted_dead_end=False,
            state=new_state,
        )
