from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from jhoc_hook_gate import evaluate_payload


class TestHookGate(unittest.TestCase):
    def test_hooks_json_valid_and_present(self) -> None:
        hooks_file = ROOT / ".agents" / "hooks.json"
        self.assertTrue(hooks_file.is_file(), ".agents/hooks.json must exist")
        data = json.loads(hooks_file.read_text(encoding="utf-8"))
        self.assertIn("jhoc-gate", data)
        self.assertTrue(data["jhoc-gate"]["enabled"])
        self.assertIn("PreToolUse", data["jhoc-gate"])

    def test_evaluate_payload_clean_write_allowed(self) -> None:
        payload = {
            "toolCall": {
                "name": "write_to_file",
                "args": {
                    "TargetFile": str(ROOT / "safe_file.txt"),
                    "CodeContent": "Clean code without any emoji",
                },
            }
        }
        res = evaluate_payload(payload)
        self.assertEqual(res["decision"], "allow")

    def test_evaluate_payload_emoji_denied(self) -> None:
        payload = {
            "toolCall": {
                "name": "write_to_file",
                "args": {
                    "TargetFile": str(ROOT / "bad_file.txt"),
                    "CodeContent": "Code with \U0001f4a1 emoji",
                },
            }
        }
        res = evaluate_payload(payload)
        self.assertEqual(res["decision"], "deny")
        self.assertIn("Rule 7 Violation", res["reason"])

    def test_evaluate_payload_out_of_boundary_denied(self) -> None:
        payload = {
            "toolCall": {
                "name": "write_to_file",
                "args": {
                    "TargetFile": "C:\\Windows\\System32\\dangerous.dll",
                    "CodeContent": "dangerous",
                },
            }
        }
        res = evaluate_payload(payload)
        self.assertEqual(res["decision"], "deny")
        self.assertIn("Rule 5 Violation", res["reason"])

    def test_evaluate_payload_root_littering_denied(self) -> None:
        payload = {
            "toolCall": {
                "name": "write_to_file",
                "args": {
                    "TargetFile": str(ROOT / "test_scratch.py"),
                    "CodeContent": "print('ad hoc')",
                },
            },
            "workspacePaths": [str(ROOT)],
        }
        res = evaluate_payload(payload)
        self.assertEqual(res["decision"], "deny")
        self.assertIn("File Persistence Routing Violation", res["reason"])

    def test_evaluate_payload_scratch_allowed(self) -> None:
        payload = {
            "toolCall": {
                "name": "write_to_file",
                "args": {
                    "TargetFile": str(ROOT / "scratch" / "test_scratch.py"),
                    "CodeContent": "print('in scratch')",
                },
            },
            "workspacePaths": [str(ROOT)],
        }
        res = evaluate_payload(payload)
        self.assertEqual(res["decision"], "allow")

    def test_evaluate_payload_sensitive_asset_denied(self) -> None:
        payload = {
            "toolCall": {
                "name": "write_to_file",
                "args": {
                    "TargetFile": str(ROOT / ".env"),
                    "CodeContent": "SECRET=123",
                },
            },
            "workspacePaths": [str(ROOT)],
        }
        res = evaluate_payload(payload)
        self.assertEqual(res["decision"], "deny")
        self.assertIn("Sensitive Asset Violation", res["reason"])

    def test_evaluate_payload_clean_run_command_allowed(self) -> None:
        payload = {
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "python -m unittest discover"},
            }
        }
        res = evaluate_payload(payload)
        self.assertEqual(res["decision"], "allow")

    def test_evaluate_payload_run_command_emoji_denied(self) -> None:
        payload = {
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "echo \U0001f4a1"},
            }
        }
        res = evaluate_payload(payload)
        self.assertEqual(res["decision"], "deny")
        self.assertIn("Rule 7 Violation", res["reason"])

    def test_evaluate_payload_destructive_git_reset_denied(self) -> None:
        payload = {
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "git reset --hard HEAD~1"},
            }
        }
        res = evaluate_payload(payload)
        self.assertEqual(res["decision"], "deny")
        self.assertIn("Destructive Command Violation", res["reason"])

    def test_evaluate_payload_destructive_clean_denied(self) -> None:
        payload = {
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "git clean -fd"},
            }
        }
        res = evaluate_payload(payload)
        self.assertEqual(res["decision"], "deny")
        self.assertIn("Destructive Command Violation", res["reason"])

    def test_evaluate_payload_command_sensitive_redirect_denied(self) -> None:
        payload = {
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "echo SECRET > .env"},
            }
        }
        res = evaluate_payload(payload)
        self.assertEqual(res["decision"], "deny")
        self.assertIn("Sensitive Asset Violation", res["reason"])


if __name__ == "__main__":
    unittest.main()
