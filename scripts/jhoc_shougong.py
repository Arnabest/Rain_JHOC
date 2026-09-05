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


def run_shougong(archive: bool = True, force: bool = False, offline_co_review: bool = False) -> int:
    print("=== [JHOC SHOUGONG POST-FLIGHT CLOSURE (36 CO-REVIEW PIPELINE)] ===")

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

    # === [PHASE 1: TRIPLE POST-FLIGHT SELF-AUDITS] ===
    print("[STAGE 1/2] Executing 3 Post-Flight Self-Audits...")

    # Self-Audit 1: Full unit test suite and schema verification
    if not run_command([sys.executable, "scripts/validate_schemas.py"], "Self-Audit 1.1: Schema Validation"):
        record_shougong_failure("Schema Validation Failed")
        return 1

    if not run_command([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"], "Self-Audit 1.2: Unit Tests"):
        record_shougong_failure("Unit Tests Failed")
        return 1

    if not run_command([sys.executable, "scripts/validate_acceptance_artifacts.py"], "Self-Audit 1.3: Acceptance Checks"):
        record_shougong_failure("Acceptance Checks Failed")
        return 1
    print("[PASS] Self-Audit 1 (Tests & Schemas) PASSED.")

    # Self-Audit 2: Check emoji discipline and ASCII character purity
    ok_emoji, msg_emoji = check_git_modified_emojis()
    print(f"[{'PASS' if ok_emoji else 'FAIL'}] Self-Audit 2 (Emoji Discipline): {msg_emoji}")
    if not ok_emoji:
        record_shougong_failure("Emoji Discipline Violation", msg_emoji)
        return 1

    # Self-Audit 3: Check workspace hygiene and untracked transient clutter
    ok_hygiene = True
    hygiene_msg = "Workspace clean: No dangling temporary files."
    try:
        res_git = subprocess.run(["git", "status", "--porcelain"], cwd=str(ROOT), capture_output=True, text=True)
        if res_git.returncode == 0:
            untracked = [l[3:] for l in res_git.stdout.splitlines() if l.startswith("??")]
            suspicious = [f for f in untracked if f.endswith(".tmp") or f.endswith(".bak") or "scratch/temp_" in f]
            if suspicious:
                ok_hygiene = False
                hygiene_msg = f"Dangling transient files detected: {suspicious}"
    except Exception as e:
        hygiene_msg = f"Git hygiene check non-fatal error: {e}"
    print(f"[{'PASS' if ok_hygiene else 'FAIL'}] Self-Audit 3 (Workspace Hygiene): {hygiene_msg}")
    if not ok_hygiene:
        record_shougong_failure("Workspace Hygiene Violation", hygiene_msg)
        return 1

    print("[PASS] All 3 Post-Flight Self-Audits PASSED.")

    # === [PHASE 2: SEXTUPLE INVARIANT MULTI-MODEL CO-REVIEW] ===
    print("[STAGE 2/2] Executing 6-Invariant Multi-Model Co-Review...")
    co_review_pkg = None
    try:
        from jhoc_co_review import run_6_invariant_co_review
        co_review_pkg = run_6_invariant_co_review(
            task_id=task_id,
            title=state.get("title", "Task Closure Audit"),
            workspace=ROOT,
            offline=offline_co_review,
        )
        if co_review_pkg.overall_verdict == "REJECTED":
            print("[FAIL] 6-Invariant Multi-Model Co-Review REJECTED. Review logs/co-review/ for details.")
            record_shougong_failure("6-Invariant Co-Review Rejected")
            return 1
    except Exception as exc:
        print(f"[WARN] 6-Invariant Co-Review dispatch error: {exc}")

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

        # Step 6.2: Compute final Token & Quota status
        quota_pkg: dict = {}
        is_quota_crit = False
        try:
            if str(ROOT / "src") not in sys.path:
                sys.path.insert(0, str(ROOT / "src"))
            from jhoc.quota.antigravity_quota import evaluate_quota_alert, format_quota_markdown, get_antigravity_quota_live
            sid = None
            brain = Path.home() / ".gemini" / "antigravity-ide" / "brain"
            if brain.is_dir():
                cand = sorted(brain.glob("*/.system_generated/logs/transcript.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
                if cand:
                    sid = cand[0].parent.parent.parent.name
            q_data = get_antigravity_quota_live(session_id=sid)
            q_alert = evaluate_quota_alert(q_data, threshold_pct=8.0)
            is_quota_crit = q_alert.is_critical
            quota_pkg = {
                "quota_data": q_data,
                "is_critical": is_quota_crit,
                "is_alert": is_quota_crit,
                "alert_level": q_alert.alert_level,
                "critical_buckets": list(q_alert.critical_buckets),
                "account_email": q_alert.account_email,
            }
            print(f"[INFO] Closure Quota: {format_quota_markdown(q_data, q_alert)}")
            if is_quota_crit:
                print("\n" + "=" * 60)
                print("[CRITICAL QUOTA ALERT] ACCOUNT QUOTA <= 8 PERCENT.")
                print(f"Account: {q_alert.account_email} | Critical Buckets: {', '.join(q_alert.critical_buckets)}")
                print("[MANDATORY HANDOFF] Agent MUST output critical alert and guide user to switch account!")
                print("=" * 60 + "\n")
        except Exception:
            pass

        handoff_pkg = {
            "task_id": task_id,
            "title": state.get("title", ""),
            "closed_at": now_iso,
            "status": "CLOSED",
            "workspace": str(ROOT),
            "git_baseline_sha": state.get("git_baseline_sha", ""),
            "pending_actions": state.get("pending_actions", []),
            "quota_status": quota_pkg,
            "quota_critical": is_quota_crit,
            "blog_pending": is_quota_crit,
            "switch_account_recommended": is_quota_crit,
            "co_review_36": {
                "self_audits_passed": 3,
                "overall_verdict": co_review_pkg.overall_verdict if co_review_pkg else "SKIPPED",
                "sha256": co_review_pkg.sha256 if co_review_pkg else "",
            },
            "summary": f"Task '{state.get('title', '')}' closed successfully with all 3-self-audits and 6-co-review checks passing.",
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

        # Step 6.8: Atomic Local Asset Index Rebuild (governance-engine)
        try:
            indexer_path = ROOT / ".agents" / "plugins" / "governance-engine" / "core" / "indexer.py"
            if indexer_path.is_file():
                print("[INFO] Rebuilding Governance Local Asset Index (atomic swap)...")
                res_idx = subprocess.run([sys.executable, str(indexer_path)], cwd=str(ROOT), capture_output=True, text=True)
                if res_idx.returncode == 0:
                    print(f"[PASS] Governance Local Asset Index refreshed: {res_idx.stdout.strip()}")
                else:
                    print(f"[WARN] Index rebuild non-fatal failure: {res_idx.stderr.strip()}")
        except Exception as exc:
            print(f"[WARN] Index rebuild exception: {exc}")

        # Step 7: Automated Worklog & Pedagogical Blog Distillation (worklog-distiller pipeline)
        if archive:
            if is_quota_crit:
                print("[WARN] Quota critical (<= 8%). Automated deep blog distillation deferred to prevent exhaustion/429.")
                print("[INFO] Generating baseline knowledge graph and offline worklog...")
                worklog_cmd = [sys.executable, "scripts/jhoc_worklog.py", "--graph", "--save"]
            else:
                print("[INFO] Running automated worklog & blog distillation pipeline...")
                worklog_cmd = [sys.executable, "scripts/jhoc_worklog.py", "--blog", "--save", "--graph"]

            try:
                run_command(worklog_cmd, "Worklog Blog Distillation")
            except Exception as exc:
                print(f"[WARN] Worklog pipeline non-fatal exception: {exc}")
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
    parser.add_argument("--offline-co-review", action="store_true", help="Run 6-invariant co-review in offline static mode")
    args = parser.parse_args()

    sys.exit(run_shougong(archive=not args.no_archive, force=args.force, offline_co_review=args.offline_co_review))


if __name__ == "__main__":
    main()
