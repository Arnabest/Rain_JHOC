from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from jhoc.contracts.errors import ContractError
from jhoc.guard.path import PathAccessMode, PathGuard
from jhoc_hook_gate import evaluate_payload
import jhoc_approve


class TestGovernanceRound2BlindSpots(unittest.TestCase):
    def setUp(self) -> None:
        self.secret_file = ROOT / "runtime" / ".operator_secret"
        if self.secret_file.exists():
            self.secret_file.unlink()
        self.original_token = os.environ.get("JHOC_OPERATOR_TOKEN")
        self.original_model = os.environ.get("JHOC_MODEL_ID")

    def tearDown(self) -> None:
        if self.secret_file.exists():
            self.secret_file.unlink()
        if self.original_token is not None:
            os.environ["JHOC_OPERATOR_TOKEN"] = self.original_token
        else:
            os.environ.pop("JHOC_OPERATOR_TOKEN", None)
        if self.original_model is not None:
            os.environ["JHOC_MODEL_ID"] = self.original_model
        else:
            os.environ.pop("JHOC_MODEL_ID", None)

    def test_round2_01_ledger_direct_tampering_blocked(self) -> None:
        # 1. Block commandline Python SQLite connection to inbox.db
        payload1 = {
            "caller": "antigravity-ide",
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "python -c \"import sqlite3; conn = sqlite3.connect('runtime/inbox.db')\""},
            },
        }
        res1 = evaluate_payload(payload1)
        self.assertEqual(res1["decision"], "deny")
        self.assertIn("Ledger Tampering Violation", res1["reason"])

        # 2. Block direct SQL command
        payload2 = {
            "caller": "antigravity-ide",
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "UPDATE jhoc_approval_inbox SET status='APPROVED'"},
            },
        }
        res2 = evaluate_payload(payload2)
        self.assertEqual(res2["decision"], "deny")
        self.assertIn("Ledger Tampering Violation", res2["reason"])

        # 3. Block write_to_file on inbox.db
        payload3 = {
            "caller": "antigravity-ide",
            "workspacePaths": [str(ROOT)],
            "toolCall": {
                "name": "write_to_file",
                "args": {"TargetFile": str(ROOT / "runtime" / "inbox.db"), "CodeContent": "corrupt"},
            },
        }
        res3 = evaluate_payload(payload3)
        self.assertEqual(res3["decision"], "deny")
        self.assertIn("Governance Root Violation", res3["reason"])

    def test_round2_02_core_engine_directory_write_blocked(self) -> None:
        # 1. Block modifying path.py inside src/jhoc/guard
        payload1 = {
            "caller": "antigravity-ide",
            "workspacePaths": [str(ROOT)],
            "toolCall": {
                "name": "replace_file_content",
                "args": {
                    "TargetFile": str(ROOT / "src" / "jhoc" / "guard" / "path.py"),
                    "TargetContent": "def is_sensitive",
                    "ReplacementContent": "def is_sensitive_bypassed",
                },
            },
        }
        res1 = evaluate_payload(payload1)
        self.assertEqual(res1["decision"], "deny")
        self.assertIn("Governance Root Violation", res1["reason"])

        # 2. Block modifying conductor inbox.py
        payload2 = {
            "caller": "antigravity-ide",
            "workspacePaths": [str(ROOT)],
            "toolCall": {
                "name": "write_to_file",
                "args": {
                    "TargetFile": str(ROOT / "src" / "jhoc" / "conductor" / "inbox.py"),
                    "CodeContent": "# exploit",
                },
            },
        }
        res2 = evaluate_payload(payload2)
        self.assertEqual(res2["decision"], "deny")
        self.assertIn("Governance Root Violation", res2["reason"])

        # 3. Verify PathGuard.evaluate raises ContractError on WRITE to core governance files
        with self.assertRaises(ContractError):
            PathGuard.evaluate(ROOT / "src" / "jhoc" / "guard" / "path.py", ROOT, mode=PathAccessMode.WRITE)

        # 4. But READ mode is permitted
        read_path = PathGuard.evaluate(ROOT / "src" / "jhoc" / "guard" / "path.py", ROOT, mode=PathAccessMode.READ)
        self.assertEqual(read_path, (ROOT / "src" / "jhoc" / "guard" / "path.py").resolve())

    def test_round2_03_shell_obfuscation_and_pipeline_laundering_blocked(self) -> None:
        # 1. Base64 EncodedCommand blocked
        payload1 = {
            "caller": "antigravity-ide",
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "powershell -EncodedCommand JABhACAAPQAgACIAMgAiAA=="},
            },
        }
        res1 = evaluate_payload(payload1)
        self.assertEqual(res1["decision"], "deny")
        self.assertIn("Destructive Command Violation", res1["reason"])

        # 2. Pipeline inverted Get-ChildItem | Remove-Item blocked
        payload2 = {
            "caller": "antigravity-ide",
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "Get-ChildItem -Recurse | Remove-Item -Force"},
            },
        }
        res2 = evaluate_payload(payload2)
        self.assertEqual(res2["decision"], "deny")
        self.assertIn("Destructive Command Violation", res2["reason"])

        # 3. rd /s /q blocked
        payload3 = {
            "caller": "antigravity-ide",
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "rd /s /q some_dir"},
            },
        }
        res3 = evaluate_payload(payload3)
        self.assertEqual(res3["decision"], "deny")
        self.assertIn("Destructive Command Violation", res3["reason"])

        # 4. rm -r blocked
        payload4 = {
            "caller": "antigravity-ide",
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "rm -rf some_dir"},
            },
        }
        res4 = evaluate_payload(payload4)
        self.assertEqual(res4["decision"], "deny")
        self.assertIn("Destructive Command Violation", res4["reason"])

    def test_round2_04_token_spoofing_blocked(self) -> None:
        # 1. Inline setting of JHOC_OPERATOR_TOKEN blocked in CommandLine
        payload = {
            "caller": "antigravity-ide",
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "$env:JHOC_OPERATOR_TOKEN='fake_token'; python scripts/jhoc_approve.py list"},
            },
        }
        res = evaluate_payload(payload)
        self.assertEqual(res["decision"], "deny")
        self.assertIn("Ledger Tampering Violation", res["reason"])

        # 2. Secret file check in jhoc_approve CLI
        self.secret_file.write_text("secret_999", encoding="utf-8")
        os.environ["JHOC_OPERATOR_TOKEN"] = "wrong_secret"
        exit_code = jhoc_approve.main(["approve", "ticket-xyz"])
        self.assertEqual(exit_code, 1)

        # 3. Correct secret passes check
        os.environ["JHOC_OPERATOR_TOKEN"] = "secret_999"
        # Since ticket-xyz doesn't exist, it will raise KeyError or handle it gracefully, but won't be permission denied
        exit_code_valid = jhoc_approve.main(["approve", "ticket-xyz"])
        self.assertEqual(exit_code_valid, 1)  # Ticket not found error, not Permission Denied


if __name__ == "__main__":
    unittest.main()
