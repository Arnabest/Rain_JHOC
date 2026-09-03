from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parent.parent


def get_task_stats() -> dict[str, int]:
    timeline_file = ROOT / "memory" / "task_timeline.jsonl"
    stats = {"total_events": 0, "armed": 0, "closed": 0, "failed": 0}
    if not timeline_file.is_file():
        return stats
    for line in timeline_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            stats["total_events"] += 1
            st = data.get("status") or data.get("event")
            if st == "ARMED":
                stats["armed"] += 1
            elif st == "CLOSED":
                stats["closed"] += 1
            elif st in ("FAILED", "SHOUGONG_FAILURE"):
                stats["failed"] += 1
        except Exception:
            pass
    return stats


def get_blackbox_stats() -> tuple[dict[str, int], Counter[str], dict[str, dict[str, int]]]:
    bb_file = ROOT / "logs" / "p19-blackbox.jsonl"
    stats = {"total_tool_calls": 0, "allowed": 0, "denied": 0}
    deny_reasons: Counter[str] = Counter()
    model_tool_stats: dict[str, dict[str, int]] = {}
    if not bb_file.is_file():
        return stats, deny_reasons, model_tool_stats
    for line in bb_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            stats["total_tool_calls"] += 1
            content = entry.get("content", {})
            decision = content.get("decision", "allow")
            actor = entry.get("actor") or content.get("actor") or "antigravity-ide"
            if actor not in model_tool_stats:
                model_tool_stats[actor] = {"total": 0, "allowed": 0, "denied": 0}
            model_tool_stats[actor]["total"] += 1
            if decision == "allow":
                stats["allowed"] += 1
                model_tool_stats[actor]["allowed"] += 1
            else:
                stats["denied"] += 1
                model_tool_stats[actor]["denied"] += 1
                r = content.get("reason", "unknown")
                # Group reason prefix
                r_prefix = r.split(":")[0].strip() if ":" in r else r[:30]
                deny_reasons[r_prefix] += 1
        except Exception:
            pass
    return stats, deny_reasons, model_tool_stats


def get_approval_stats() -> dict[str, int]:
    inbox_db = ROOT / "runtime" / "inbox.db"
    stats = {"total_tickets": 0, "pending": 0, "approved": 0, "rejected": 0}
    if not inbox_db.is_file():
        return stats
    try:
        with sqlite3.connect(inbox_db) as conn:
            rows = conn.execute("SELECT status, COUNT(*) FROM jhoc_approval_inbox GROUP BY status").fetchall()
            for status, count in rows:
                stats["total_tickets"] += count
                s_lower = status.lower()
                if s_lower in stats:
                    stats[s_lower] = count
    except Exception:
        pass
    return stats


def get_vault_stats() -> tuple[dict[str, int], Counter[str]]:
    vault_log = ROOT / "logs" / "audit" / "vault-access.jsonl"
    stats = {"total_egress_events": 0}
    model_egress: Counter[str] = Counter()
    if not vault_log.is_file():
        return stats, model_egress
    try:
        for line in vault_log.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            stats["total_egress_events"] += 1
            caller = data.get("caller_model") or data.get("actor") or "antigravity-ide"
            model_egress[caller] += 1
    except Exception:
        pass
    return stats, model_egress


def get_hub_multi_model_stats() -> dict[str, Any]:
    hub_db = ROOT / "logs" / "p19-hub.sqlite"
    res = {
        "online_models": {},
        "tasks_per_model": Counter(),
        "leases_per_model": Counter(),
        "messages_sent": Counter(),
        "messages_received": Counter(),
    }
    if not hub_db.is_file():
        return res
    try:
        with sqlite3.connect(str(hub_db)) as conn:
            # Presence
            rows = conn.execute("SELECT model_id, state, task_id, last_heartbeat FROM hub_presence").fetchall()
            for mid, st, tid, hb in rows:
                res["online_models"][mid] = {"state": st, "task_id": tid, "last_heartbeat": hb}

            # Tasks
            t_rows = conn.execute("SELECT owner_model, COUNT(*) FROM hub_task_slots GROUP BY owner_model").fetchall()
            for om, cnt in t_rows:
                res["tasks_per_model"][om] = cnt

            # Active leases
            l_rows = conn.execute("SELECT locked_by_model, COUNT(*) FROM hub_file_leases WHERE status = 'ACTIVE' GROUP BY locked_by_model").fetchall()
            for lm, cnt in l_rows:
                res["leases_per_model"][lm] = cnt

            # Messages
            m_rows = conn.execute("SELECT source_model, target_model, status FROM hub_messages").fetchall()
            for sm, tm, st in m_rows:
                res["messages_sent"][sm] += 1
                res["messages_received"][tm] += 1
    except Exception:
        pass
    return res


def main() -> None:
    parser = argparse.ArgumentParser(description="JHOC Operational Log & Audit Statistics Dashboard")
    parser.add_argument("--json", action="store_true", help="Output raw JSON metrics")
    parser.add_argument("--gates", action="store_true", help="Show gate denial ranking details")
    args = parser.parse_args()

    task_stats = get_task_stats()
    bb_stats, deny_reasons, model_tool_stats = get_blackbox_stats()
    approval_stats = get_approval_stats()
    vault_stats, model_vault_stats = get_vault_stats()
    hub_stats = get_hub_multi_model_stats()

    metrics = {
        "tasks": task_stats,
        "blackbox_gate": bb_stats,
        "model_tool_attribution": model_tool_stats,
        "approvals": approval_stats,
        "vault_egress": vault_stats,
        "model_vault_egress": dict(model_vault_stats),
        "hub_attribution": {
            "online_models": hub_stats["online_models"],
            "tasks_per_model": dict(hub_stats["tasks_per_model"]),
            "leases_per_model": dict(hub_stats["leases_per_model"]),
            "messages_sent": dict(hub_stats["messages_sent"]),
            "messages_received": dict(hub_stats["messages_received"]),
        },
        "top_gate_denials": dict(deny_reasons.most_common(5)),
    }

    if args.json:
        print(json.dumps(metrics, indent=2, ensure_ascii=True))
        return

    print("======================================================================")
    print("                     JHOC OPERATIONAL AUDIT DASHBOARD                  ")
    print("======================================================================")
    print("1. Task Execution Stream (memory/task_timeline.jsonl):")
    print(f"   - Total Events   : {task_stats['total_events']}")
    print(f"   - Tasks Armed    : {task_stats['armed']}")
    print(f"   - Tasks Closed   : {task_stats['closed']}")
    print(f"   - Task Failures  : {task_stats['failed']}")
    print()
    print("2. Tool Gate & BlackBox Ledger (logs/p19-blackbox.jsonl):")
    print(f"   - Total Tool Calls : {bb_stats['total_tool_calls']}")
    print(f"   - Allowed Actions  : {bb_stats['allowed']}")
    print(f"   - Denied Actions   : {bb_stats['denied']}")
    print()
    print("3. Human Approval Inbox (runtime/inbox.db):")
    print(f"   - Total Tickets  : {approval_stats['total_tickets']}")
    print(f"   - Pending Review : {approval_stats['pending']}")
    print(f"   - Approved       : {approval_stats['approved']}")
    print(f"   - Rejected       : {approval_stats['rejected']}")
    print()
    print("4. Credential Vault Egress (logs/audit/vault-access.jsonl):")
    print(f"   - Total Egress Resolutions: {vault_stats['total_egress_events']}")
    print()
    if args.gates or deny_reasons:
        print("5. Top Gate Denial Categories:")
        if not deny_reasons:
            print("   - No gate denials recorded.")
        else:
            for cat, count in deny_reasons.most_common(5):
                print(f"   - {cat}: {count} times")
        print()

    print("6. Multi-Model Attribution Breakdown:")
    all_models = sorted(set(
        list(model_tool_stats.keys())
        + list(hub_stats["online_models"].keys())
        + list(hub_stats["tasks_per_model"].keys())
        + list(hub_stats["leases_per_model"].keys())
        + list(model_vault_stats.keys())
    ))
    if not all_models:
        print("   - No multi-model activity recorded yet.")
    else:
        for m in all_models:
            t_data = model_tool_stats.get(m, {"total": 0, "allowed": 0, "denied": 0})
            tasks_cnt = hub_stats["tasks_per_model"].get(m, 0)
            leases_cnt = hub_stats["leases_per_model"].get(m, 0)
            msg_sent = hub_stats["messages_sent"].get(m, 0)
            msg_recv = hub_stats["messages_received"].get(m, 0)
            vault_cnt = model_vault_stats.get(m, 0)
            online_info = hub_stats["online_models"].get(m, {})
            state_str = online_info.get("state", "OFFLINE")

            print(f"   -> [{m}] Status: {state_str}")
            print(f"      - Tool Calls    : {t_data['total']} (Allow: {t_data['allowed']}, Deny: {t_data['denied']})")
            print(f"      - Tasks Armed   : {tasks_cnt}")
            print(f"      - Active Leases : {leases_cnt}")
            print(f"      - Relay Traffic : {msg_sent} sent, {msg_recv} received")
            print(f"      - Vault Egress  : {vault_cnt} resolutions")
    print("======================================================================")


if __name__ == "__main__":
    main()
