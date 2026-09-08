from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from jhoc.guard.path import PathAccessMode, PathGuard
from jhoc.conductor.inbox import SQLiteApprovalInbox
from jhoc.contracts.errors import ContractError
from jhoc_hook_gate import evaluate_payload


class TestGatingApprovalAndStats(unittest.TestCase):
    def test_path_guard_allows_jhoc_mother_root_read(self) -> None:
        with tempfile.TemporaryDirectory() as temp_ws:
            ws_path = Path(temp_ws).resolve()
            jhoc_skill = ROOT / ".agents" / "skills" / "kaigong" / "SKILL.md"

            # 1. READ mode on JHOC root file from external workspace -> MUST PASS
            resolved = PathGuard.evaluate(jhoc_skill, ws_path, mode=PathAccessMode.READ)
            self.assertEqual(resolved, jhoc_skill.resolve())

            # 2. WRITE mode on JHOC root file from external workspace -> MUST BE BLOCKED
            with self.assertRaises(ContractError):
                PathGuard.evaluate(jhoc_skill, ws_path, mode=PathAccessMode.WRITE)

    def test_hook_gate_ticket_escalation_and_approval_override(self) -> None:
        from uuid import uuid4
        inbox_db = ROOT / "runtime" / "inbox.db"
        inbox = SQLiteApprovalInbox(inbox_db)

        test_cmd = f"git clean -fd --test-{uuid4()}"
        payload = {
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": test_cmd},
            }
        }

        try:
            # 1. First evaluation: must be denied and create a ticket
            res1 = evaluate_payload(payload)
            self.assertEqual(res1["decision"], "deny")
            self.assertIn("Approval Required: Ticket", res1["reason"])

            import re
            m = re.search(r"Ticket\s+(ticket-[a-f0-9\-]+)\s+created", res1["reason"])
            self.assertIsNotNone(m, "Ticket ID must be extracted from reason")
            ticket_id = m.group(1)

            ticket = inbox.get_ticket(ticket_id)
            self.assertIsNotNone(ticket)
            self.assertEqual(ticket.status.value, "PENDING")

            # 2. Approve ticket via inbox
            inbox.approve(ticket_id, approver="test_operator", note="test permit")

            # 3. Second evaluation: with approved ticket -> MUST BE ALLOWED
            res2 = evaluate_payload(payload)
            self.assertEqual(res2["decision"], "allow")
            self.assertIn("Approval Override", res2["reason"])
            self.assertIn(ticket_id, res2["reason"])
        finally:
            if "ticket_id" in locals():
                with inbox._lock:
                    inbox._db.execute("DELETE FROM jhoc_approval_inbox WHERE ticket_id = ?", (ticket_id,))
                    inbox._db.commit()
            inbox.close()

    def test_blackbox_trace_appended(self) -> None:
        evaluate_payload({"toolCall": {"name": "run_command", "args": {"CommandLine": "python --version"}}})
        bb_file = ROOT / "logs" / "p19-blackbox.jsonl"
        self.assertTrue(bb_file.is_file(), "Blackbox jsonl file must exist after tool calls")
        lines = [l for l in bb_file.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertGreater(len(lines), 0)
        last_entry = json.loads(lines[-1])
        self.assertEqual(last_entry["step_type"], "TOOL")
        self.assertIn("entry_hash", last_entry)
        self.assertIn("previous_hash", last_entry)

    def test_log_stats_cli_runs(self) -> None:
        res = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "jhoc_log_stats.py"), "--json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self.assertEqual(res.returncode, 0)
        data = json.loads(res.stdout)
        self.assertIn("tasks", data)
        self.assertIn("blackbox_gate", data)
        self.assertIn("approvals", data)
        self.assertIn("vault_egress", data)


if __name__ == "__main__":
    unittest.main()
