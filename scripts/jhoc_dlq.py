"""Dead-Letter Queue (DLQ) inspection, alerting, and replay tool for JHOC."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jhoc.relay.broker import DeliveryStatus, SQLiteRelay


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="JHOC Dead-Letter Queue (DLQ) Inspector and Replayer")
    parser.add_argument("--db", default=str(ROOT / "runtime" / "jhoc.db"), help="JHOC SQLite runtime path")
    subparsers = parser.add_subparsers(dest="action", required=True)

    # list
    list_cmd = subparsers.add_parser("list", help="List all dead-lettered delivery records")
    list_cmd.add_argument("--json", action="store_true", help="Output raw JSON")
    list_cmd.add_argument("--fail-if-any", action="store_true", help="Exit with code 1 if any dead letter exists (for CI/alarms)")

    # show
    show_cmd = subparsers.add_parser("show", help="Show details of a specific dead letter")
    show_cmd.add_argument("message_id", help="Message ID to inspect")

    # replay
    replay_cmd = subparsers.add_parser("replay", help="Replay a dead letter back to PENDING queue")
    replay_cmd.add_argument("message_id", help="Message ID to replay")

    # purge
    purge_cmd = subparsers.add_parser("purge", help="Permanently delete a dead letter from queue")
    purge_cmd.add_argument("message_id", help="Message ID to purge")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    db_path = Path(args.db).resolve()
    if not db_path.exists():
        sys.stderr.write(f"Error: database does not exist: {db_path}\n")
        return 1

    relay = SQLiteRelay(str(db_path))

    try:
        if args.action == "list":
            dead = relay.dead_letters()
            if getattr(args, "json", False):
                records = [
                    {
                        "message_id": d.envelope.message_id,
                        "channel": d.envelope.channel,
                        "attempts": d.attempts,
                        "last_error": d.last_error,
                        "occurred_at": d.envelope.occurred_at.isoformat(),
                        "payload": d.envelope.payload,
                    }
                    for d in dead
                ]
                print(json.dumps(records, indent=2, ensure_ascii=False))
            else:
                print(f"=== JHOC Dead Letter Queue (DLQ) - Count: {len(dead)} ===")
                if not dead:
                    print("Queue is clean. No dead-lettered messages.")
                for d in dead:
                    print(f"[DEAD_LETTER] Message ID: {d.envelope.message_id}")
                    print(f"  Channel: {d.envelope.channel} | Attempts: {d.attempts}")
                    print(f"  Last Error: {d.last_error}")
                    print(f"  Occurred At: {d.envelope.occurred_at.isoformat()}")
                    print()

            if getattr(args, "fail_if_any", False) and dead:
                return 1
            return 0

        if args.action == "show":
            record = relay.get(args.message_id)
            if record is None:
                sys.stderr.write(f"Error: message not found: {args.message_id}\n")
                return 1
            print(json.dumps({
                "message_id": record.envelope.message_id,
                "status": record.status.value,
                "attempts": record.attempts,
                "last_error": record.last_error,
                "occurred_at": record.envelope.occurred_at.isoformat(),
                "payload": record.envelope.payload,
            }, indent=2, ensure_ascii=False))
            return 0

        if args.action == "replay":
            record = relay.replay(args.message_id)
            print(f"REPLAYED: {record.envelope.message_id} -> status: {record.status.value}")
            return 0

        if args.action == "purge":
            conn = sqlite3.connect(str(db_path))
            try:
                cur = conn.execute("DELETE FROM jhoc_relay_delivery WHERE message_id = ? AND status = ?", (args.message_id, DeliveryStatus.DEAD_LETTERED.value))
                conn.commit()
                if cur.rowcount > 0:
                    print(f"PURGED: {args.message_id}")
                    return 0
                else:
                    sys.stderr.write(f"Error: dead letter not found or not in DEAD_LETTERED status: {args.message_id}\n")
                    return 1
            finally:
                conn.close()

        return 0
    finally:
        pass


if __name__ == "__main__":
    raise SystemExit(main())
