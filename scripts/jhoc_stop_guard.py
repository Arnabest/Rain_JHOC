"""JHOC Lifecycle Stop Guard - Intercepts agent termination if task is still ARMED."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent


def evaluate_stop(payload: dict) -> dict:
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
                return {"decision": "allow"}
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
