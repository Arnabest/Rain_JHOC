import tempfile
import unittest
from pathlib import Path

from jhoc.conductor.inbox import ApprovalStatus, SQLiteApprovalInbox


class TestApprovalInbox(unittest.TestCase):
    def test_lifecycle_and_persistence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_inbox.db"
            inbox = SQLiteApprovalInbox(db_path)

            ticket = inbox.create_ticket(
                operation="mutate_code",
                requester="codex-cli",
                reason="Requires operator approval for code mutation",
                payload={"file": "src/core.py", "lines": 42},
                ticket_id="TICKET-001",
            )
            self.assertEqual(ticket.ticket_id, "TICKET-001")
            self.assertEqual(ticket.status, ApprovalStatus.PENDING)
            self.assertFalse(inbox.is_approved("TICKET-001"))

            # List pending
            pending = inbox.list_tickets(status=ApprovalStatus.PENDING)
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0].ticket_id, "TICKET-001")

            # Approve
            approved = inbox.approve("TICKET-001", approver="admin", note="LGTM")
            self.assertEqual(approved.status, ApprovalStatus.APPROVED)
            self.assertEqual(approved.approver, "admin")
            self.assertTrue(inbox.is_approved("TICKET-001"))

            # Cannot re-approve or reject once resolved
            with self.assertRaises(ValueError):
                inbox.approve("TICKET-001")
            with self.assertRaises(ValueError):
                inbox.reject("TICKET-001")

            inbox.close()

            # Verify persistence across restart
            inbox2 = SQLiteApprovalInbox(db_path)
            loaded = inbox2.get_ticket("TICKET-001")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.status, ApprovalStatus.APPROVED)
            self.assertTrue(inbox2.is_approved("TICKET-001"))
            inbox2.close()

    def test_reject_flow(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_inbox.db"
            inbox = SQLiteApprovalInbox(db_path)
            ticket = inbox.create_ticket("deploy", "deepseek", "Deploy to prod", ticket_id="T-002")
            rejected = inbox.reject("T-002", approver="sec-ops", reason="Too risky")
            self.assertEqual(rejected.status, ApprovalStatus.REJECTED)
            self.assertFalse(inbox.is_approved("T-002"))
            inbox.close()


if __name__ == "__main__":
    unittest.main()
