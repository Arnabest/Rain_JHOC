from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from jhoc.conductor.inbox import SQLiteApprovalInbox
from jhoc_hook_gate import evaluate_payload


class TestGovernanceRound4BlindSpots(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_inbox.db"
        self.secret_file = ROOT / "runtime" / ".operator_secret"
        if self.secret_file.exists():
            self.secret_file.unlink()
        self.inbox = SQLiteApprovalInbox(self.db_path)
        self.ticket = self.inbox.create_ticket("test_op", "test_req", "test_reason")
        self.orig_model = os.environ.get("JHOC_MODEL_ID")
        self.orig_token = os.environ.get("JHOC_OPERATOR_TOKEN")

    def tearDown(self) -> None:
        self.inbox.close()
        self.temp_dir.cleanup()
        if self.secret_file.exists():
            self.secret_file.unlink()
        if self.orig_model is not None:
            os.environ["JHOC_MODEL_ID"] = self.orig_model
        else:
            os.environ.pop("JHOC_MODEL_ID", None)
        if self.orig_token is not None:
            os.environ["JHOC_OPERATOR_TOKEN"] = self.orig_token
        else:
            os.environ.pop("JHOC_OPERATOR_TOKEN", None)

    def test_round4_01_library_level_self_approval_blocked(self) -> None:
        # 1. Model context without token raises PermissionError on inbox.approve()
        os.environ["JHOC_MODEL_ID"] = "claude-code"
        os.environ.pop("JHOC_OPERATOR_TOKEN", None)
        with self.assertRaises(PermissionError):
            self.inbox.approve(self.ticket.ticket_id)

        with self.assertRaises(PermissionError):
            self.inbox.reject(self.ticket.ticket_id)

        # 2. Secret file mismatch raises PermissionError
        self.secret_file.write_text("top_secret_token", encoding="utf-8")
        os.environ.pop("JHOC_MODEL_ID", None)
        os.environ["JHOC_OPERATOR_TOKEN"] = "wrong_token"
        with self.assertRaises(PermissionError):
            self.inbox.approve(self.ticket.ticket_id)

        # 3. Valid secret passes
        os.environ["JHOC_OPERATOR_TOKEN"] = "top_secret_token"
        approved = self.inbox.approve(self.ticket.ticket_id, operator_token="top_secret_token")
        self.assertEqual(approved.approver, "operator")

    def test_round4_02_other_harness_tool_aliases_normalized(self) -> None:
        # 1. Bash / terminal tool alias normalized to run_command and gated
        payload1 = {
            "caller": "claude-code",
            "toolName": "Bash",
            "toolCall": {
                "args": {"command": "rd /s /q test_dir"},
            },
        }
        res1 = evaluate_payload(payload1)
        self.assertEqual(res1["decision"], "deny")
        self.assertIn("Destructive Command Violation", res1["reason"])

        # 2. Edit / write tool alias normalized to write_to_file and gated against core assets
        payload2 = {
            "caller": "antigravity-ide",
            "tool": "edit",
            "toolCall": {
                "args": {"path": str(ROOT / "src" / "jhoc" / "guard" / "path.py"), "content": "# hacked"},
            },
        }
        res2 = evaluate_payload(payload2)
        self.assertEqual(res2["decision"], "deny")
        self.assertIn("Governance Root Violation", res2["reason"])

    def test_round4_03_python_destructive_and_obfuscation_patterns_blocked(self) -> None:
        # 1. shutil.rmtree blocked
        payload1 = {
            "caller": "antigravity-ide",
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "python -c \"import shutil; shutil.rmtree('some_dir')\""},
            },
        }
        res1 = evaluate_payload(payload1)
        self.assertEqual(res1["decision"], "deny")
        self.assertIn("Destructive Command Violation", res1["reason"])

        # 2. os.remove / os.unlink blocked
        payload2 = {
            "caller": "antigravity-ide",
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "python -c \"import os; os.unlink('file.txt')\""},
            },
        }
        res2 = evaluate_payload(payload2)
        self.assertEqual(res2["decision"], "deny")
        self.assertIn("Destructive Command Violation", res2["reason"])

        # 3. base64.b64decode with exec blocked
        payload3 = {
            "caller": "antigravity-ide",
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "python -c \"import base64; exec(base64.b64decode('cHJpbnQoMSk='))\""},
            },
        }
        res3 = evaluate_payload(payload3)
        self.assertEqual(res3["decision"], "deny")
        self.assertIn("Destructive Command Violation", res3["reason"])


if __name__ == "__main__":
    unittest.main()
