from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from jhoc.guard.vault import CredentialVault
from jhoc_hook_gate import evaluate_payload
from jhoc_log_stats import get_blackbox_stats, get_vault_stats


class TestMultiModelAttribution(unittest.TestCase):
    def setUp(self) -> None:
        self.original_env_model = os.environ.get("JHOC_MODEL_ID")
        self.vault = CredentialVault()

    def tearDown(self) -> None:
        if self.original_env_model is not None:
            os.environ["JHOC_MODEL_ID"] = self.original_env_model
        else:
            os.environ.pop("JHOC_MODEL_ID", None)

    def test_hook_gate_attributes_actor_from_env(self) -> None:
        os.environ["JHOC_MODEL_ID"] = "claude-code"
        payload = {
            "toolCall": {
                "name": "view_file",
                "args": {"AbsolutePath": str(ROOT / "README.md")},
            }
        }
        res = evaluate_payload(payload)
        self.assertEqual(res["decision"], "allow")

        bb_file = ROOT / "logs" / "p19-blackbox.jsonl"
        lines = [l for l in bb_file.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertTrue(len(lines) > 0)
        last_entry = json.loads(lines[-1])

        self.assertEqual(last_entry.get("actor"), "claude-code")
        self.assertEqual(last_entry.get("content", {}).get("actor"), "claude-code")

    def test_hook_gate_attributes_actor_from_payload(self) -> None:
        os.environ.pop("JHOC_MODEL_ID", None)
        payload = {
            "caller": "codex-cli",
            "task_id": "task-test-codex-101",
            "toolCall": {
                "name": "view_file",
                "args": {"AbsolutePath": str(ROOT / "README.md")},
            },
        }
        res = evaluate_payload(payload)
        self.assertEqual(res["decision"], "allow")

        bb_file = ROOT / "logs" / "p19-blackbox.jsonl"
        lines = [l for l in bb_file.read_text(encoding="utf-8").splitlines() if l.strip()]
        last_entry = json.loads(lines[-1])

        self.assertEqual(last_entry.get("actor"), "codex-cli")
        self.assertEqual(last_entry.get("task_id"), "task-test-codex-101")
        self.assertEqual(last_entry.get("content", {}).get("actor"), "codex-cli")

    def test_vault_records_caller_model(self) -> None:
        token = self.vault.register_secret("attribution_secret", "raw_secret_value_123")
        resolved = self.vault.resolve_for_egress(token, authorized_actor="adapter.test", caller_model="claude-code")
        self.assertEqual(resolved, "raw_secret_value_123")

        audit_file = ROOT / "logs" / "audit" / "vault-access.jsonl"
        lines = [l for l in audit_file.read_text(encoding="utf-8").splitlines() if l.strip()]
        last_record = json.loads(lines[-1])

        self.assertEqual(last_record.get("actor"), "adapter.test")
        self.assertEqual(last_record.get("caller_model"), "claude-code")
        self.assertEqual(last_record.get("status"), "DEREFERENCED")

    def test_dashboard_tally_groups_by_model(self) -> None:
        # Pre-seed calls from distinct models
        evaluate_payload({"caller": "claude-code", "toolCall": {"name": "view_file", "args": {"AbsolutePath": "foo"}}})
        evaluate_payload({"caller": "codex-cli", "toolCall": {"name": "view_file", "args": {"AbsolutePath": "bar"}}})

        token = self.vault.register_secret("seed_secret", "raw_val")
        self.vault.resolve_for_egress(token, authorized_actor="adapter.test", caller_model="claude-code")

        bb_stats, _, model_tool_stats = get_blackbox_stats()
        self.assertIn("claude-code", model_tool_stats)
        self.assertIn("codex-cli", model_tool_stats)
        self.assertGreaterEqual(model_tool_stats["claude-code"]["total"], 1)
        self.assertGreaterEqual(model_tool_stats["codex-cli"]["total"], 1)

        vault_stats, model_vault_stats = get_vault_stats()
        self.assertIn("claude-code", model_vault_stats)
        self.assertGreaterEqual(model_vault_stats["claude-code"], 1)


if __name__ == "__main__":
    unittest.main()
