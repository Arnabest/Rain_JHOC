"""Unit tests for Phase 2: Governance Slimming, Tiered Injector, Memory Distiller, Grader Gate & Thin Adapter."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jhoc.context.tiered_injector import (
    TieredGovernanceInjector,
    is_high_risk_asset,
    GovernanceLayer,
)
from jhoc.memory_store.distiller import (
    MemoryDistiller,
    MAX_INVARIANT_CHARS,
    MAX_TOTAL_RECORD_CHARS,
)
from jhoc.memory_store.store import MemoryType
from jhoc.guard.grader_gate import GraderSanityGate
from jhoc.guard.policy import Decision
from jhoc.runner.adapter import ThinAdapter, AdapterResult
from jhoc.contracts.errors import ContractError


class TestPhase2GovernanceSlimmingAndGraderGate(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="jhoc_phase2_test_"))

    def tearDown(self) -> None:
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_tiered_injector_layer_rendering_and_budget(self) -> None:
        """Verify Layer 0/1/2 rendering, high-risk asset triggers, and byte determinism."""
        injector = TieredGovernanceInjector(self.temp_dir)

        # Layer 0 Base
        l0 = injector.render_layer_0_base()
        self.assertTrue(l0.isascii())
        self.assertLess(injector.estimate_token_count(l0), 200)
        self.assertIn("Rule 7: Zero-Emoji Discipline", l0)

        # Layer 1 Action
        l1 = injector.render_layer_1_action("write_to_file")
        self.assertTrue(l1.isascii())
        self.assertLess(injector.estimate_token_count(l1), 350)
        self.assertIn("Atomic Persistence", l1)

        # Layer 2 Asset
        self.assertTrue(is_high_risk_asset("AGENTS.md"))
        self.assertTrue(is_high_risk_asset(".agents/rules/local-model-principles.md"))
        self.assertFalse(is_high_risk_asset("src/my_app/main.py"))

        l2 = injector.render_layer_2_asset("AGENTS.md")
        self.assertTrue(l2.isascii())
        self.assertLess(injector.estimate_token_count(l2), 600)
        self.assertIn("CRITICAL CONSTITUTIONAL ASSET", l2)

        # Tail overlay assembly & byte determinism
        tail1 = injector.render_tail_overlay("write_to_file", "AGENTS.md")
        tail2 = injector.render_tail_overlay("write_to_file", "AGENTS.md")
        self.assertEqual(tail1, tail2)  # Byte-level determinism
        self.assertIn("LAYER 1 ACTION", tail1)
        self.assertIn("LAYER 2 CORE ASSET", tail1)

        # Read-only non-asset produces empty tail overlay (zero tax!)
        tail_empty = injector.render_tail_overlay("view_file", "README.md")
        self.assertEqual(tail_empty, "")

    def test_memory_distiller_character_normalization_and_trace_diversion(self) -> None:
        """Verify that memory records are bounded to 500 chars and bulky traces are diverted."""
        distiller = MemoryDistiller(self.temp_dir)

        # 1. Bulky trace payload
        huge_trace = "turn_" * 500  # 2500 chars
        content = {
            "rule": "Avoid stdin deadlock by starting drain threads first",
            "symptom": "Parent hangs waiting for child",
            "prevention": "Start stdout/stderr drain threads before writing to stdin",
            "raw_transcript_trace": huge_trace,
        }

        distilled = distiller.distill(
            content=content,
            memory_type=MemoryType.EXPERIENCE,
            source_ref="tests/test_run.py",
        )

        rec = distilled.record
        # Verify content was bounded
        serialized = json.dumps(rec.content, ensure_ascii=False)
        self.assertLessEqual(len(serialized), MAX_TOTAL_RECORD_CHARS)
        self.assertIn("evidence_sha256", rec.content)
        self.assertIn("sidecar_trace", rec.content)

        # Verify sidecar file exists and contains the raw unstripped trace
        self.assertIsNotNone(distilled.sidecar_trace_path)
        sidecar_full_path = self.temp_dir / distilled.sidecar_trace_path  # type: ignore[operator]
        self.assertTrue(sidecar_full_path.is_file())
        sidecar_data = json.loads(sidecar_full_path.read_text(encoding="utf-8"))
        self.assertIn(huge_trace, sidecar_data["raw_content"]["raw_transcript_trace"])

    def test_grader_sanity_gate_shadow_mode_and_override(self) -> None:
        """Verify shadow audit mode and cryptographic emergency override."""
        # 1. Shadow mode active
        gate_shadow = GraderSanityGate(self.temp_dir, shadow_mode=True)
        dec, msg = gate_shadow.evaluate_with_shadow("test_rule", True, "Test violation")
        self.assertEqual(dec, Decision.ALLOW)
        self.assertIn("[SHADOW_AUDIT_LOGGED]", msg)
        self.assertTrue(gate_shadow.shadow_log.is_file())

        # 2. Shadow mode inactive (strict enforcement)
        gate_strict = GraderSanityGate(self.temp_dir, shadow_mode=False)
        dec_strict, msg_strict = gate_strict.evaluate_with_shadow("test_rule", True, "Test violation")
        self.assertEqual(dec_strict, Decision.DENY)

        # 3. Emergency Override Token
        secret = "super_secure_operator_secret_123456"
        task_id = "task-test-001"
        scope = "rules/emergency_fix"
        token = GraderSanityGate.generate_emergency_override_token(secret, task_id, scope, ttl_seconds=60)

        # Validate token
        ok, reason = gate_strict.verify_and_consume_override_token(token, secret, task_id, scope)
        self.assertTrue(ok)
        self.assertIn("successfully verified", reason)
        self.assertTrue(gate_strict.override_log.is_file())

        # Anti-Replay: same token must fail second time
        ok_replay, reason_replay = gate_strict.verify_and_consume_override_token(token, secret, task_id, scope)
        self.assertFalse(ok_replay)
        self.assertIn("Replay detected", reason_replay)

        # Wrong task_id or wrong secret fails
        ok_bad_task, _ = gate_strict.verify_and_consume_override_token(token, secret, "wrong_task", scope)
        self.assertFalse(ok_bad_task)

    def test_grader_negative_controls_self_test(self) -> None:
        """Verify rule evaluator self-testing with positive and negative controls."""
        gate = GraderSanityGate(self.temp_dir)

        def good_evaluator(val: str) -> bool:
            return not val.startswith("BAD_")

        ok, msg = gate.run_negative_controls_self_test(
            good_evaluator,
            known_valid_samples=["GOOD_1", "NORMAL", "VALID"],
            known_invalid_samples=["BAD_INJECTION", "BAD_COMMAND"],
        )
        self.assertTrue(ok)

        # Broken evaluator that falsely allows invalid input (leak)
        def leaky_evaluator(val: str) -> bool:
            return True

        ok_leaky, msg_leaky = gate.run_negative_controls_self_test(
            leaky_evaluator,
            known_valid_samples=["GOOD_1"],
            known_invalid_samples=["BAD_1"],
        )
        self.assertFalse(ok_leaky)
        self.assertIn("False Negative (leak)", msg_leaky)

    def test_thin_adapter_truncation_schema_and_isolation(self) -> None:
        """Verify ThinAdapter crash isolation, CJK truncation, and pre-truncation SHA-256."""
        out_schema = {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["title", "content"],
        }
        adapter = ThinAdapter("test_tool", workspace_root=self.temp_dir, output_schema=out_schema, token_ceiling=50)

        # 1. Output exceeds token ceiling (CJK text)
        long_cjk = "这是一段很长的中文测试内容，用于验证分词与硬截断能力。" * 20
        payload = {"title": "Test CJK", "content": long_cjk}

        res = adapter.execute(lambda: payload)
        self.assertTrue(res.is_success)
        self.assertTrue(res.is_truncated)
        self.assertIsNotNone(res.storage_ref)

        # Verify pre-truncation SHA-256 matches full raw bytes
        raw_full_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        expected_sha256 = hashlib.sha256(raw_full_bytes).hexdigest()
        self.assertEqual(res.full_sha256, expected_sha256)

        # Verify storage ref exists and contains the full un-truncated bytes
        blob_file = self.temp_dir / res.storage_ref  # type: ignore[operator]
        self.assertTrue(blob_file.is_file())
        self.assertEqual(blob_file.read_bytes(), raw_full_bytes)

        # 2. Domain exception isolation (process crashes, but harness remains intact)
        def failing_action() -> None:
            raise RuntimeError("Subprocess connection failed abruptly")

        res_fail = adapter.execute(failing_action)
        self.assertFalse(res_fail.is_success)
        self.assertEqual(res_fail.status_code, "EXECUTION_ERROR")
        self.assertIn("Subprocess connection failed abruptly", res_fail.diagnostic)

        # 3. Input schema validation inside execute()
        in_schema = {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        }
        adapter_with_in = ThinAdapter("test_in", workspace_root=self.temp_dir, input_schema=in_schema)
        with self.assertRaises(ContractError) as cm:
            adapter_with_in.execute(lambda payload: payload, input_payload={"wrong_field": 123})
        self.assertIn("input schema validation failed", str(cm.exception))

        # 4. Non-JSON serializable output isolation when no schema specified (does not crash harness)
        adapter_no_schema = ThinAdapter("test_no_schema", workspace_root=self.temp_dir)
        res_unserializable = adapter_no_schema.execute(lambda: {"bytes": b"\x00\x01\x02"})
        self.assertFalse(res_unserializable.is_success)
        self.assertEqual(res_unserializable.status_code, "SERIALIZATION_ERROR")
        self.assertIn("payload serialization failed", res_unserializable.diagnostic)

    def test_grader_cross_instance_replay_and_expiry(self) -> None:
        """Verify cross-instance nonce persistence and expired token rejection."""
        secret = "long_enough_secret_key_for_hmac_123"
        task_id = "task-cross-instance"
        scope = "test/scope"

        # 1. Expired token rejection
        expired_token = f"override:{task_id}:{int(time.time()) - 10}:nonce123:fakesig"
        gate_1 = GraderSanityGate(self.temp_dir)
        ok_exp, msg_exp = gate_1.verify_and_consume_override_token(expired_token, secret, task_id, scope)
        self.assertFalse(ok_exp)
        self.assertIn("expired", msg_exp)

        # 2. Cross-instance nonce durability
        valid_token = GraderSanityGate.generate_emergency_override_token(secret, task_id, scope, ttl_seconds=300)
        ok1, _ = gate_1.verify_and_consume_override_token(valid_token, secret, task_id, scope)
        self.assertTrue(ok1)

        # Separate gate instance pointing to same workspace
        gate_2 = GraderSanityGate(self.temp_dir)
        ok2, msg2 = gate_2.verify_and_consume_override_token(valid_token, secret, task_id, scope)
        self.assertFalse(ok2)
        self.assertIn("Replay detected", msg2)

        # 3. Corrupted ledger fails closed
        corrupt_log = self.temp_dir / "logs" / "audit" / "gate_overrides.jsonl"
        corrupt_log.write_text("CORRUPTED_RAW_JSON_LINE_THAT_CANNOT_PARSE\n", encoding="utf-8")
        gate_corrupt = GraderSanityGate(self.temp_dir)
        fresh_token = GraderSanityGate.generate_emergency_override_token(secret, task_id, scope, ttl_seconds=300)
        ok_corrupt, msg_corrupt = gate_corrupt.verify_and_consume_override_token(fresh_token, secret, task_id, scope)
        self.assertFalse(ok_corrupt)
        self.assertIn("corrupted or unreadable", msg_corrupt)

    def test_memory_distiller_missing_source_ref_and_bounds(self) -> None:
        """Verify missing source_ref raises ContractError and bounds are strictly enforced."""
        distiller = MemoryDistiller(self.temp_dir)
        with self.assertRaises(ContractError):
            distiller.distill(content={"data": 1}, memory_type=MemoryType.TASK, source_ref="")

        with self.assertRaises(ContractError):
            distiller.distill(content={"data": 1}, memory_type=MemoryType.TASK, source_ref="   ")

        # Huge invariant content body condensation
        huge_payload = {"rule": "x" * 1000, "symptom": "y" * 1000, "prevention": "z" * 1000}
        distilled = distiller.distill(content=huge_payload, memory_type=MemoryType.EXPERIENCE, source_ref="ref/001")
        serialized = json.dumps(distilled.record.content, ensure_ascii=False)
        self.assertLessEqual(len(serialized), 620)

    def test_tiered_injector_tool_casing_and_mutation_detection(self) -> None:
        """Verify tool casing normalization and mutating tool keyword detection."""
        injector = TieredGovernanceInjector(self.temp_dir)
        tail_upper = injector.render_tail_overlay("WRITE_TO_FILE", "README.md")
        self.assertIn("LAYER 1 ACTION", tail_upper)

        tail_whitespace = injector.render_tail_overlay("  edit  ", "README.md")
        self.assertIn("LAYER 1 ACTION", tail_whitespace)

        tail_custom = injector.render_tail_overlay("custom_code_patcher", "README.md")
        self.assertIn("LAYER 1 ACTION", tail_custom)


if __name__ == "__main__":
    unittest.main()
