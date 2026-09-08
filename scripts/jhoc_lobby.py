"""JHOC Model Working Lobby & File Lease Dashboard CLI."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jhoc.hub import JHOCMultiModelHub, MessageStatus, ModelPresenceState


def get_hub() -> JHOCMultiModelHub:
    db_path = ROOT / "logs" / "p19-hub.sqlite"
    return JHOCMultiModelHub(db_path)


def cmd_status() -> int:
    hub = get_hub()
    now = datetime.now(timezone.utc)
    print("=" * 70)
    print("                JHOC MULTI-MODEL WORKING LOBBY                ")
    print("=" * 70)

    # 1. Active Models
    models = hub.get_active_models(stale_threshold_sec=300)
    print(f"1. Online Registered Models ({len(models)}):")
    if not models:
        print("   (No active models currently registered)")
    else:
        for m in models:
            hb_dt = datetime.fromisoformat(m.last_heartbeat)
            age_sec = int((now - hb_dt).total_seconds())
            task_str = f" [Task: {m.task_id}]" if m.task_id else ""
            print(f"   -> [{m.state.value}] {m.model_id}{task_str} (Last seen {age_sec}s ago, PID: {m.pid})")

    # 2. Active File Leases
    leases = hub.list_active_leases()
    print(f"\n2. Active File Mutex Leases ({len(leases)}):")
    if not leases:
        print("   (No files currently locked)")
    else:
        for l in leases:
            exp_dt = datetime.fromisoformat(l.expires_at)
            rem_sec = max(0, int((exp_dt - now).total_seconds()))
            task_str = f" [Task: {l.task_id}]" if l.task_id else ""
            print(f"   -> {l.file_path}")
            print(f"      Locked by: {l.locked_by_model}{task_str} (TTL remaining: {rem_sec}s)")

    # 3. Active Task Slots
    conn = hub._get_connection()
    cur = conn.execute(
        "SELECT task_id, owner_model, title, baseline_sha, status FROM hub_task_slots WHERE status = 'ARMED'"
    )
    slots = cur.fetchall()
    print(f"\n3. Concurrently Armed Task Slots ({len(slots)}):")
    if not slots:
        print("   (No task slots currently armed)")
    else:
        for tid, om, ttl, sha, st in slots:
            print(f"   -> [{om}] {ttl} ({tid}) [Baseline: {sha[:10]}]")

    # 4. Pending Co-Reviews / Relay Messages
    cur2 = conn.execute(
        "SELECT message_id, source_model, target_model, operation, correlation_id FROM hub_messages WHERE status = 'PENDING'"
    )
    msgs = cur2.fetchall()
    print(f"\n4. Pending Relay Messages / Co-Review Queue ({len(msgs)}):")
    if not msgs:
        print("   (No pending inter-model messages)")
    else:
        for mid, sm, tm, op, cid in msgs:
            print(f"   -> [{op}] From: {sm} -> To: {tm} (Corr: {cid})")

    print("=" * 70)
    return 0


def cmd_lock(file_path: str, model_id: str, ttl: int, task_id: str | None) -> int:
    hub = get_hub()
    ok, msg, lease = hub.acquire_file_lease(model_id, file_path, task_id=task_id, ttl_seconds=ttl)
    print(f"[{'PASS' if ok else 'FAIL'}] {msg}")
    return 0 if ok else 1


def cmd_unlock(file_path: str, model_id: str) -> int:
    hub = get_hub()
    ok = hub.release_file_lease(model_id, file_path)
    print(f"[{'PASS' if ok else 'WARN'}] {'Lease released' if ok else 'No active lease found to release'}")
    return 0 if ok else 1


def cmd_co_review(source_model: str, target_model: str, title: str, body: str) -> int:
    hub = get_hub()
    payload = {"title": title, "body": body, "requested_at": datetime.now(timezone.utc).isoformat()}
    msg_id = hub.send_message(source_model, target_model, "CO_REVIEW", payload)
    print(f"[PASS] Co-Review request dispatched via SQLite Hub! Message ID: {msg_id}")
    return 0


def cmd_reply(message_id: str, decision: str, comments: str) -> int:
    hub = get_hub()
    reply_payload = {
        "decision": decision,
        "comments": comments,
        "replied_at": datetime.now(timezone.utc).isoformat(),
    }
    ok = hub.reply_message(message_id, status=MessageStatus.COMPLETED, reply_payload=reply_payload)
    print(f"[{'PASS' if ok else 'FAIL'}] Co-Review response recorded: {decision}")
    return 0 if ok else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="JHOC Model Working Lobby & Mutex Dashboard")
    subparsers = parser.add_subparsers(dest="subcommand")

    # status
    subparsers.add_parser("status", help="Show real-time model presence and file leases")

    # lock
    lock_p = subparsers.add_parser("lock", help="Acquire a file lease")
    lock_p.add_argument("file", help="File path to lock")
    lock_p.add_argument("--model", required=True, help="Model identifier")
    lock_p.add_argument("--ttl", type=int, default=120, help="TTL seconds (default: 120)")
    lock_p.add_argument("--task", default=None, help="Associated task ID")

    # unlock
    unlock_p = subparsers.add_parser("unlock", help="Release a file lease")
    unlock_p.add_argument("file", help="File path to unlock")
    unlock_p.add_argument("--model", required=True, help="Model identifier")

    # co-review
    cr_p = subparsers.add_parser("co-review", help="Dispatch a co-review message")
    cr_p.add_argument("--from-model", required=True, help="Requesting model")
    cr_p.add_argument("--to-model", required=True, help="Target model (e.g. codex, claude)")
    cr_p.add_argument("--title", required=True, help="Review subject")
    cr_p.add_argument("--body", default="", help="Review details/context")

    # reply
    rep_p = subparsers.add_parser("reply", help="Reply to a co-review or relay message")
    rep_p.add_argument("message_id", help="Message ID to reply to")
    rep_p.add_argument("--decision", default="APPROVED", choices=["APPROVED", "REJECTED", "REVISE"], help="Review decision")
    rep_p.add_argument("--comments", default="", help="Review comments/findings")

    args = parser.parse_args()

    if args.subcommand == "status" or not args.subcommand:
        sys.exit(cmd_status())
    elif args.subcommand == "lock":
        sys.exit(cmd_lock(args.file, args.model, args.ttl, args.task))
    elif args.subcommand == "unlock":
        sys.exit(cmd_unlock(args.file, args.model))
    elif args.subcommand == "co-review":
        sys.exit(cmd_co_review(args.from_model, args.to_model, args.title, args.body))
    elif args.subcommand == "reply":
        sys.exit(cmd_reply(args.message_id, args.decision, args.comments))


if __name__ == "__main__":
    main()
