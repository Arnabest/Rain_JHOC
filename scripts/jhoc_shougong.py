"""JHOC Shougong - Post-flight closure verification and environment cleanup."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
_EMOJI_RE = re.compile(r"[\U00010000-\U0010ffff]|[\u2600-\u27bf]|[\u2300-\u23ff]")


def run_command(cmd: list[str], label: str) -> bool:
    print(f"[CHECK] Running {label} ({' '.join(cmd)})...")
    res = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    if res.returncode != 0:
        print(f"[FAIL] {label} failed with code {res.returncode}:\n{res.stderr or res.stdout}")
        return False
    print(f"[PASS] {label} passed.")
    return True


def check_git_modified_emojis() -> tuple[bool, str]:
    try:
        res = subprocess.run(
            ["git", "diff", "HEAD"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        if res.returncode == 0 and res.stdout:
            added_lines = [l for l in res.stdout.splitlines() if l.startswith("+") and not l.startswith("+++")]
            for l in added_lines:
                emojis = _EMOJI_RE.findall(l)
                if emojis:
                    return False, f"Rule 7 Violation: Uncommitted changes contain emojis -> {set(emojis)}"
        return True, "Diff checked: Zero emojis in added lines"
    except Exception as e:
        return False, f"Git diff error: {e}"


def record_shougong_failure(reason: str, details: str = "") -> None:
    try:
        sys.path.insert(0, str(ROOT / "src"))
        from jhoc.memory_store import MemoryRecord, MemoryType, SQLiteMemoryStore
        mem_db = ROOT / "logs" / "p19-memory.sqlite"
        store = SQLiteMemoryStore(str(mem_db))
        rec = MemoryRecord(
            content={
                "error_type": "SHOUGONG_FAILURE",
                "reason": reason,
                "details": details,
                "failed_at": datetime.now(timezone.utc).isoformat(),
            },
            memory_type=MemoryType.ERROR,
            source_ref="scripts/jhoc_shougong.py",
            sensitivity="INTERNAL",
            project_id="jhoc",
        )
        store.write(rec, approved=True)
        store.close()
    except Exception:
        pass

    try:
        timeline_file = ROOT / "memory" / "task_timeline.jsonl"
        event = {
            "event": "SHOUGONG_FAILURE",
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        with timeline_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=True) + "\n")
    except Exception:
        pass


def run_shougong(archive: bool = True, force: bool = False) -> int:
    print("=== [JHOC SHOUGONG POST-FLIGHT CLOSURE] ===")

    # Step 1: Detect active task and enforce ARMED state precondition
    state_file = ROOT / "memory" / "v3_task_state.json"
    task_id = "unknown"
    state: dict = {}
    if state_file.is_file():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
            task_id = state.get("task_id", "unknown")
        except Exception:
            pass

    current_status = state.get("status", "NONE")
    if current_status != "ARMED" and not force:
        print(f"[FAIL] Precondition Failed: Task {task_id} is not in ARMED state (current: {current_status}).")
        print("[FAIL] Cannot run shougong on an idle or already closed workspace. Run kaigong first (or use --force).")
        return 1

    print(f"[INFO] Closing active task: {task_id}")

    # Step 2: Run schema verification
    if not run_command([sys.executable, "scripts/validate_schemas.py"], "Schema Validation"):
        record_shougong_failure("Schema Validation Failed")
        return 1

    # Step 3: Run full unit test suite
    if not run_command([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"], "Unit Tests"):
        record_shougong_failure("Unit Tests Failed")
        return 1

    # Step 4: Run acceptance checks
    if not run_command([sys.executable, "scripts/validate_acceptance_artifacts.py"], "Acceptance Checks"):
        record_shougong_failure("Acceptance Checks Failed")
        return 1

    # Step 5: Check emoji discipline in diff
    ok_emoji, msg_emoji = check_git_modified_emojis()
    print(f"[{'PASS' if ok_emoji else 'FAIL'}] {msg_emoji}")
    if not ok_emoji:
        record_shougong_failure("Emoji Discipline Violation", msg_emoji)
        return 1

    # Step 5.5: Global write freeze during final handoff & state closure
    lock_file = ROOT / "runtime" / "write_freeze.lock"
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    lock_file.write_text(f"frozen_by_shougong:{task_id}", encoding="utf-8")

    try:
        # Step 6: Mark state as CLOSED and generate Inter-Model Handoff package
        now_iso = datetime.now(timezone.utc).isoformat()
        if state_file.is_file():
            state["status"] = "CLOSED"
            state["closed_at"] = now_iso
            state_file.write_text(json.dumps(state, indent=2, ensure_ascii=True), encoding="utf-8")

        handoff_pkg = {
            "task_id": task_id,
            "title": state.get("title", ""),
            "closed_at": now_iso,
            "status": "CLOSED",
            "workspace": str(ROOT),
            "git_baseline_sha": state.get("git_baseline_sha", ""),
            "pending_actions": state.get("pending_actions", []),
            "summary": f"Task '{state.get('title', '')}' closed successfully with all tests passing.",
        }
        handoff_file = ROOT / "memory" / "handoff-latest.json"
        handoff_file.parent.mkdir(parents=True, exist_ok=True)
        handoff_file.write_text(json.dumps(handoff_pkg, indent=2, ensure_ascii=True), encoding="utf-8")
        print(f"[PASS] Inter-Model Handoff Package generated: {handoff_file.name}")

        # Step 6.5: Release File Leases & Close Task Slot in Multi-Model Hub
        try:
            sys.path.insert(0, str(ROOT / "src"))
            from jhoc.hub import JHOCMultiModelHub, ModelPresenceState
            hub = JHOCMultiModelHub(ROOT / "logs" / "p19-hub.sqlite")
            released_cnt = hub.release_all_leases("antigravity-ide")
            hub.close_task_slot(task_id, "antigravity-ide")
            hub.register_presence("antigravity-ide", ModelPresenceState.IDLE, task_id=None)
            print(f"[PASS] Multi-Model Hub updated: {released_cnt} file leases released, presence set to IDLE.")
        except Exception:
            pass
    finally:
        if lock_file.is_file():
            try:
                lock_file.unlink()
            except Exception:
                pass

    print(f"[PASS] All post-flight checks passed. Task {task_id} closed.")
    print("shougong: SUCCESS")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="JHOC Post-flight Shougong Closure")
    parser.add_argument("--no-archive", action="store_true", help="Skip archiving state")
    parser.add_argument("--force", action="store_true", help="Force closure even if task is not in ARMED state")
    args = parser.parse_args()

    sys.exit(run_shougong(archive=not args.no_archive, force=args.force))


if __name__ == "__main__":
    main()
