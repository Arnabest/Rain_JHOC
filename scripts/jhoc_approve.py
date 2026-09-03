"""CLI tool for operator approval of Guard and Conductor REQUIRE_APPROVAL tickets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jhoc.conductor.inbox import ApprovalStatus, SQLiteApprovalInbox


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="JHOC Human-in-the-Loop Approval Inbox")
    parser.add_argument("--db", default=str(ROOT / "runtime" / "inbox.db"), help="JHOC SQLite database path")
    subparsers = parser.add_subparsers(dest="action", required=True)

    # list
    list_cmd = subparsers.add_parser("list", help="List approval tickets")
    list_cmd.add_argument("--status", choices=("PENDING", "APPROVED", "REJECTED", "CONSUMED", "ALL"), default="PENDING")
    list_cmd.add_argument("--json", action="store_true", help="Output raw JSON")

    # show
    show_cmd = subparsers.add_parser("show", help="Show details of an approval ticket")
    show_cmd.add_argument("ticket_id", help="Ticket ID to inspect")

    # approve
    approve_cmd = subparsers.add_parser("approve", help="Approve a pending ticket")
    approve_cmd.add_argument("ticket_id", help="Ticket ID to approve")
    approve_cmd.add_argument("--approver", default="operator", help="Approver identity")
    approve_cmd.add_argument("--note", default="Approved by operator via CLI", help="Approval note")

    # reject
    reject_cmd = subparsers.add_parser("reject", help="Reject a pending ticket")
    reject_cmd.add_argument("ticket_id", help="Ticket ID to reject")
    reject_cmd.add_argument("--approver", default="operator", help="Approver identity")
    reject_cmd.add_argument("--reason", default="Rejected by operator via CLI", help="Rejection reason")

    # check
    check_cmd = subparsers.add_parser("check", help="Check if ticket is approved (exit 0 if approved, 1 otherwise)")
    check_cmd.add_argument("ticket_id", help="Ticket ID to check")

    return parser


def main(argv: list[str] | None = None) -> int:
    import os
    args = build_parser().parse_args(argv)

    if args.action in ("approve", "reject"):
        secret_file = ROOT / "runtime" / ".operator_secret"
        token = os.environ.get("JHOC_OPERATOR_TOKEN", "")
        if secret_file.is_file():
            expected = secret_file.read_text(encoding="utf-8").strip()
            if not token or token != expected:
                print("[FAIL] Permission Denied: Invalid or missing operator token.")
                return 1
        elif os.environ.get("JHOC_MODEL_ID") and not token:
            print("[FAIL] Permission Denied: Autonomous model execution detected. Self-approval is strictly forbidden.")
            return 1

    inbox = SQLiteApprovalInbox(args.db)

    try:
        if args.action == "list":
            status_filter = None if args.status == "ALL" else ApprovalStatus(args.status)
            tickets = inbox.list_tickets(status=status_filter)
            if getattr(args, "json", False):
                print(json.dumps([t.to_dict() for t in tickets], indent=2, ensure_ascii=False))
                return 0
            print(f"=== JHOC Approval Inbox ({args.status}) - Total: {len(tickets)} ===")
            if not tickets:
                print("No tickets found.")
                return 0
            for t in tickets:
                print(f"[{t.status.value}] {t.ticket_id} | Op: {t.operation} | By: {t.requester}")
                print(f"  Reason: {t.reason}")
                print(f"  Created: {t.created_at.isoformat()}")
                if t.resolved_at:
                    print(f"  Resolved: {t.resolved_at.isoformat()} by {t.approver} ({t.resolution_reason})")
                print()
            return 0

        if args.action == "show":
            ticket = inbox.get_ticket(args.ticket_id)
            if ticket is None:
                sys.stderr.write(f"Error: ticket not found: {args.ticket_id}\n")
                return 1
            print(json.dumps(ticket.to_dict(), indent=2, ensure_ascii=False))
            return 0

        if args.action == "approve":
            ticket = inbox.approve(args.ticket_id, approver=args.approver, note=args.note, operator_token=token)
            print(f"APPROVED: {ticket.ticket_id} (Operation: {ticket.operation}) by {ticket.approver}")
            return 0

        if args.action == "reject":
            ticket = inbox.reject(args.ticket_id, approver=args.approver, reason=args.reason, operator_token=token)
            print(f"REJECTED: {ticket.ticket_id} (Operation: {ticket.operation}) by {ticket.approver}")
            return 0

        if args.action == "check":
            approved = inbox.is_approved(args.ticket_id)
            print(f"Ticket {args.ticket_id} approved: {approved}")
            return 0 if approved else 1

        return 0
    except (KeyError, ValueError, PermissionError) as exc:
        print(f"[FAIL] {exc}")
        return 1
    finally:
        inbox.close()


if __name__ == "__main__":
    raise SystemExit(main())
