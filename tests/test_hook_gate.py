from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from jhoc_hook_gate import evaluate_payload


class TestHookGate(unittest.TestCase):
    def setUp(self) -> None:
        self._quota_patcher = mock.patch("jhoc.quota.antigravity_quota.get_antigravity_quota_live")
        self._mock_quota = self._quota_patcher.start()
        self._mock_quota.return_value = {
            "enabled": True,
            "account_email": "healthy_test@gmail.com",
            "gemini_5h_pct": 100,
            "gemini_weekly_pct": 100,
            "gemini_5h_reset": "~4h",
            "gemini_weekly_reset": "~6d",
        }

    def tearDown(self) -> None:
        self._quota_patcher.stop()

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

    @unittest.mock.patch("jhoc.quota.antigravity_quota.get_antigravity_quota_live")
    def test_quota_fuse_denies_normal_write(self, mock_quota) -> None:
        mock_quota.return_value = {
            "enabled": True,
            "account_email": "fuse_test@gmail.com",
            "gemini_5h_pct": 2,
            "gemini_5h_reset": "~1h",
            "gemini_weekly_pct": 50,
        }
        payload = {
            "conversationId": "test-fuse-conv",
            "toolCall": {
                "name": "write_to_file",
                "args": {
                    "TargetFile": str(ROOT / "src" / "jhoc" / "new_feature.py"),
                    "CodeContent": "x = 1",
                },
            },
        }
        res = evaluate_payload(payload)
        self.assertEqual(res["decision"], "deny")
        self.assertIn("[CRITICAL QUOTA & BALANCE FUSE]", res["reason"])
        self.assertIn("fuse_test@gmail.com", res["reason"])

    @unittest.mock.patch("jhoc.quota.antigravity_quota.get_antigravity_quota_live")
    def test_quota_fuse_allows_whitelist_write(self, mock_quota) -> None:
        mock_quota.return_value = {
            "enabled": True,
            "account_email": "fuse_test@gmail.com",
            "gemini_5h_pct": 2,
            "gemini_5h_reset": "~1h",
            "gemini_weekly_pct": 50,
        }
        # Whitelist 1: implementation_plan.md
        payload1 = {
            "conversationId": "test-fuse-conv",
            "toolCall": {
                "name": "write_to_file",
                "args": {
                    "TargetFile": str(ROOT / "implementation_plan.md"),
                    "CodeContent": "# Updated plan",
                },
            },
        }
        res1 = evaluate_payload(payload1)
        self.assertEqual(res1["decision"], "allow")

        # Whitelist 2: memory/handoff
        payload2 = {
            "conversationId": "test-fuse-conv",
            "toolCall": {
                "name": "write_to_file",
                "args": {
                    "TargetFile": str(ROOT / "memory" / "handoff-latest.json"),
                    "CodeContent": "{}",
                },
            },
        }
        res2 = evaluate_payload(payload2)
        self.assertEqual(res2["decision"], "allow")

    @unittest.mock.patch("jhoc.quota.antigravity_quota.get_antigravity_quota_live")
    def test_quota_fuse_denies_normal_command(self, mock_quota) -> None:
        mock_quota.return_value = {
            "enabled": True,
            "account_email": "fuse_test@gmail.com",
            "gemini_5h_pct": 2,
            "gemini_5h_reset": "~1h",
            "gemini_weekly_pct": 50,
        }
        payload = {
            "conversationId": "test-fuse-conv",
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "npm test"},
            },
        }
        res = evaluate_payload(payload)
        self.assertEqual(res["decision"], "deny")
        self.assertIn("[CRITICAL QUOTA & BALANCE FUSE]", res["reason"])

    @unittest.mock.patch("jhoc.quota.antigravity_quota.get_antigravity_quota_live")
    def test_quota_fuse_allows_whitelist_command(self, mock_quota) -> None:
        mock_quota.return_value = {
            "enabled": True,
            "account_email": "fuse_test@gmail.com",
            "gemini_5h_pct": 2,
            "gemini_5h_reset": "~1h",
            "gemini_weekly_pct": 50,
        }
        # Whitelist: jhoc_shougong.py
        payload = {
            "conversationId": "test-fuse-conv",
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "py -3 scripts/jhoc_shougong.py"},
            },
        }
        res = evaluate_payload(payload)
        self.assertEqual(res["decision"], "allow")

    @unittest.mock.patch("jhoc.quota.antigravity_quota.get_antigravity_quota_live")
    def test_stop_guard_quota_critical_blocking(self, mock_quota) -> None:
        from jhoc_stop_guard import evaluate_stop
        mock_quota.return_value = {
            "enabled": True,
            "account_email": "fuse_test@gmail.com",
            "gemini_5h_pct": 1,
            "gemini_5h_reset": "~1h",
            "gemini_weekly_pct": 40,
        }
        # When handoff file does not exist, stop must be blocked
        with unittest.mock.patch("pathlib.Path.is_file", return_value=False):
            res = evaluate_stop({"conversationId": "test-conv"})
            self.assertEqual(res["decision"], "continue")
            self.assertIn("[QUOTA CRITICAL STOP BLOCKED]", res["reason"])

    @unittest.mock.patch("jhoc.quota.antigravity_quota.get_antigravity_quota_live")
    def test_pre_inject_conversation_id_critical_alert(self, mock_quota) -> None:
        from jhoc_pre_inject import evaluate_pre_invocation
        mock_quota.return_value = {
            "enabled": True,
            "account_email": "fuse_test@gmail.com",
            "gemini_5h_pct": 1,
            "gemini_5h_reset": "~1h",
            "gemini_weekly_pct": 40,
        }
        res = evaluate_pre_invocation({"conversationId": "test-conv"}, check_quota=True)
        messages = [s.get("ephemeralMessage", "") for s in res.get("injectSteps", [])]
        self.assertTrue(any("[CRITICAL QUOTA ALERT]" in m for m in messages))

    @unittest.mock.patch("jhoc.quota.antigravity_quota.get_antigravity_quota_live")
    @unittest.mock.patch("jhoc.quota.api_balance.get_api_balances_live")
    def test_api_balance_fuse_denies_normal_write(self, mock_balances, mock_quota) -> None:
        from jhoc.quota.api_balance import APIKeyBalance
        mock_quota.return_value = {
            "enabled": True,
            "account_email": "test@gmail.com",
            "gemini_5h_pct": 80,
            "gemini_5h_reset": "~4h",
            "gemini_weekly_pct": 90,
        }
        mock_balances.return_value = {
            "DeepSeek": APIKeyBalance(
                provider="DeepSeek",
                currency="CNY",
                total_balance=0.5,
                is_available=True,
                status="critical",
            )
        }
        payload = {
            "conversationId": "test-api-conv",
            "toolCall": {
                "name": "write_to_file",
                "args": {
                    "TargetFile": str(ROOT / "src" / "jhoc" / "new_feature.py"),
                    "CodeContent": "x = 2",
                },
            },
        }
        res = evaluate_payload(payload)
        self.assertEqual(res["decision"], "deny")
        self.assertIn("[CRITICAL QUOTA & BALANCE FUSE]", res["reason"])
        self.assertTrue("API balance critical" in res["reason"] or "API Key 余额告急" in res["reason"])

    @unittest.mock.patch("jhoc.quota.antigravity_quota.get_antigravity_quota_live")
    def test_stop_guard_quota_critical_stale_handoff_blocked(self, mock_quota) -> None:
        from jhoc_stop_guard import evaluate_stop
        mock_quota.return_value = {
            "enabled": True,
            "account_email": "fuse_test@gmail.com",
            "gemini_5h_pct": 2,
            "gemini_5h_reset": "~1h",
            "gemini_weekly_pct": 40,
        }
        fake_handoff = json.dumps({"quota_status": {"is_alert": True}})
        def fake_is_file(self, *args, **kwargs):
            return "handoff-latest.json" in str(self)

        with unittest.mock.patch("pathlib.Path.is_file", autospec=True, side_effect=fake_is_file), \
             unittest.mock.patch("pathlib.Path.read_text", autospec=True, return_value=fake_handoff), \
             unittest.mock.patch("pathlib.Path.stat", autospec=True) as mock_stat:
            mock_stat.return_value.st_mtime = 0.0  # Unix epoch -> stale
            res = evaluate_stop({"conversationId": "test-conv"})
            self.assertEqual(res["decision"], "continue")
            self.assertIn("[QUOTA CRITICAL STOP BLOCKED]", res["reason"])

    @unittest.mock.patch("jhoc.quota.antigravity_quota.get_antigravity_quota_live")
    def test_stop_guard_quota_critical_fresh_alert_handoff_allowed(self, mock_quota) -> None:
        import time
        from jhoc_stop_guard import evaluate_stop
        mock_quota.return_value = {
            "enabled": True,
            "account_email": "fuse_test@gmail.com",
            "gemini_5h_pct": 2,
            "gemini_5h_reset": "~1h",
            "gemini_weekly_pct": 40,
        }
        fake_handoff = json.dumps({"quota_status": {"is_alert": True}})
        def fake_is_file(self, *args, **kwargs):
            return "handoff-latest.json" in str(self)

        with unittest.mock.patch("pathlib.Path.is_file", autospec=True, side_effect=fake_is_file), \
             unittest.mock.patch("pathlib.Path.read_text", autospec=True, return_value=fake_handoff), \
             unittest.mock.patch("pathlib.Path.stat", autospec=True) as mock_stat:
            mock_stat.return_value.st_mtime = time.time()  # Right now -> fresh
            res = evaluate_stop({"conversationId": "test-conv"})
            self.assertEqual(res["decision"], "allow")

    @unittest.mock.patch("jhoc.quota.antigravity_quota.get_antigravity_quota_live")
    def test_quota_critical_blocks_business_code_write(self, mock_quota) -> None:
        mock_quota.return_value = {
            "enabled": True,
            "account_email": "crit_test@gmail.com",
            "gemini_5h_pct": 5,
            "gemini_5h_reset": "~1h",
            "gemini_weekly_pct": 20,
        }
        payload = {
            "conversationId": "test-crit-conv",
            "toolCall": {
                "name": "write_to_file",
                "args": {
                    "TargetFile": str(ROOT / "src" / "jhoc" / "business_logic.py"),
                    "CodeContent": "def foo(): pass",
                },
            },
        }
        res = evaluate_payload(payload)
        self.assertEqual(res["decision"], "deny")
        self.assertIn("[CRITICAL QUOTA & BALANCE FUSE]", res["reason"])

    @unittest.mock.patch("jhoc.quota.antigravity_quota.get_antigravity_quota_live")
    def test_quota_critical_allows_whitelisted_paths(self, mock_quota) -> None:
        mock_quota.return_value = {
            "enabled": True,
            "account_email": "crit_test@gmail.com",
            "gemini_5h_pct": 5,
            "gemini_5h_reset": "~1h",
            "gemini_weekly_pct": 20,
        }
        for subpath in ("docs/worklogs/test.md", "logs/archive_payloads/snap.json", "memory/handoff-latest.json"):
            payload = {
                "conversationId": "test-crit-conv",
                "toolCall": {
                    "name": "write_to_file",
                    "args": {
                        "TargetFile": str(ROOT / subpath),
                        "CodeContent": "Clean content",
                    },
                },
            }
            res = evaluate_payload(payload)
            self.assertEqual(res["decision"], "allow", f"Failed to whitelist: {subpath}")

    @unittest.mock.patch("jhoc.quota.antigravity_quota.get_antigravity_quota_live")
    def test_quota_critical_allows_whitelisted_commands_with_windows_paths(self, mock_quota) -> None:
        mock_quota.return_value = {
            "enabled": True,
            "account_email": "crit_test@gmail.com",
            "gemini_5h_pct": 4,
            "gemini_5h_reset": "~1h",
            "gemini_weekly_pct": 20,
        }
        safe_commands = (
            "py -3 scripts\\jhoc_shougong.py",
            "python G:\\JHOC\\scripts\\jhoc_worklog.py --blog --save",
            "git status",
            "git diff HEAD",
        )
        for cmd in safe_commands:
            payload = {
                "conversationId": "test-crit-conv",
                "toolCall": {
                    "name": "run_command",
                    "args": {
                        "CommandLine": cmd,
                    },
                },
            }
            res = evaluate_payload(payload)
            self.assertEqual(res["decision"], "allow", f"Failed to whitelist command: {cmd}")

    @unittest.mock.patch("jhoc.quota.antigravity_quota.get_antigravity_quota_live")
    def test_quota_critical_blocks_arbitrary_business_command(self, mock_quota) -> None:
        mock_quota.return_value = {
            "enabled": True,
            "account_email": "crit_test@gmail.com",
            "gemini_5h_pct": 3,
            "gemini_5h_reset": "~1h",
            "gemini_weekly_pct": 20,
        }
        payload = {
            "conversationId": "test-crit-conv",
            "toolCall": {
                "name": "run_command",
                "args": {
                    "CommandLine": "npm run build",
                },
            },
        }
        res = evaluate_payload(payload)
        self.assertEqual(res["decision"], "deny")
        self.assertIn("[CRITICAL QUOTA & BALANCE FUSE]", res["reason"])

    def test_stop_guard_force_stop_escape_hatch(self) -> None:
        from jhoc_stop_guard import evaluate_stop
        res = evaluate_stop({"force": True})
        self.assertEqual(res["decision"], "allow")
        self.assertIn("Forced stop override", res["reason"])


if __name__ == "__main__":
    unittest.main()


