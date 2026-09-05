from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from jhoc_co_review import JHOC_RULES, run_6_invariant_co_review
from jhoc_hook_gate import evaluate_payload
from jhoc_kaigong import run_kaigong


class Test36CoReviewAndInquiry(unittest.TestCase):
    def setUp(self) -> None:
        self._quota_patcher = mock.patch("jhoc.quota.antigravity_quota.get_antigravity_quota_live")
        self._mock_quota = self._quota_patcher.start()
        self._mock_quota.return_value = {
            "enabled": True,
            "account_email": "test_audit@gmail.com",
            "gemini_5h_pct": 100,
            "gemini_weekly_pct": 100,
            "gemini_5h_reset": "~4h",
            "gemini_weekly_reset": "~6d",
        }

    def tearDown(self) -> None:
        self._quota_patcher.stop()

    def test_jhoc_rules_completeness(self) -> None:
        self.assertEqual(len(JHOC_RULES), 6, "Must have exactly 6 constitutional rules")
        rule_ids = [r["id"] for r in JHOC_RULES]
        for i in range(1, 7):
            self.assertIn(f"RULE_{i}", rule_ids)

    def test_co_review_offline_generation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            pkg = run_6_invariant_co_review(
                task_id="test-task-101",
                title="Unit Test Invariant Verification",
                workspace=Path(td),
                offline=True,
            )
            self.assertEqual(pkg.overall_verdict, "OFFLINE_PASS")
            self.assertEqual(len(pkg.verdicts), 6)
            for v in pkg.verdicts:
                self.assertEqual(v.status, "PASS")
            self.assertTrue(bool(pkg.sha256))
            self.assertEqual(len(pkg.sha256), 64)

    def test_inquiry_gate_blocks_production_write_when_pending(self) -> None:
        state_file = ROOT / "memory" / "v3_task_state.json"
        orig_content = state_file.read_text(encoding="utf-8") if state_file.is_file() else None
        try:
            state_file.write_text(
                json.dumps(
                    {
                        "task_id": "test-pending-task",
                        "status": "ARMED",
                        "inquiry_status": "PENDING",
                    }
                ),
                encoding="utf-8",
            )
            payload = {
                "conversationId": "test-inquiry-conv",
                "toolCall": {
                    "name": "write_to_file",
                    "args": {
                        "TargetFile": str(ROOT / "desktop_client" / "src" / "components" / "NewFeature.tsx"),
                        "CodeContent": "export const x = 1;",
                    },
                },
            }
            res = evaluate_payload(payload)
            self.assertEqual(res["decision"], "deny")
            self.assertIn("[INQUIRY PENDING GATE]", res["reason"])
        finally:
            if orig_content is not None:
                state_file.write_text(orig_content, encoding="utf-8")
            elif state_file.is_file():
                state_file.unlink()

    def test_inquiry_gate_allows_artifacts_when_pending(self) -> None:
        state_file = ROOT / "memory" / "v3_task_state.json"
        orig_content = state_file.read_text(encoding="utf-8") if state_file.is_file() else None
        try:
            state_file.write_text(
                json.dumps(
                    {
                        "task_id": "test-pending-task",
                        "status": "ARMED",
                        "inquiry_status": "PENDING",
                    }
                ),
                encoding="utf-8",
            )
            allowed_files = (
                "implementation_plan.md",
                "walkthrough.md",
                "memory/notes.md",
                "docs/design.md",
                "tests/test_mock.py",
            )
            for subpath in allowed_files:
                payload = {
                    "conversationId": "test-inquiry-conv",
                    "toolCall": {
                        "name": "write_to_file",
                        "args": {
                            "TargetFile": str(ROOT / subpath),
                            "CodeContent": "Clean planning content",
                        },
                    },
                }
                res = evaluate_payload(payload)
                self.assertEqual(res["decision"], "allow", f"Failed to allow artifact: {subpath}")
        finally:
            if orig_content is not None:
                state_file.write_text(orig_content, encoding="utf-8")
            elif state_file.is_file():
                state_file.unlink()

    def test_inquiry_gate_allows_production_write_when_confirmed(self) -> None:
        state_file = ROOT / "memory" / "v3_task_state.json"
        orig_content = state_file.read_text(encoding="utf-8") if state_file.is_file() else None
        try:
            state_file.write_text(
                json.dumps(
                    {
                        "task_id": "test-confirmed-task",
                        "status": "ARMED",
                        "inquiry_status": "CONFIRMED",
                    }
                ),
                encoding="utf-8",
            )
            payload = {
                "conversationId": "test-inquiry-conv",
                "toolCall": {
                    "name": "write_to_file",
                    "args": {
                        "TargetFile": str(ROOT / "desktop_client" / "src" / "components" / "NewFeature.tsx"),
                        "CodeContent": "export const x = 1;",
                    },
                },
            }
            res = evaluate_payload(payload)
            self.assertEqual(res["decision"], "allow")
        finally:
            if orig_content is not None:
                state_file.write_text(orig_content, encoding="utf-8")
            elif state_file.is_file():
                state_file.unlink()

    def test_kaigong_inquiry_probe_state_recording(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_root = Path(td)
            (tmp_root / "AGENTS.md").write_text("# Test Agents", encoding="utf-8")
            (tmp_root / "memory").mkdir(parents=True, exist_ok=True)
            code_pending = run_kaigong("重大架构改造", workspace=tmp_root, inquiry=True, inquiry_confirmed=False)
            self.assertEqual(code_pending, 0)
            st_file = tmp_root / "memory" / "v3_task_state.json"
            self.assertTrue(st_file.is_file())
            data = json.loads(st_file.read_text(encoding="utf-8"))
            self.assertEqual(data.get("inquiry_status"), "PENDING")

            code_confirmed = run_kaigong(
                "重大架构改造",
                workspace=tmp_root,
                inquiry=True,
                inquiry_confirmed=True,
                force=True,
            )
            self.assertEqual(code_confirmed, 0)
            data_conf = json.loads(st_file.read_text(encoding="utf-8"))
            self.assertEqual(data_conf.get("inquiry_status"), "CONFIRMED")


if __name__ == "__main__":
    unittest.main()
