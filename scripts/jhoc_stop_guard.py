"""JHOC Lifecycle Stop Guard - Intercepts agent termination if task is still ARMED."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent


def evaluate_stop(payload: dict) -> dict:
    # Escape hatch: force stop override
    if payload.get("force") or os.environ.get("JHOC_FORCE_STOP"):
        return {"decision": "allow", "reason": "Forced stop override triggered."}

    state_file = ROOT / "memory" / "v3_task_state.json"
    if state_file.is_file():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
            status = state.get("status", "")
            task_id = state.get("task_id", "unknown")
            title = state.get("title", "")

            if status == "ARMED":
                return {
                    "decision": "continue",
                    "reason": (
                        f"[JHOC LIFECYCLE GUARD] Active task '{title}' ({task_id}) is still ARMED. "
                        "You must execute post-flight closure by running 'python scripts/jhoc_shougong.py' "
                        "to verify full tests and generate archive status and token usage before stopping."
                    ),
                }
            elif status == "CLOSED":
                pass
        except Exception as e:
            # Fail-closed on corrupted task state
            return {
                "decision": "continue",
                "reason": (
                    f"[JHOC LIFECYCLE GUARD] Corrupted task state file detected ({e}). "
                    "You must run 'python scripts/jhoc_shougong.py' to repair and cleanly close before stopping."
                ),
            }

    # Dual-plane fallback check: Hub presence
    hub_db = ROOT / "logs" / "p19-hub.sqlite"
    if hub_db.is_file():
        try:
            import sqlite3
            with sqlite3.connect(str(hub_db)) as conn:
                row = conn.execute("SELECT state, task_id FROM hub_presence WHERE model_id = 'antigravity-ide'").fetchone()
                if row and row[0] == "CODING":
                    return {
                        "decision": "continue",
                        "reason": (
                            f"[JHOC LIFECYCLE GUARD] Multi-Model Hub shows model 'antigravity-ide' is actively CODING "
                            f"(Task: {row[1] or 'untracked'}). You must execute post-flight closure by running "
                            "'python scripts/jhoc_shougong.py' before stopping."
                        ),
                    }
        except Exception:
            pass

    # Quota Critical Stop Guard: Prevent stopping without handoff when quota <= 8%
    if not payload.get("skip_quota_check") and not os.environ.get("JHOC_SKIP_QUOTA_CHECK"):
        try:
            if str(ROOT / "src") not in sys.path:
                sys.path.insert(0, str(ROOT / "src"))
            from jhoc.quota.antigravity_quota import evaluate_quota_alert, get_antigravity_quota_live

            cid = payload.get("conversationId") or payload.get("session_id")
            if not cid:
                brain = Path.home() / ".gemini" / "antigravity-ide" / "brain"
                if brain.is_dir():
                    cand = sorted(brain.glob("*/.system_generated/logs/transcript.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
                    if cand:
                        cid = cand[0].parent.parent.parent.name

            q_data = get_antigravity_quota_live(session_id=cid)
            alert = evaluate_quota_alert(q_data, threshold_pct=8.0)
            if alert.is_critical:
                handoff_file = ROOT / "memory" / "handoff-latest.json"
                needs_handoff = True
                if handoff_file.is_file():
                    try:
                        import time
                        ho_data = json.loads(handoff_file.read_text(encoding="utf-8"))
                        mtime = handoff_file.stat().st_mtime
                        is_fresh = (time.time() - mtime) < 1800  # Fresh within 30 minutes
                        is_alert_marked = (
                            ho_data.get("quota_status", {}).get("is_alert") is True
                            or ho_data.get("quota_status", {}).get("is_critical") is True
                            or ho_data.get("quota_critical") is True
                        )
                        if is_fresh and is_alert_marked:
                            needs_handoff = False
                    except Exception:
                        needs_handoff = True

                if needs_handoff:
                    return {
                        "decision": "continue",
                        "reason": (
                            f"[QUOTA CRITICAL STOP BLOCKED] 当前账户 '{alert.account_email}' 配额已低于 8% 临界阈值 "
                            f"(告急项: {', '.join(alert.critical_buckets)}) 且未生成当次有效的新鲜 memory/handoff-latest.json 紧急交接包！"
                            "禁止直接停机，必须先运行 'py -3 scripts/jhoc_shougong.py' 或沉淀交接包以完成跨模型交接。"
                        ),
                    }
        except Exception:
            pass

    return {"decision": "allow"}


def main() -> None:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        payload = {}

    res = evaluate_stop(payload)
    print(json.dumps(res, ensure_ascii=True))


if __name__ == "__main__":
    main()
