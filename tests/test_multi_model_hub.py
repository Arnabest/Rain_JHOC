from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from jhoc.hub import (
    JHOCMultiModelHub,
    LeaseStatus,
    MessageStatus,
    ModelPresenceState,
)
from jhoc_hook_gate import evaluate_payload


class TestMultiModelHub(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test-hub.sqlite"
        self.hub = JHOCMultiModelHub(self.db_path)

    def tearDown(self) -> None:
        self.hub.close()
        self.temp_dir.cleanup()

    def test_presence_registration_and_heartbeat(self) -> None:
        p1 = self.hub.register_presence("claude-code", ModelPresenceState.PLANNING, task_id="task-101", pid=12345)
        p2 = self.hub.register_presence("codex-cli", ModelPresenceState.CODING, task_id="task-102", pid=12346)

        active = self.hub.get_active_models(stale_threshold_sec=60)
        self.assertEqual(len(active), 2)
        model_ids = {m.model_id for m in active}
        self.assertEqual(model_ids, {"claude-code", "codex-cli"})

        # Heartbeat check
        ok = self.hub.heartbeat("claude-code")
        self.assertTrue(ok)

    def test_file_lease_mutex_prevents_concurrent_overwrite(self) -> None:
        target_file = ROOT / "src" / "jhoc" / "supervisor.py"

        # 1. Claude acquires lease
        ok1, msg1, lease1 = self.hub.acquire_file_lease("claude-code", target_file, task_id="task-101", ttl_seconds=60)
        self.assertTrue(ok1)
        self.assertIsNotNone(lease1)

        # 2. Antigravity tries to acquire the same file -> MUST FAIL
        ok2, msg2, lease2 = self.hub.acquire_file_lease("antigravity-ide", target_file, task_id="task-202", ttl_seconds=60)
        self.assertFalse(ok2)
        self.assertIn("locked by model 'claude-code'", msg2)

        # 3. Check lease via check_file_lease
        allowed, active_lease = self.hub.check_file_lease(target_file, requesting_model_id="antigravity-ide")
        self.assertFalse(allowed)
        self.assertEqual(active_lease.locked_by_model, "claude-code")

        # 4. Same model check_file_lease -> ALLOWED
        allowed_self, _ = self.hub.check_file_lease(target_file, requesting_model_id="claude-code")
        self.assertTrue(allowed_self)

        # 5. Claude releases lease -> Antigravity can now acquire
        self.hub.release_file_lease("claude-code", target_file)
        ok3, msg3, lease3 = self.hub.acquire_file_lease("antigravity-ide", target_file, task_id="task-202", ttl_seconds=60)
        self.assertTrue(ok3)
        self.assertEqual(lease3.locked_by_model, "antigravity-ide")

    def test_file_lease_ttl_expiration(self) -> None:
        target_file = ROOT / "src" / "jhoc" / "config.py"
        # 1. Acquire with 1 second TTL
        ok1, _, _ = self.hub.acquire_file_lease("claude-code", target_file, ttl_seconds=1)
        self.assertTrue(ok1)

        # Sleep past TTL
        time.sleep(1.1)

        # 2. Antigravity acquires -> Previous lease expired, acquisition succeeds!
        ok2, _, lease2 = self.hub.acquire_file_lease("antigravity-ide", target_file, ttl_seconds=60)
        self.assertTrue(ok2)
        self.assertEqual(lease2.locked_by_model, "antigravity-ide")

    def test_inter_model_co_review_messaging_and_replies(self) -> None:
        # 1. Claude dispatches CO_REVIEW request to Codex
        corr_id = "co-review-20260903-p19"
        msg_id = self.hub.send_message(
            source_model="claude-code",
            target_model="codex-cli",
            operation="CO_REVIEW",
            payload={"files": ["src/jhoc/supervisor.py"], "diff_summary": "Unified Relay & Hub"},
            correlation_id=corr_id,
        )
        self.assertTrue(msg_id.startswith("msg-"))

        # 2. Codex fetches pending messages
        pending = self.hub.fetch_pending_messages("codex-cli")
        self.assertEqual(len(pending), 1)
        envelope = pending[0]
        self.assertEqual(envelope.operation, "CO_REVIEW")
        self.assertEqual(envelope.source_model, "claude-code")

        # 3. Codex completes review and replies
        reply_ok = self.hub.reply_message(
            envelope.message_id,
            status=MessageStatus.COMPLETED,
            reply_payload={"decision": "APPROVED", "comments": "All 3-model invariant checks passed."},
        )
        self.assertTrue(reply_ok)

        # 4. Verify conversation thread in correlation
        thread = self.hub.get_messages_by_correlation(corr_id)
        self.assertEqual(len(thread), 1)
        self.assertEqual(thread[0].status, MessageStatus.COMPLETED)
        self.assertEqual(thread[0].reply_payload["decision"], "APPROVED")

    def test_multi_task_slot_isolation(self) -> None:
        # Both models arm tasks concurrently without overwriting each other
        slot_a = self.hub.arm_task_slot("task-001", "claude-code", "Refactor Supervisor", str(ROOT), "sha-111")
        slot_b = self.hub.arm_task_slot("task-002", "antigravity-ide", "Implement Hub", str(ROOT), "sha-222")

        cur_a = self.hub.get_active_task_slot("claude-code")
        cur_b = self.hub.get_active_task_slot("antigravity-ide")

        self.assertIsNotNone(cur_a)
        self.assertIsNotNone(cur_b)
        self.assertEqual(cur_a.task_id, "task-001")
        self.assertEqual(cur_b.task_id, "task-002")

        # Claude closes task-001; Antigravity's task-002 remains ARMED!
        self.hub.close_task_slot("task-001", "claude-code")
        self.assertIsNone(self.hub.get_active_task_slot("claude-code"))
        self.assertIsNotNone(self.hub.get_active_task_slot("antigravity-ide"))

    def test_hook_gate_denies_write_on_leased_file(self) -> None:
        # 1. Use the real p19-hub.sqlite
        real_hub_db = ROOT / "logs" / "p19-hub.sqlite"
        real_hub = JHOCMultiModelHub(real_hub_db)
        test_file = ROOT / "src" / "jhoc" / "locked_demo_file.py"

        # Lock file by claude-code
        real_hub.acquire_file_lease("claude-code", test_file, ttl_seconds=60)

        # 2. Antigravity tries to write via evaluate_payload -> MUST DENY
        payload = {
            "toolCall": {
                "name": "write_to_file",
                "args": {
                    "TargetFile": str(test_file),
                    "CodeContent": "# Attempted overwrite",
                },
            }
        }
        res = evaluate_payload(payload)
        self.assertEqual(res["decision"], "deny")
        self.assertIn("File Mutex Conflict", res["reason"])
        self.assertIn("claude-code", res["reason"])

        # 3. Clean up
        real_hub.release_file_lease("claude-code", test_file)
        real_hub.close()

    def test_schema_enforced_partial_unique_index_prevents_dual_active_leases(self) -> None:
        """Verifies BLIND-01 remedy: DB engine itself forbids concurrent dual active leases."""
        import sqlite3
        conn = self.hub._get_connection()
        norm_path = self.hub.normalize_file_path("src/jhoc/core.py")

        # 1. Insert first active lease
        conn.execute(
            "INSERT INTO hub_file_leases (lease_id, file_path, locked_by_model, granted_at, expires_at, ttl_seconds, status) "
            "VALUES ('l-1', ?, 'claude-code', '2026-09-03', '2026-09-04', 120, 'ACTIVE')",
            (norm_path,),
        )

        # 2. Attempt to insert second active lease on SAME file path -> MUST RAISE IntegrityError!
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO hub_file_leases (lease_id, file_path, locked_by_model, granted_at, expires_at, ttl_seconds, status) "
                "VALUES ('l-2', ?, 'codex-cli', '2026-09-03', '2026-09-04', 120, 'ACTIVE')",
                (norm_path,),
            )

    def test_fencing_token_on_lease_release(self) -> None:
        """Verifies BLIND-03 remedy: lease_id fencing token prevents stale workers from releasing newer leases."""
        target_file = ROOT / "src" / "jhoc" / "fencing_demo.py"
        ok, _, lease = self.hub.acquire_file_lease("claude-code", target_file, ttl_seconds=60)
        self.assertTrue(ok)
        self.assertIsNotNone(lease)

        # Wrong fencing token -> release fails
        rel_fail = self.hub.release_file_lease("claude-code", target_file, lease_id="stale-lease-id")
        self.assertFalse(rel_fail)

        # Correct fencing token -> release succeeds
        rel_ok = self.hub.release_file_lease("claude-code", target_file, lease_id=lease.lease_id)
        self.assertTrue(rel_ok)

    def test_atomic_claim_message_and_terminal_guard(self) -> None:
        """Verifies BLIND-02 remedy: atomic claim prevents dual delivery, reply guards terminal state."""
        msg_id = self.hub.send_message("claude-code", "codex-cli", "TEST_OP", {"x": 1})

        # Worker 1 claims message
        claimed1 = self.hub.claim_message(msg_id, "codex-cli")
        self.assertTrue(claimed1)

        # Worker 2 tries to claim same message -> FAILS (already IN_PROGRESS)
        claimed2 = self.hub.claim_message(msg_id, "codex-cli")
        self.assertFalse(claimed2)

        # Worker 1 replies -> succeeds
        rep1 = self.hub.reply_message(msg_id, MessageStatus.COMPLETED, {"result": "ok"})
        self.assertTrue(rep1)

        # Stale late worker attempts to overwrite terminal state -> FAILS
        rep2 = self.hub.reply_message(msg_id, MessageStatus.FAILED, {"result": "stale"})
        self.assertFalse(rep2)


if __name__ == "__main__":
    unittest.main()

