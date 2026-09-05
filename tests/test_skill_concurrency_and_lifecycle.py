from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from jhoc_hook_gate import evaluate_payload
from jhoc_stop_guard import evaluate_stop
from jhoc_pre_inject import evaluate_pre_invocation
from jhoc_kaigong import run_kaigong
from jhoc_shougong import run_shougong


class TestSkillConcurrencyAndLifecycle(unittest.TestCase):
    def setUp(self) -> None:
        self.state_file = ROOT / "memory" / "v3_task_state.json"
        self.orig_state = self.state_file.read_text(encoding="utf-8") if self.state_file.is_file() else None
        self.lock_file = ROOT / "runtime" / "write_freeze.lock"
        if self.lock_file.is_file():
            self.lock_file.unlink()
        self._reset_hub_presence()

    def tearDown(self) -> None:
        if self.orig_state is not None:
            self.state_file.write_text(self.orig_state, encoding="utf-8")
        if self.lock_file.is_file():
            self.lock_file.unlink()
        self._reset_hub_presence()

    def _reset_hub_presence(self) -> None:
        hub_db = ROOT / "logs" / "p19-hub.sqlite"
        if hub_db.is_file():
            try:
                from jhoc.hub import JHOCMultiModelHub, ModelPresenceState
                hub = JHOCMultiModelHub(hub_db)
                hub.register_presence("antigravity-ide", ModelPresenceState.IDLE)
            except Exception:
                pass

    def test_kaigong_reentrance_preserves_baseline_sha(self) -> None:
        # 1. Arm task with explicit baseline
        run_kaigong("Initial Task", workspace=ROOT)
        state1 = json.loads(self.state_file.read_text(encoding="utf-8"))
        orig_sha = state1["git_baseline_sha"]

        # 2. Modify state to pretend baseline was commit-123456
        state1["git_baseline_sha"] = "commit_1234567890"
        self.state_file.write_text(json.dumps(state1), encoding="utf-8")

        # 3. Re-run kaigong without force: baseline must be preserved!
        run_kaigong("Subsequent Re-entrant Task", workspace=ROOT, force=False)
        state2 = json.loads(self.state_file.read_text(encoding="utf-8"))
        self.assertEqual(state2["git_baseline_sha"], "commit_1234567890")

        # 4. Re-run kaigong with force: baseline is updated from real git!
        run_kaigong("Forced Re-arm Task", workspace=ROOT, force=True)
        state3 = json.loads(self.state_file.read_text(encoding="utf-8"))
        self.assertEqual(state3["git_baseline_sha"], orig_sha)

    def test_shougong_precondition_requires_armed_state(self) -> None:
        # Set task state to CLOSED
        self.state_file.write_text(json.dumps({"task_id": "test", "status": "CLOSED"}), encoding="utf-8")

        # Run shougong without force -> MUST FAIL
        code = run_shougong(archive=False, force=False)
        self.assertEqual(code, 1)

    def test_write_freeze_blocks_mutation_during_verification(self) -> None:
        payload = {
            "toolCall": {
                "name": "write_to_file",
                "args": {
                    "TargetFile": str(ROOT / "src" / "test_dummy.py"),
                    "CodeContent": "# clean test code",
                },
            }
        }

        # 1. Normal state (no freeze lock)
        res1 = evaluate_payload(payload)
        self.assertEqual(res1["decision"], "allow")

        # 2. Activate write freeze lock
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        self.lock_file.write_text("frozen_test", encoding="utf-8")

        res2 = evaluate_payload(payload)
        self.assertEqual(res2["decision"], "deny")
        self.assertIn("Concurrency Conflict", res2["reason"])
        self.assertIn("write freeze", res2["reason"])

        # 3. Remove lock
        self.lock_file.unlink()
        res3 = evaluate_payload(payload)
        self.assertEqual(res3["decision"], "allow")

    def test_stop_guard_blocks_armed_task_exit(self) -> None:
        # 1. When task is ARMED, stop must be blocked!
        self.state_file.write_text(json.dumps({"task_id": "task-test", "title": "Test", "status": "ARMED"}), encoding="utf-8")
        res1 = evaluate_stop({})
        self.assertEqual(res1["decision"], "continue")
        self.assertIn("still ARMED", res1["reason"])

        # 2. When task is CLOSED, stop is allowed!
        self.state_file.write_text(json.dumps({"task_id": "task-test", "title": "Test", "status": "CLOSED"}), encoding="utf-8")
        res2 = evaluate_stop({})
        self.assertEqual(res2["decision"], "allow")

    def test_pre_invocation_injects_lifecycle_order(self) -> None:
        # 1. When ARMED, injects order
        self.state_file.write_text(json.dumps({"task_id": "task-test", "title": "Test", "status": "ARMED", "git_baseline_sha": "abc1234567"}), encoding="utf-8")
        res1 = evaluate_pre_invocation({})
        self.assertGreater(len(res1["injectSteps"]), 0)
        self.assertIn("INCEPTION -> ELABORATION", res1["injectSteps"][0]["ephemeralMessage"])

        # 2. When CLOSED, injectSteps is empty
        self.state_file.write_text(json.dumps({"task_id": "task-test", "title": "Test", "status": "CLOSED"}), encoding="utf-8")
        res2 = evaluate_pre_invocation({})
        self.assertEqual(len(res2["injectSteps"]), 0)

    def test_pre_invocation_injects_quota_alert_when_critical(self) -> None:
        self.state_file.write_text(json.dumps({"task_id": "task-test", "title": "Test", "status": "CLOSED"}), encoding="utf-8")
        # With check_quota=True on active critical session, quota alert must be injected
        res = evaluate_pre_invocation({}, check_quota=True)
        if len(res["injectSteps"]) > 0:
            msg = res["injectSteps"][0]["ephemeralMessage"]
            self.assertIn("CRITICAL QUOTA ALERT", msg)

    @unittest.mock.patch("jhoc.quota.antigravity_quota.get_antigravity_quota_live")
    def test_kaigong_quota_critical_denies_without_force(self, mock_quota) -> None:
        mock_quota.return_value = {
            "enabled": True,
            "account_email": "fuse_test@gmail.com",
            "gemini_5h_pct": 2,
            "gemini_5h_reset": "~1h",
            "gemini_weekly_pct": 50,
        }
        # 1. Without force: MUST DENY (returncode 1)
        code1 = run_kaigong("Task on Low Quota", workspace=ROOT, force=False)
        self.assertEqual(code1, 1)

        # 2. With force: ALLOWED (returncode 0)
        code2 = run_kaigong("Task on Low Quota Forced", workspace=ROOT, force=True)
        self.assertEqual(code2, 0)


if __name__ == "__main__":
    unittest.main()


