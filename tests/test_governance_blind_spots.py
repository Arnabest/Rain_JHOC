from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from jhoc.conductor.inbox import ApprovalStatus, SQLiteApprovalInbox
from jhoc.hub import JHOCMultiModelHub, ModelPresenceState
from jhoc_hook_gate import evaluate_payload
from jhoc_stop_guard import evaluate_stop
import jhoc_approve


class TestGovernanceBlindSpots(unittest.TestCase):
    def setUp(self) -> None:
        self.inbox_db = ROOT / "runtime" / "inbox.db"
        self.inbox = SQLiteApprovalInbox(self.inbox_db)
        self.original_model_id = os.environ.get("JHOC_MODEL_ID")
        self.original_operator_token = os.environ.get("JHOC_OPERATOR_TOKEN")

    def tearDown(self) -> None:
        if self.original_model_id is not None:
            os.environ["JHOC_MODEL_ID"] = self.original_model_id
        else:
            os.environ.pop("JHOC_MODEL_ID", None)

        if self.original_operator_token is not None:
            os.environ["JHOC_OPERATOR_TOKEN"] = self.original_operator_token
        else:
            os.environ.pop("JHOC_OPERATOR_TOKEN", None)

        hub_db = ROOT / "logs" / "p19-hub.sqlite"
        if hub_db.is_file():
            try:
                hub = JHOCMultiModelHub(hub_db)
                hub.register_presence("antigravity-ide", ModelPresenceState.IDLE)
            except Exception:
                pass

    def test_blind_01_approval_ticket_consumed_after_use(self) -> None:
        # Create and approve a ticket
        cmd = "git reset --hard HEAD~1"
        ticket = self.inbox.create_ticket(
            operation="destructive_command",
            requester="test_runner",
            reason="Testing one-shot consumption",
            payload={"target": cmd, "command": cmd},
        )
        self.inbox.approve(ticket.ticket_id, approver="operator_test", note="Approved once")

        # First execution: Must be allowed and consumed
        payload = {
            "caller": "antigravity-ide",
            "toolCall": {"name": "run_command", "args": {"CommandLine": cmd}},
        }
        res1 = evaluate_payload(payload)
        self.assertEqual(res1["decision"], "allow")
        self.assertIn("consumed for one-shot execution", res1["reason"])

        # Check DB status: Must be CONSUMED
        updated = self.inbox.get_ticket(ticket.ticket_id)
        self.assertIsNotNone(updated)
        self.assertEqual(updated.status, ApprovalStatus.CONSUMED)

        # Second execution: Must be DENIED because ticket was consumed (no infinite replay)
        res2 = evaluate_payload(payload)
        self.assertEqual(res2["decision"], "deny")

    def test_blind_02_self_approval_blocked(self) -> None:
        # 1. Blocked via hook gate
        payload = {
            "caller": "antigravity-ide",
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "python scripts/jhoc_approve.py approve ticket-xyz"},
            },
        }
        res = evaluate_payload(payload)
        self.assertEqual(res["decision"], "deny")
        self.assertIn("Privilege Escalation Violation", res["reason"])

        # 2. Blocked within jhoc_approve CLI when autonomous model context is detected
        os.environ["JHOC_MODEL_ID"] = "claude-code"
        os.environ.pop("JHOC_OPERATOR_TOKEN", None)
        exit_code = jhoc_approve.main(["--db", str(self.inbox_db), "approve", "ticket-xyz"])
        self.assertEqual(exit_code, 1)

    def test_blind_03_governance_root_tamper_blocked(self) -> None:
        # Check write_to_file on hooks.json
        payload1 = {
            "caller": "antigravity-ide",
            "workspacePaths": [str(ROOT)],
            "toolCall": {
                "name": "write_to_file",
                "args": {"TargetFile": str(ROOT / ".agents" / "hooks.json"), "CodeContent": "{}"},
            },
        }
        res1 = evaluate_payload(payload1)
        self.assertEqual(res1["decision"], "deny")
        self.assertIn("Governance Root Violation", res1["reason"])

        # Check replace_file_content on jhoc_hook_gate.py
        payload2 = {
            "caller": "antigravity-ide",
            "workspacePaths": [str(ROOT)],
            "toolCall": {
                "name": "replace_file_content",
                "args": {
                    "TargetFile": str(ROOT / "scripts" / "jhoc_hook_gate.py"),
                    "TargetContent": "foo",
                    "ReplacementContent": "bar",
                },
            },
        }
        res2 = evaluate_payload(payload2)
        self.assertEqual(res2["decision"], "deny")
        self.assertIn("Governance Root Violation", res2["reason"])

    def test_blind_04_powershell_destructive_cmdlets_blocked(self) -> None:
        # Check Remove-Item recursive deletion
        payload1 = {
            "caller": "antigravity-ide",
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "Remove-Item -Recurse -Force src/jhoc"},
            },
        }
        res1 = evaluate_payload(payload1)
        self.assertEqual(res1["decision"], "deny")
        self.assertIn("Destructive Command Violation", res1["reason"])

        # Check Set-Content into sensitive file
        payload2 = {
            "caller": "antigravity-ide",
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "Set-Content -Path .env -Value 'LEAK=1'"},
            },
        }
        res2 = evaluate_payload(payload2)
        self.assertEqual(res2["decision"], "deny")
        self.assertIn("Sensitive Asset Violation", res2["reason"])

    def test_blind_05_stop_guard_fail_closed_and_hub_check(self) -> None:
        hub_db = ROOT / "logs" / "p19-hub.sqlite"
        hub = JHOCMultiModelHub(hub_db)
        hub.register_presence("antigravity-ide", ModelPresenceState.CODING, task_id="task-blind05-test")

        # Even with empty/missing payload, Hub presence as CODING must block termination
        res = evaluate_stop({})
        self.assertEqual(res["decision"], "continue")
        self.assertIn("[JHOC LIFECYCLE GUARD]", res["reason"])


if __name__ == "__main__":
    unittest.main()
