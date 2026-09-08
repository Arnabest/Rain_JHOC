"""JHOC Unified Cross-Host Trace & Audit CLI.

Provides unified full-lifecycle traceability across:
1. Multi-Model Hub Messages & Intent Envelopes (p19-hub.sqlite)
2. Task Slot State & Baseline Ledger (hub_task_slots)
3. Cryptographic Five-Tuple Tool Blackbox Trace (p19-blackbox.jsonl)
4. Co-Review Evidence Packages (logs/co-review/)
5. Blackbox Hash Chain Integrity Verification (--verify-chain)

Adheres strictly to Rule 1 (Physical Reality), Rule 6 (Evidence), and Rule 7 (Zero Emoji).
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE_ROOT / "src"))

try:
    from jhoc.hub import JHOCMultiModelHub, HubEnvelope
    from jhoc.proof.blackbox import BlackBoxEntry, BlackBoxStepType
except ImportError:
    pass


def _resolve_active_task_id(root: Path) -> str | None:
    """Attempts to resolve the active task_id from memory or hub."""
    v3_state = root / "memory" / "v3_task_state.json"
    if v3_state.is_file():
        try:
            data = json.loads(v3_state.read_text(encoding="utf-8"))
            tid = data.get("task_id")
            if tid:
                return tid
        except Exception:
            pass

    hub_db = root / "logs" / "p19-hub.sqlite"
    if hub_db.is_file():
        try:
            with sqlite3.connect(str(hub_db), timeout=2.0) as conn:
                cur = conn.execute("SELECT task_id FROM hub_task_slots WHERE status = 'ARMED' ORDER BY armed_at DESC LIMIT 1")
                row = cur.fetchone()
                if row:
                    return row[0]
        except Exception:
            pass
    return None


def fetch_blackbox_entries(
    root: Path,
    task_id: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Reads entries from p19-blackbox.jsonl, filtering by task_id if provided."""
    blackbox_path = root / "logs" / "p19-blackbox.jsonl"
    if not blackbox_path.is_file():
        return []

    entries: list[dict[str, Any]] = []
    try:
        with open(blackbox_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line_s = line.strip()
                if not line_s:
                    continue
                try:
                    obj = json.loads(line_s)
                    if task_id:
                        entry_task = obj.get("task_id") or obj.get("content", {}).get("task_id")
                        if entry_task != task_id:
                            continue
                    entries.append(obj)
                except Exception:
                    continue
    except Exception:
        pass

    if limit and len(entries) > limit:
        return entries[-limit:]
    return entries


def fetch_hub_messages(
    root: Path,
    task_id: str | None = None,
    correlation_id: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Reads messages from hub_messages in p19-hub.sqlite."""
    hub_db = root / "logs" / "p19-hub.sqlite"
    if not hub_db.is_file():
        return []

    messages: list[dict[str, Any]] = []
    try:
        with sqlite3.connect(str(hub_db), timeout=2.0) as conn:
            query = "SELECT message_id, source_model, target_model, operation, payload_json, correlation_id, status, created_at, updated_at, reply_payload_json FROM hub_messages WHERE 1=1"
            params: list[Any] = []
            if correlation_id:
                query += " AND correlation_id = ?"
                params.append(correlation_id)
            query += " ORDER BY created_at ASC"

            cur = conn.execute(query, tuple(params))
            for row in cur.fetchall():
                mid, sm, tm, op, pj, cid, st, ca, ua, rpj = row
                p = json.loads(pj) if pj else {}
                rp = json.loads(rpj) if rpj else None
                if task_id:
                    # Match if correlation_id, payload, or reply mentions task_id
                    in_payload = str(task_id) in pj
                    in_reply = str(task_id) in (rpj or "")
                    in_cid = str(task_id) in cid
                    if not (in_payload or in_reply or in_cid):
                        continue
                messages.append({
                    "message_id": mid,
                    "source_model": sm,
                    "target_model": tm,
                    "operation": op,
                    "payload": p,
                    "correlation_id": cid,
                    "status": st,
                    "created_at": ca,
                    "updated_at": ua,
                    "reply_payload": rp,
                })
    except Exception:
        pass

    if limit and len(messages) > limit:
        return messages[-limit:]
    return messages


def fetch_task_slot(root: Path, task_id: str) -> dict[str, Any] | None:
    """Fetches task slot record from hub_task_slots."""
    hub_db = root / "logs" / "p19-hub.sqlite"
    if not hub_db.is_file():
        return None

    try:
        with sqlite3.connect(str(hub_db), timeout=2.0) as conn:
            cur = conn.execute(
                "SELECT task_id, owner_model, title, workspace, baseline_sha, status, armed_at, closed_at FROM hub_task_slots WHERE task_id = ?",
                (task_id,),
            )
            row = cur.fetchone()
            if row:
                return {
                    "task_id": row[0],
                    "owner_model": row[1],
                    "title": row[2],
                    "workspace": row[3],
                    "baseline_sha": row[4],
                    "status": row[5],
                    "armed_at": row[6],
                    "closed_at": row[7],
                }
    except Exception:
        pass
    return None


def fetch_co_reviews(root: Path, task_id: str | None = None) -> list[dict[str, Any]]:
    """Scans logs/co-review/ directory for relevant co-review artifacts."""
    co_dir = root / "logs" / "co-review"
    if not co_dir.is_dir():
        return []

    reviews: list[dict[str, Any]] = []
    for f in sorted(co_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if task_id:
                if data.get("task_id") != task_id and task_id not in f.name:
                    continue
            verdict = data.get("overall_verdict")
            if not verdict:
                # Try extract from sub-reviews
                for key in ("claude_review", "codex_review"):
                    sub = data.get(key, {})
                    v_text = sub.get("verbatim", "")
                    if "[VERDICT]" in v_text:
                        verdict = v_text.split("[VERDICT]")[1].strip().split("\n")[0].strip()
                        break
            if not verdict:
                verdict = "RECORDED"

            reviews.append({
                "file": f.name,
                "path": str(f),
                "timestamp": data.get("timestamp"),
                "task_id": data.get("task_id"),
                "overall_verdict": verdict,
                "audits_conducted": len(data.get("audits", [])) or 2,
                "evidence_hash": data.get("evidence_package_sha256"),
            })
        except Exception:
            continue
    return reviews


def verify_blackbox_hash_chain(root: Path) -> tuple[bool, int, list[str]]:
    """Verifies the unbroken cryptographic SHA-256 hash chain in p19-blackbox.jsonl."""
    import hashlib
    blackbox_path = root / "logs" / "p19-blackbox.jsonl"
    if not blackbox_path.is_file():
        return True, 0, ["[INFO] No blackbox journal found."]

    expected_prev = "0" * 64
    verified_count = 0
    errors: list[str] = []

    with open(blackbox_path, "r", encoding="utf-8", errors="replace") as f:
        for idx, line in enumerate(f, 1):
            line_s = line.strip()
            if not line_s:
                continue
            try:
                obj = json.loads(line_s)
                seq = obj.get("sequence", idx)
                timestamp = obj.get("timestamp", "")
                step_type = obj.get("step_type", "TOOL")
                actor = obj.get("actor", "")
                content = obj.get("content", {})
                prev_hash = obj.get("previous_hash", "")
                entry_hash = obj.get("entry_hash", "")

                if prev_hash != expected_prev:
                    errors.append(
                        f"[FAIL] Broken previous_hash at sequence {seq}: expected {expected_prev[:12]}..., got {prev_hash[:12]}..."
                    )
                    break

                # Recompute hash
                hash_payload_1 = {k: v for k, v in obj.items() if k != "entry_hash"}
                raw_1 = json.dumps(hash_payload_1, sort_keys=True, default=str).encode("utf-8")
                computed_1 = hashlib.sha256(raw_1).hexdigest()

                hash_payload_2 = {k: v for k, v in obj.items() if k not in ("entry_hash", "task_id")}
                raw_2 = json.dumps(hash_payload_2, sort_keys=True, default=str).encode("utf-8")
                computed_2 = hashlib.sha256(raw_2).hexdigest()

                if entry_hash not in (computed_1, computed_2):
                    errors.append(
                        f"[FAIL] Entry hash mismatch at sequence {seq}: expected {entry_hash[:12]}..., computed {computed_1[:12]}..."
                    )
                    break

                expected_prev = entry_hash
                verified_count += 1
            except Exception as ex:
                errors.append(f"[FAIL] Line {idx} corrupt: {ex}")
                break

    is_valid = len(errors) == 0
    return is_valid, verified_count, errors


def print_timeline_human(
    task_slot: dict[str, Any] | None,
    hub_msgs: list[dict[str, Any]],
    blackbox_entries: list[dict[str, Any]],
    co_reviews: list[dict[str, Any]],
) -> None:
    """Prints a clean, zero-emoji ASCII timeline for human inspection."""
    print("=" * 78)
    print("JHOC UNIFIED AUDIT & TRACE TIMELINE")
    print("=" * 78)

    if task_slot:
        print("\n--- [TASK SLOT] ---")
        print(f"Task ID     : {task_slot['task_id']}")
        print(f"Title       : {task_slot['title']}")
        print(f"Owner Model : {task_slot['owner_model']}")
        print(f"Status      : {task_slot['status']}")
        print(f"Baseline SHA: {task_slot['baseline_sha']}")
        print(f"Armed At    : {task_slot['armed_at']}")
        if task_slot.get("closed_at"):
            print(f"Closed At   : {task_slot['closed_at']}")

    if co_reviews:
        print("\n--- [CO-REVIEW ARTIFACTS] ---")
        for cr in co_reviews:
            print(f"- [{cr.get('overall_verdict', 'UNKNOWN')}] {cr['file']} (Audits: {cr['audits_conducted']})")
            if cr.get("evidence_hash"):
                print(f"  Evidence SHA-256: {cr['evidence_hash']}")

    if hub_msgs:
        print(f"\n--- [HUB MESSAGES & INTENTS] ({len(hub_msgs)} events) ---")
        for m in hub_msgs:
            ts = m.get("created_at", "")[:19]
            sm = m.get("source_model", "")
            tm = m.get("target_model", "")
            op = m.get("operation", "")
            status = m.get("status", "")
            payload_summary = ""
            p = m.get("payload", {})
            if op == "INTENT_DETECTED":
                payload_summary = f"Intent: {p.get('intent')} (Tier {p.get('tier')})"
            else:
                payload_summary = f"Payload keys: {list(p.keys())}"
            print(f"[{ts}] {sm} -> {tm} | {op:<18} | Status: {status:<10} | {payload_summary}")

    if blackbox_entries:
        print(f"\n--- [BLACKBOX TOOL AUDIT TRAIL] ({len(blackbox_entries)} events) ---")
        for b in blackbox_entries:
            ts = b.get("timestamp", "")[:19]
            seq = b.get("sequence", 0)
            actor = b.get("actor", "")
            c = b.get("content", {})
            tool = c.get("tool", "")
            decision = c.get("decision", "unknown").upper()
            reason = c.get("reason", "")[:60]
            tag = "[PASS]" if decision == "ALLOW" else "[BLOCK]"
            print(f"#{seq:<4} [{ts}] {tag:<7} {actor:<16} | Tool: {tool:<24} | {reason}")

    print("\n" + "=" * 78)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="JHOC Unified Audit & Trace CLI")
    parser.add_argument("--task", "--task-id", dest="task_id", help="Filter by Task ID (defaults to active task if available)")
    parser.add_argument("--corr", "--correlation-id", dest="corr_id", help="Filter Hub messages by Correlation ID")
    parser.add_argument("--tail", type=int, default=20, help="Number of recent events to display (default: 20)")
    parser.add_argument("--verify-chain", action="store_true", help="Verify cryptographic SHA-256 blackbox hash chain")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON format")
    parser.add_argument("--root", default=str(WORKSPACE_ROOT), help="JHOC workspace root directory")

    args = parser.parse_args(argv)
    root = Path(args.root).resolve()

    # Verify chain mode
    if args.verify_chain:
        is_valid, count, errors = verify_blackbox_hash_chain(root)
        if args.json:
            print(json.dumps({"valid": is_valid, "verified_entries": count, "errors": errors}, indent=2))
        else:
            if is_valid:
                print(f"[PASS] BlackBox hash chain verified: {count} entries unbroken.")
            else:
                print(f"[FAIL] BlackBox hash chain corrupted! Verified {count} entries before failure:")
                for err in errors:
                    print(f"  {err}")
        return 0 if is_valid else 1

    # Resolve target task_id
    target_task_id = args.task_id
    if not target_task_id and not args.corr_id:
        target_task_id = _resolve_active_task_id(root)

    # Gather artifacts
    task_slot = fetch_task_slot(root, target_task_id) if target_task_id else None
    hub_msgs = fetch_hub_messages(root, task_id=target_task_id, correlation_id=args.corr_id, limit=args.tail)
    blackbox = fetch_blackbox_entries(root, task_id=target_task_id, limit=args.tail)
    co_reviews = fetch_co_reviews(root, task_id=target_task_id)

    if args.json:
        out = {
            "query": {
                "task_id": target_task_id,
                "correlation_id": args.corr_id,
                "tail": args.tail,
            },
            "task_slot": task_slot,
            "hub_messages": hub_msgs,
            "blackbox_entries": blackbox,
            "co_reviews": co_reviews,
        }
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        print_timeline_human(task_slot, hub_msgs, blackbox, co_reviews)

    return 0


if __name__ == "__main__":
    sys.exit(main())
