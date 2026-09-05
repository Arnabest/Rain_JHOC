"""JHOC Kaigong - Pre-flight hard gate check and task context registration."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys

JHOC_ROOT = Path(__file__).resolve().parents[1]
_EMOJI_RE = re.compile(r"[\U00010000-\U0010ffff]|[\u2600-\u27bf]|[\u2300-\u23ff]")


def check_workspace(target_root: Path) -> tuple[bool, str]:
    resolved = target_root.resolve()
    if not resolved.exists() or not resolved.is_dir():
        return False, f"Invalid workspace root: {resolved} (Directory does not exist)"
    # Valid if it is JHOC itself or has AGENTS.md / .agents or git repo
    has_agents_md = (resolved / "AGENTS.md").is_file()
    has_git = (resolved / ".git").exists()
    has_agents_dir = (resolved / ".agents").is_dir()
    if not (has_agents_md or has_git or has_agents_dir):
        return False, f"Target workspace {resolved} is neither a git repository nor initialized with AGENTS.md"
    return True, f"Workspace verified: {resolved}"


def check_git_status(target_root: Path) -> tuple[bool, str]:
    try:
        res = subprocess.run(
            ["git", "status", "-s"],
            cwd=str(target_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
        if res.returncode != 0:
            return False, f"Git status failed in {target_root} with code {res.returncode}"
        lines = [line.strip() for line in res.stdout.splitlines() if line.strip()]
        return True, f"Git tracking active in {target_root.name} ({len(lines)} modified/untracked files)"
    except Exception as e:
        return False, f"Git error in {target_root}: {e}"


def get_git_commit_sha(target_root: Path) -> str:
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(target_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
    return "UNKNOWN_COMMIT"


def check_zero_emoji_discipline(target_root: Path) -> tuple[bool, str]:
    # Check governance files in target workspace and JHOC core
    scan_files: list[Path] = [JHOC_ROOT / "AGENTS.md", *(JHOC_ROOT / ".agents" / "rules").glob("*.md")]
    if (target_root / "AGENTS.md").is_file():
        scan_files.append(target_root / "AGENTS.md")
    if (target_root / ".agents" / "rules").is_dir():
        scan_files.extend((target_root / ".agents" / "rules").glob("*.md"))

    for p in scan_files:
        if p.is_file():
            txt = p.read_text(encoding="utf-8", errors="ignore")
            matches = _EMOJI_RE.findall(txt)
            if matches:
                return False, f"Rule 7 Violation: {p} contains {len(matches)} emojis"
    return True, "Zero-Emoji Discipline verified across active governance files"


def run_kaigong(
    title: str,
    body: str = "",
    workspace: Path | None = None,
    force: bool = False,
    inquiry: bool = False,
    inquiry_confirmed: bool = False,
) -> int:
    print("=== [JHOC KAIGONG PRE-FLIGHT GATE] ===")
    target_root = (workspace or Path.cwd()).resolve()
    now_utc = datetime.now(timezone.utc)
    ts_str = now_utc.strftime("%Y%m%dT%H%M%SZ")
    slug = re.sub(r"[^\w\-]", "_", title)[:40].strip("_").lower() or "task"
    task_id = f"{ts_str}-{slug}"

    # Step 1: Check workspace physical boundary
    ok_ws, msg_ws = check_workspace(target_root)
    print(f"[{'PASS' if ok_ws else 'FAIL'}] {msg_ws}")
    if not ok_ws:
        print("gate: DENIED (workspace boundary failure)")
        return 1

    # Step 2: Check Git status
    ok_git, msg_git = check_git_status(target_root)
    print(f"[{'PASS' if ok_git else 'FAIL'}] {msg_git}")

    # Step 3: Check Zero-Emoji Discipline
    ok_emoji, msg_emoji = check_zero_emoji_discipline(target_root)
    print(f"[{'PASS' if ok_emoji else 'FAIL'}] {msg_emoji}")
    if not ok_emoji:
        print("gate: DENIED (emoji discipline violation)")
        return 1

    # Step 3.5: Pre-flight Account Quota & Critical Threshold Inspection
    try:
        if str(JHOC_ROOT / "src") not in sys.path:
            sys.path.insert(0, str(JHOC_ROOT / "src"))
        from jhoc.quota.antigravity_quota import evaluate_quota_alert, get_antigravity_quota_live
        # Auto-detect latest active Antigravity session if present
        sid = None
        brain = Path.home() / ".gemini" / "antigravity-ide" / "brain"
        if brain.is_dir():
            cand = sorted(brain.glob("*/.system_generated/logs/transcript.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
            if cand:
                sid = cand[0].parent.parent.parent.name
        quota_data = get_antigravity_quota_live(session_id=sid)
        alert = evaluate_quota_alert(quota_data, threshold_pct=8.0)
        if alert.is_critical:
            print(f"{alert.warning_message}")
            if not force:
                print("gate: DENIED (quota critical <= 8.0%. Use --force to override)")
                return 1
        elif quota_data and quota_data.get("enabled"):
            email = quota_data.get("account_email", "")
            g5 = quota_data.get("gemini_5h_pct", 100)
            gw = quota_data.get("gemini_weekly_pct", 100)
            print(f"[INFO] Quota Status: [{email}] 5H: {g5}% · Weekly: {gw}% (Healthy)")
    except Exception:
        pass

    # Step 4: Display Active Shelf capabilities to guide model against reinventing the wheel
    canonical_skills = sorted(p.name for p in (JHOC_ROOT / ".agents" / "skills").iterdir() if p.is_dir())
    print(f"[INFO] Active Shelf: {', '.join(canonical_skills)}")

    # Step 5: Capture Git Baseline Commit SHA (with Re-entrance Protection)
    mem_dir = target_root / "memory"
    mem_dir.mkdir(parents=True, exist_ok=True)
    state_file = mem_dir / "v3_task_state.json"

    commit_sha = get_git_commit_sha(target_root)
    if state_file.is_file() and not force:
        try:
            cur_state = json.loads(state_file.read_text(encoding="utf-8"))
            if cur_state.get("status") == "ARMED":
                prev_id = cur_state.get("task_id", "unknown")
                prev_sha = cur_state.get("git_baseline_sha")
                if prev_sha and prev_sha != "UNKNOWN_COMMIT":
                    commit_sha = prev_sha
                    print(f"[WARN] Active task already ARMED: '{cur_state.get('title', '')}' ({prev_id})")
                    print(f"[WARN] Preserving initial Git Baseline SHA ({commit_sha[:10]}). Use --force to override.")
        except Exception:
            pass

    sha_short = commit_sha[:10] if len(commit_sha) >= 10 else commit_sha
    print(f"[INFO] Git Baseline Commit: {sha_short}")

    # Step 5.8: Four Orthogonal Dimensions Inquiry Gate (Probe & Confirmation)
    inquiry_status = "CONFIRMED"
    if inquiry or any(k in title.lower() for k in ("重构", "refactor", "新功能", "架构", "design", "co-review", "governance")):
        if not inquiry_confirmed and not force:
            inquiry_status = "PENDING"
            print("\n" + "=" * 65)
            print("=== [JHOC INQUIRY GATE: FOUR ORTHOGONAL DIMENSIONS PROBE] ===")
            print("1. Scope & MVP: What is the hard boundary and minimal acceptable deliverable?")
            print("2. Architectural Trade-offs: Local determinism vs modular flexibility?")
            print("3. Fault Tolerance & Fallback: Fail-Closed circuit break vs default safe policy?")
            print("4. Impact & Long-term Governance: DOWN/UP/FORK invariants & test verification?")
            print("[MANDATORY ALIGNMENT] Pre-flight counter-questioning probe is PENDING.")
            print("Model MUST present questions to user and confirm baseline before writing business code.")
            print("=" * 65 + "\n")
        else:
            print("[PASS] Pre-flight inquiry confirmed by user.")

    # Step 6: Record task state
    task_state = {
        "task_id": task_id,
        "title": title,
        "body": body,
        "workspace": str(target_root),
        "armed_at": now_utc.isoformat(),
        "status": "ARMED",
        "gate": "ALLOW",
        "git_baseline_sha": commit_sha,
        "active_shelf_skills": canonical_skills,
        "inquiry_status": inquiry_status,
    }
    state_file.write_text(json.dumps(task_state, indent=2, ensure_ascii=True), encoding="utf-8")

    # Append to append-only task timeline
    timeline_file = mem_dir / "task_timeline.jsonl"
    try:
        with timeline_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(task_state, ensure_ascii=True) + "\n")
    except Exception:
        pass

    # Step 6.5: Register in Multi-Model Hub (Presence & Isolated Task Slot)
    try:
        import os
        sys.path.insert(0, str(JHOC_ROOT / "src"))
        from jhoc.hub import JHOCMultiModelHub, ModelPresenceState
        hub = JHOCMultiModelHub(JHOC_ROOT / "logs" / "p19-hub.sqlite")
        hub.register_presence("antigravity-ide", ModelPresenceState.CODING, task_id=task_id, pid=os.getpid(), metadata={"title": title})
        hub.arm_task_slot(task_id, "antigravity-ide", title, str(target_root), commit_sha)
    except Exception:
        pass

    # Step 7: Inspect previous Inter-Model Handoff package
    handoff_file = mem_dir / "handoff-latest.json"
    if handoff_file.is_file():
        try:
            prev_pkg = json.loads(handoff_file.read_text(encoding="utf-8"))
            p_task = prev_pkg.get("task_id", "unknown")
            p_title = prev_pkg.get("title", "")
            p_closed = prev_pkg.get("closed_at", "")[:19]
            print(f"[INFO] Previous Model Handoff: '{p_title}' ({p_task}) closed at {p_closed}")
            pending = prev_pkg.get("pending_actions", [])
            if pending:
                print(f"[WARN] Pending items from previous session ({len(pending)} items):")
                for item in pending:
                    print(f"  -> {item}")
        except Exception:
            pass

    print(f"[INFO] Task registered: {task_id}")
    print(f"[INFO] Title: {title}")
    print(f"[INFO] Workspace: {target_root}")
    print("gate: ALLOW")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="JHOC Pre-flight Kaigong Gate")
    parser.add_argument("--title", required=True, help="One-line task description")
    parser.add_argument("--body", default="", help="Optional task details")
    parser.add_argument("--workspace", default=None, help="Target workspace root path (default: current working dir)")
    parser.add_argument("--force", action="store_true", help="Force overwrite Git baseline SHA if task is already ARMED")
    parser.add_argument("--inquiry", action="store_true", help="Trigger pre-flight 4-dimension counter-questioning probe")
    parser.add_argument("--inquiry-confirmed", action="store_true", help="Mark pre-flight counter-questioning probe as confirmed by user")
    args = parser.parse_args()

    ws_path = Path(args.workspace) if args.workspace else None
    sys.exit(
        run_kaigong(
            args.title,
            args.body,
            ws_path,
            force=args.force,
            inquiry=args.inquiry,
            inquiry_confirmed=args.inquiry_confirmed,
        )
    )


if __name__ == "__main__":
    main()
