"""Integration pipeline test verifying end-to-end reachability of Phase 2 modules:
TieredGovernanceInjector -> ThinAdapter -> GraderSanityGate -> MemoryDistiller -> SQLiteMemoryStore.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jhoc.context.tiered_injector import TieredGovernanceInjector, is_high_risk_asset
from jhoc.runner.adapter import ThinAdapter
from jhoc.guard.grader_gate import GraderSanityGate
from jhoc.guard.policy import Decision
from jhoc.memory_store.distiller import MemoryDistiller
from jhoc.memory_store.sqlite import SQLiteMemoryStore
from jhoc.memory_store.store import MemoryType


class TestPhase2IntegrationPipeline(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="jhoc_phase2_pipeline_"))

    def tearDown(self) -> None:
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_end_to_end_governance_execution_pipeline(self) -> None:
        """Verify seamless pipeline from tiered context injection to adapter execution,
        gate evaluation, memory distillation, and SQLite WAL persistence.
        """
        # 1. Tiered Governance Context Assembly
        injector = TieredGovernanceInjector(self.temp_dir)
        static_head = injector.render_layer_0_base()
        self.assertTrue(static_head.isascii())
        self.assertIn("Rule 7: Zero-Emoji Discipline", static_head)

        target_file = "AGENTS.md"
        tool_call = "write_to_file"
        self.assertTrue(is_high_risk_asset(target_file))

        tail_overlay = injector.render_tail_overlay(tool_name=tool_call, target_path=target_file)
        self.assertIn("LAYER 1 ACTION", tail_overlay)
        self.assertIn("LAYER 2 CORE ASSET", tail_overlay)

        # Full prompt assembly preserves prefix caching (head immutable, tail dynamic)
        simulated_prompt = f"{static_head}\n\n[USER TASK: Update constitutional governance]\n\n{tail_overlay}"
        self.assertTrue(simulated_prompt.startswith(static_head))

        # 2. Thin Adapter Execution with input validation, crash isolation & CJK truncation
        in_schema = {
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "diff": {"type": "string"},
            },
            "required": ["action", "diff"],
        }
        out_schema = {
            "type": "object",
            "properties": {
                "applied": {"type": "boolean"},
                "message": {"type": "string"},
                "verbose_log": {"type": "string"},
            },
            "required": ["applied", "message"],
        }
        adapter = ThinAdapter(
            adapter_name="governance_patcher",
            workspace_root=self.temp_dir,
            input_schema=in_schema,
            output_schema=out_schema,
            token_ceiling=100,
        )

        input_payload = {
            "action": "apply_patch",
            "diff": "--- a/AGENTS.md\n+++ b/AGENTS.md\n+ Rule 7: Zero Emoji Strict",
        }

        # Simulated runner function returning large output with CJK text
        def simulated_patch_tool(input_payload: dict | None = None, **kwargs: Any) -> dict:
            return {
                "applied": True,
                "message": "Patch applied successfully: 治理精简与反死锁门禁生效。" * 10,
                "verbose_log": "DEBUG TRACE: " + ("step_trace_log " * 100),
            }

        adapter_res = adapter.execute(simulated_patch_tool, input_payload=input_payload)
        self.assertTrue(adapter_res.is_success)
        self.assertTrue(adapter_res.is_truncated)
        self.assertIsNotNone(adapter_res.storage_ref)
        self.assertIsNotNone(adapter_res.full_sha256)

        # 3. Grader Gate Sanity Evaluation & Anti-Lockout Verification
        gate = GraderSanityGate(self.temp_dir, shadow_mode=False)

        # Negative control self-test on simulated rule
        def rule_no_forbidden_keywords(item: dict) -> bool:
            msg = str(item.get("message", ""))
            return "UNAPPROVED_OVERRIDE" not in msg

        gate_healthy, _ = gate.run_negative_controls_self_test(
            rule_evaluator=rule_no_forbidden_keywords,
            known_valid_samples=[{"message": "clean action"}],
            known_invalid_samples=[{"message": "action UNAPPROVED_OVERRIDE forbidden"}],
        )
        self.assertTrue(gate_healthy)

        dec, reason = gate.evaluate_with_shadow(
            rule_name="constitutional_asset_gate",
            violation_detected=False,
            violation_detail="",
            context={"tool": tool_call, "target": target_file},
        )
        self.assertEqual(dec, Decision.ALLOW)

        # 4. Memory Distiller Normalization & Trace Segregation
        distiller = MemoryDistiller(self.temp_dir)
        raw_memory_content = {
            "rule": "Constitutional asset patch verified with zero-emoji discipline",
            "symptom": "Dynamic tiered injection preserves prompt cache prefix",
            "prevention": "Layer 0 immutable head, Layer 1/2 ephemeral tail",
            "raw_debug_trace": "EXTENSIVE PIPELINE TRACE " * 50,
        }

        distilled = distiller.distill(
            content=raw_memory_content,
            memory_type=MemoryType.EXPERIENCE,
            source_ref="tests/test_phase2_integration_pipeline.py",
        )
        rec = distilled.record

        # Assert golden invariant character bounds
        serialized_content = json.dumps(rec.content, ensure_ascii=False)
        self.assertLessEqual(len(serialized_content), 620)
        self.assertIn("evidence_sha256", rec.content)
        self.assertIn("sidecar_trace", rec.content)

        # Verify raw trace was diverted to out-of-band sidecar
        self.assertIsNotNone(distilled.sidecar_trace_path)
        sidecar_full = self.temp_dir / distilled.sidecar_trace_path  # type: ignore[operator]
        self.assertTrue(sidecar_full.is_file())

        # 5. SQLite WAL Persistence & Recovery
        sqlite_db = self.temp_dir / "memory_integration.db"
        store = SQLiteMemoryStore(str(sqlite_db))
        written_rec = store.write(rec, approved=True)
        self.assertEqual(written_rec.record_id, rec.record_id)

        # Query back and verify integrity
        fetched = store.get(rec.record_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.content["evidence_sha256"], rec.content["evidence_sha256"])  # type: ignore[union-attr]

        # Hot backup to secondary database
        backup_db = self.temp_dir / "memory_backup.db"
        store.backup_to(str(backup_db))
        self.assertTrue(backup_db.is_file())
        store.close()

        # Reopen backup and assert records intact
        backup_store = SQLiteMemoryStore(str(backup_db))
        records = backup_store.records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].record_id, rec.record_id)
        backup_store.close()


if __name__ == "__main__":
    unittest.main()
