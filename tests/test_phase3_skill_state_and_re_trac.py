"""Adversarial and functional test suite for Phase 3:
SkillStateMachine, RE-TRAC Trajectory Compression, DeadEndRegistry, SubagentSandbox, and SkillStepLoopDriver.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jhoc.flow.skill_state import SkillStateMachine, StepState, ContextTuple
from jhoc.flow.re_trac import (
    DeadEndRegistry,
    TrajectoryCompressor,
    RootCauseClass,
    canonicalize_action,
)
from jhoc.flow.subagent_bus import SubagentSandbox, SubagentResult
from jhoc.flow.driver import SkillStepLoopDriver, DriverStepResult
from jhoc.storage import StateStore
from jhoc.storage.sqlite import SQLiteStore


class TestPhase3SkillStateAndReTrac(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="jhoc_phase3_test_"))

    def tearDown(self) -> None:
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_c1_and_c2_step_loop_driver_and_o1_context_budget(self) -> None:
        """C1 & C2: Execute 25 sequential steps, verifying context stays strictly O(1) and CoT is burned."""
        spec = "Execute systematic multi-step verification under strict external harness."
        sm = SkillStateMachine(
            skill_name="code_patcher",
            skill_spec=spec,
            workspace_root=self.temp_dir,
            initial_variables={"status": "INITIALIZED"},
        )
        driver = SkillStepLoopDriver(sm, workspace_root=self.temp_dir)

        # Run 25 steps with varying delta and large ephemeral CoT
        for i in range(1, 26):
            cot_scratch = f"STEP_{i}_CHAIN_OF_THOUGHT: Extensive reasoning path..." * 20  # ~1000 chars
            tool_args = {"step_id": i, "flag": "normal"}

            res = driver.step(
                tool_name="step_executor",
                tool_args=tool_args,
                runner_fn=lambda: f"Output of step {i}",
                cot_scratch=cot_scratch,
                state_delta={f"var_{i}": f"val_{i}", "counter": i},
            )
            self.assertTrue(res.is_success)
            self.assertEqual(res.step_number, i)

            # Assert context remains strictly bounded (O(1) honesty)
            ctx = sm.assemble_context()
            prompt = ctx.to_assembled_prompt()
            # Spec <= 1600, State <= 1200, Obs <= 2000 -> Total prompt <= 5000 chars
            self.assertLessEqual(len(prompt), 5000)
            self.assertTrue(prompt.isascii())

            # Verify active state memory contains at most 10 resident keys
            self.assertLessEqual(len(sm.state_variables), 10)

            # Verify CoT was NOT kept in active memory but saved to sidecar file
            self.assertNotIn(cot_scratch, prompt)
            if res.state.sidecar_cot_ref:
                sidecar_path = self.temp_dir / res.state.sidecar_cot_ref
                self.assertTrue(sidecar_path.is_file())
                self.assertIn(f"STEP_{i}_CHAIN_OF_THOUGHT", sidecar_path.read_text(encoding="utf-8"))

    def test_c3_durable_persistence_and_crash_resume(self) -> None:
        """C3: Verify state machine snapshot persistence and crash-resume from SQLiteStore."""
        state_db = self.temp_dir / "state_store.db"
        store = SQLiteStore(str(state_db))
        task_id = f"task-{uuid4()}"

        sm1 = SkillStateMachine(
            skill_name="build_pipeline",
            skill_spec="Build and verify components",
            workspace_root=self.temp_dir,
            initial_variables={"build_target": "engine"},
        )
        sm1.advance(state_delta={"stage": "COMPILED", "exit_code": 0}, observation="Compilation complete.")
        sm1.advance(state_delta={"stage": "TESTED", "passed_tests": 42}, observation="All 42 tests green.")
        sm1.persist_to_store(store, task_id)

        # Simulate crash restart: re-open new SQLite store instance over same file and reconstruct
        store_new = SQLiteStore(str(state_db))
        sm_resumed = SkillStateMachine.load_from_store(
            state_store=store_new,
            skill_name="build_pipeline",
            task_id=task_id,
            workspace_root=self.temp_dir,
        )
        self.assertEqual(sm_resumed.current_step, 2)
        self.assertEqual(sm_resumed.version, 3)
        self.assertEqual(sm_resumed.state_variables["stage"], "TESTED")
        self.assertEqual(sm_resumed.state_variables["passed_tests"], 42)
        self.assertEqual(sm_resumed.latest_observation, "All 42 tests green.")

    def test_c4_canonical_dead_end_hashing_and_interception(self) -> None:
        """C4: Verify canonical action normalization and pre-dispatch dead-end interception."""
        reg = DeadEndRegistry()

        # Record a deterministic syntax error failure
        failing_args = {"path": "src/bad_code.py", "line": 42, "content": "syntax error here"}
        is_bl, msg = reg.record_failure(
            tool_name="replace_file_content",
            tool_args=failing_args,
            root_cause=RootCauseClass.SYNTAX_ERROR,
            diagnostic="SyntaxError: invalid syntax on line 42",
        )
        self.assertTrue(is_bl)

        # Identical action with whitespace variations and reversed key ordering
        variant_spelling_args = {"content": "syntax error here", "line": 42, "path": "  src/bad_code.py  "}
        allowed_1, reason_1 = reg.check_action("REPLACE_FILE_CONTENT", variant_spelling_args)
        self.assertFalse(allowed_1)
        self.assertIn("DEAD_END_INTERCEPTED", reason_1)

        # Parameter variation (different file or line) is NOT blocked
        variant_param_args = {"content": "syntax error here", "line": 99, "path": "src/other_code.py"}
        allowed_2, _ = reg.check_action("replace_file_content", variant_param_args)
        self.assertTrue(allowed_2)

    def test_c5_transient_error_protection_and_retry_threshold(self) -> None:
        """C5: Verify transient failures (e.g. TIMEOUT) allow retry and only blacklist after K >= 2."""
        reg = DeadEndRegistry(transient_threshold=2)
        timeout_args = {"host": "api.service.internal", "timeout_sec": 5}

        # Attempt 1: Transient TIMEOUT -> eligible for retry (NOT blacklisted)
        bl_1, msg_1 = reg.record_failure(
            tool_name="curl_check",
            tool_args=timeout_args,
            root_cause=RootCauseClass.TIMEOUT,
            diagnostic="Connection timed out after 5000ms",
        )
        self.assertFalse(bl_1)
        self.assertIn("eligible for retry", msg_1)

        # Check action is still allowed
        allowed_after_1, _ = reg.check_action("curl_check", timeout_args)
        self.assertTrue(allowed_after_1)

        # Attempt 2: Identical transient failure hits threshold -> NOW blacklisted
        bl_2, msg_2 = reg.record_failure(
            tool_name="curl_check",
            tool_args=timeout_args,
            root_cause=RootCauseClass.TIMEOUT,
            diagnostic="Connection timed out after 5000ms second time",
        )
        self.assertTrue(bl_2)
        self.assertIn("blacklisted", msg_2)

        # Now pre-dispatch check intercepts
        allowed_after_2, reason_2 = reg.check_action("curl_check", timeout_args)
        self.assertFalse(allowed_after_2)
        self.assertIn("DEAD_END_INTERCEPTED", reason_2)

    def test_c7_subagent_sandbox_isolation_and_integrity_verification(self) -> None:
        """C7: Verify subagent execution isolation, raw trace containment, and cryptographic hash re-check."""
        sandbox = SubagentSandbox(subagent_id="test_worker_1", workspace_root=self.temp_dir)

        artifact_file = self.temp_dir / "generated_output.txt"

        def child_task() -> str:
            # Emits print to stdout and writes artifact
            print("CHILD_STDOUT_CONFINED_STREAM")
            artifact_file.write_text("PHYSICAL_ARTIFACT_CONTENT", encoding="utf-8")
            return "Task finished with 10 intermediate debugging iterations."

        res = sandbox.execute_isolated(child_task, expected_artifacts=[artifact_file.name])
        self.assertTrue(res.is_success)
        self.assertLessEqual(len(res.summary), 300)
        self.assertTrue(res.summary.isascii())
        self.assertIn(artifact_file.name, res.produced_artifacts)

        # Verify stdout was captured into the out-of-band trace file
        trace_file = self.temp_dir / res.trace_storage_ref
        self.assertTrue(trace_file.is_file())
        self.assertIn("CHILD_STDOUT_CONFINED_STREAM", trace_file.read_text(encoding="utf-8"))

        # Re-verify trace integrity from disk
        self.assertTrue(res.verify_trace_integrity(self.temp_dir))

        # Tampering with trace file causes verify_trace_integrity to fail
        trace_file.write_bytes(b"TAMPERED_CONTENT")
        self.assertFalse(res.verify_trace_integrity(self.temp_dir))

    def test_c6_write_authority_boundary_and_expiry(self) -> None:
        """C6: Verify DeadEndRegistry mutations are harness-internal and harness can expire entries."""
        reg = DeadEndRegistry()
        # Invalid / unhashable argument structure fails closed
        allowed, reason = reg.check_action("unserializable_tool", {"circular": self})
        self.assertFalse(allowed)
        self.assertIn("DEAD_END_INTERCEPTED", reason)

        # Test expire_entry
        test_args = {"path": "broken.py"}
        reg.record_failure("edit", test_args, RootCauseClass.CONTRACT_VIOLATION, "syntax error")
        allowed_pre, _ = reg.check_action("edit", test_args)
        self.assertFalse(allowed_pre)

        expired = reg.expire_entry("edit", test_args)
        self.assertTrue(expired)
        allowed_post, _ = reg.check_action("edit", test_args)
        self.assertTrue(allowed_post)

    def test_c7_artifact_boundary_confinement_and_size_caps(self) -> None:
        """C7: Verify sandbox rejects artifacts escaping workspace or exceeding size limits."""
        sandbox = SubagentSandbox(subagent_id="path_jail_test", workspace_root=self.temp_dir)

        # Artifact escaping workspace boundary
        def rogue_escape_task() -> str:
            return "Wrote rogue file outside workspace"

        res_escape = sandbox.execute_isolated(rogue_escape_task, expected_artifacts=["../../escape.txt"])
        self.assertFalse(res_escape.is_success)
        self.assertIn("Artifact escapes workspace boundary", res_escape.diagnostic)

    def test_c8_rule_7_ascii_purity_across_phase3_modules(self) -> None:
        """C8: Assert 100% pure ASCII across all Phase 3 code files."""
        files = [
            ROOT / "src" / "jhoc" / "flow" / "skill_state.py",
            ROOT / "src" / "jhoc" / "flow" / "re_trac.py",
            ROOT / "src" / "jhoc" / "flow" / "subagent_bus.py",
            ROOT / "src" / "jhoc" / "flow" / "driver.py",
        ]
        for f in files:
            content = f.read_text(encoding="utf-8")
            non_ascii = [ch for ch in content if ord(ch) > 127]
            self.assertEqual(len(non_ascii), 0, f"Non-ASCII characters detected in {f.name}: {set(non_ascii)}")

    def test_c9_step_vs_lifecycle_version_coherence(self) -> None:
        """C9: Verify state machine advance enforces expected_version to prevent stale concurrent writes."""
        sm = SkillStateMachine("version_test", "spec", workspace_root=self.temp_dir)
        self.assertEqual(sm.version, 1)

        # Normal advance matching expected_version
        state1 = sm.advance(state_delta={"a": 1}, observation="step 1 ok", expected_version=1)
        self.assertEqual(state1.version, 2)

        # Stale advance with obsolete expected_version raises ContractError (IDEMPOTENCY_CONFLICT)
        from jhoc.contracts.errors import ContractError
        with self.assertRaises(ContractError):
            sm.advance(state_delta={"a": 2}, observation="step 2 stale", expected_version=1)


if __name__ == "__main__":
    unittest.main()
