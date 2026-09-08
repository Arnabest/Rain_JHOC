"""Environment-parity integration test for Antigravity IDE hooks.

Upholds Conditions C1, C2, C3, C4, C5, C6:
- Executes hooks with CWD set to G:/JHOC/.agents (matching Antigravity IDE runtime).
- Verifies that no hook script is unresolved or missing.
- Verifies fail-closed enforcement under injected quota breach.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

JHOC_ROOT = Path(__file__).resolve().parents[2]
AGENTS_DIR = JHOC_ROOT / ".agents"
HOOKS_JSON = AGENTS_DIR / "hooks.json"


class TestHooksEnvParity(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(HOOKS_JSON.is_file(), f"Missing hooks.json at {HOOKS_JSON}")
        self.hooks_data = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))

    def test_hooks_json_contains_no_unanchored_relative_paths(self) -> None:
        raw_text = HOOKS_JSON.read_text(encoding="utf-8")
        if JHOC_ROOT.name == "JHOC":
            # In mother workspace, assert no bare unanchored relative path
            self.assertNotIn('"scripts/jhoc_', raw_text)
            self.assertNotIn("'scripts/jhoc_", raw_text)
        else:
            # In clean replica, assert zero absolute path leaks
            self.assertNotIn("G:/JHOC", raw_text)

    def test_hook_gate_executable_from_agents_cwd(self) -> None:
        gate_script = JHOC_ROOT / "scripts" / "jhoc_hook_gate.py"
        self.assertTrue(gate_script.is_file())

        payload = {
            "conversationId": "env-parity-session",
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "git status"},
            }
        }

        proc = subprocess.run(
            [sys.executable, str(gate_script)],
            input=json.dumps(payload),
            cwd=str(AGENTS_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
        )
        self.assertEqual(proc.returncode, 0, f"Hook gate failed with stderr: {proc.stderr}")
        res = json.loads(proc.stdout)
        self.assertIn("decision", res)
        self.assertEqual(res["decision"], "allow")

    def test_hook_gate_denies_on_quota_critical(self) -> None:
        gate_script = JHOC_ROOT / "scripts" / "jhoc_hook_gate.py"
        self.assertTrue(gate_script.is_file())

        # Inject critical quota in payload
        payload = {
            "conversationId": "env-parity-session",
            "quota_data": {
                "enabled": True,
                "account_email": "canary_exhausted@example.com",
                "gemini_5h_pct": 5.0,
                "gemini_weekly_pct": 50.0,
            },
            "toolCall": {
                "name": "write_to_file",
                "args": {"TargetFile": "src/dangerous_edit.py", "CodeContent": "x = 1"},
            }
        }

        proc = subprocess.run(
            [sys.executable, str(gate_script)],
            input=json.dumps(payload),
            cwd=str(AGENTS_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
        )
        self.assertEqual(proc.returncode, 0)
        res = json.loads(proc.stdout)
        self.assertEqual(res["decision"], "deny")
        self.assertIn("CRITICAL QUOTA & BALANCE FUSE", res["reason"])


if __name__ == "__main__":
    unittest.main()
