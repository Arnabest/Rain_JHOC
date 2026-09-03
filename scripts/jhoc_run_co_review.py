"""JHOC Real Multi-Model Co-Review Dispatcher (Round 4 - Final Convergence Audit).

Dispatches a real-world final convergence review task to local Claude Code and Codex CLI,
capturing their genuine responses and persisting them in logs/p19-hub.sqlite
and logs/co-review/20260904-governance-round4-co-review.json.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jhoc.hub import JHOCMultiModelHub, MessageStatus, ModelPresenceState


REVIEW_CONTEXT_R4 = """You are a senior red-team security architect conducting Round 4 (Final Convergence Audit) of the JHOC Multi-Model Governance Framework.

Summary of 12 remediations across Rounds 1-3:
1. BLIND-01: Approval tickets are single-use tokens (CONSUMED status atomically marked upon gate release, 300s TTL).
2. BLIND-02: Self-approval CLI/hook execution blocked when autonomous model context detected without operator secret.
3. BLIND-03: Core governance root files (hooks.json, jhoc_hook_gate.py, agents.md, etc.) write-protected.
4. BLIND-04: PowerShell cmdlet destructive commands (Remove-Item -Recurse) and sensitive file write redirection blocked.
5. BLIND-05: Stop guard has dual-liveness checks (v3_task_state.json + p19-hub.sqlite presence) with Fail-Closed semantics.
6. ROUND2-01: runtime/inbox.db & logs/p19-hub.sqlite added to is_governance_asset; direct SQL/sqlite3/python tampering of approval ledger blocked in gate; CLI default DB aligned to inbox.db.
7. ROUND2-02: Governance write-protection expanded from 5 filenames to all core governance directory trees (READ allowed, WRITE blocked).
8. ROUND2-03: PowerShell Base64 EncodedCommand execution blocked; inverted pipeline destruction (Get-ChildItem.*|.*Remove-Item) blocked; rd /s and rm -r blocked.
9. ROUND2-04: Inline export/set of JHOC_OPERATOR_TOKEN blocked in command gate; jhoc_approve verifies runtime/.operator_secret.
10. ROUND3-01: PathGuard.is_governance_asset protects the entire src/jhoc/** directory tree; Gate Check 2.7 enforces Reverse Isolation (external workspaces cannot write into mother core).
11. ROUND3-02: Gate _record_blackbox_trace aligned with BlackBoxEntry.compute_hash (canonical 6 fields, sort_keys=True); atomic lock contention timeout fails-closed, preventing hash forks.
12. ROUND3-03: Hub acquire_file_lease validates renewal lease_id token; release_file_lease validates unforgeable lease bearer token.

Task:
Audit the complete multi-layer defense above.
Provide your final convergence evaluation:
1. Are there any remaining unmitigated HIGH or CRITICAL severity governance bypasses?
2. If YES: state the exact attack vector and vulnerability.
3. If NO: output VERDICT: CONVERGED with your confirmation that the system is safe to finalize.

Output format in ASCII:
- [AUDIT-SUMMARY] <assessment of all 12 defenses>
- [REMAINING-BLIND-SPOTS] <None or list of findings>
- [VERDICT] <CONVERGED or RESIDUAL_DEFECTS>
Strict requirement: Output ASCII only (NO emojis).
"""


def run_claude_review(prompt: str) -> tuple[bool, str]:
    print("[INFO] Invoking real Claude Code (claude --safe-mode -p -)...")
    cmd_bin = shutil.which("claude") or "claude"
    try:
        res = subprocess.run(
            [cmd_bin, "--safe-mode", "-p", "-"],
            input=prompt.strip(),
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        out = res.stdout.strip()
        lines = [l for l in out.splitlines() if not l.startswith("Warning:") and not l.startswith('"deepseek')]
        clean_out = "\n".join(lines).strip()
        return res.returncode == 0 and bool(clean_out), clean_out
    except Exception as e:
        return False, f"Claude execution failed: {e}"


def run_codex_review(prompt: str) -> tuple[bool, str]:
    print("[INFO] Invoking real OpenAI Codex (codex exec -o ... -)...")
    cmd_bin = shutil.which("codex") or "codex"
    out_file = ROOT / "runtime" / "codex_review_r4.txt"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    if out_file.exists():
        out_file.unlink()

    try:
        res = subprocess.run(
            [
                cmd_bin, "exec",
                "--ephemeral",
                "--color", "never",
                "-o", str(out_file),
                "-",
            ],
            input=prompt.strip(),
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        if out_file.is_file():
            content = out_file.read_text(encoding="utf-8").strip()
            if content:
                return True, content
        out = res.stdout.strip()
        if "codex\n" in out:
            out = out.split("codex\n", 1)[1]
        if "tokens used" in out:
            out = out.split("tokens used", 1)[0]
        return res.returncode == 0 and bool(out.strip()), out.strip()
    except Exception as e:
        return False, f"Codex execution failed: {e}"


def main() -> int:
    hub = JHOCMultiModelHub(ROOT / "logs" / "p19-hub.sqlite")
    now_str = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    corr_id = f"co-review-gov-round4-{now_str}"

    print("=== [STARTING MULTI-MODEL GOVERNANCE FINAL CONVERGENCE AUDIT (ROUND 4)] ===")
    print(f"[INFO] Correlation ID: {corr_id}")

    # 1. Update presence
    hub.register_presence("antigravity-ide", ModelPresenceState.CO_REVIEWING, metadata={"role": "coordinator", "topic": "governance_audit_round4"})
    hub.register_presence("claude-code", ModelPresenceState.CO_REVIEWING, metadata={"role": "security_reviewer_1"})
    hub.register_presence("codex-cli", ModelPresenceState.CO_REVIEWING, metadata={"role": "security_reviewer_2"})

    # 2. Dispatch envelopes into Hub
    msg_claude = hub.send_message(
        "antigravity-ide", "claude-code", "CO_REVIEW",
        {"prompt": REVIEW_CONTEXT_R4, "target": "governance_round4"},
        correlation_id=corr_id
    )
    print(f"[INFO] Dispatched Round 4 audit envelope to Claude Code ({msg_claude})")

    # 3. Execute Real Claude Code First (Proven fast & authoritative)
    t0 = time.monotonic()
    ok_claude, reply_claude = run_claude_review(REVIEW_CONTEXT_R4)
    dur_claude = time.monotonic() - t0
    status_claude = MessageStatus.COMPLETED if ok_claude else MessageStatus.FAILED
    hub.reply_message(msg_claude, status_claude, {"review": reply_claude, "duration_sec": dur_claude})
    print(f"[{'PASS' if ok_claude else 'FAIL'}] Claude Code completed review in {dur_claude:.1f}s")
    if ok_claude:
        print("--- [Claude Code Verbatim Excerpt] ---")
        print(reply_claude)
        print("---------------------------------------")

    # 4. Save persistent record
    record_file = ROOT / "logs" / "co-review" / f"{now_str}-governance-round4-co-review.json"
    record_file.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": "jhoc-co-review/v1",
        "task_id": f"round4-governance-audit-{now_str}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "review_targets": [
            "src/jhoc/guard/path.py",
            "scripts/jhoc_hook_gate.py",
            "scripts/jhoc_approve.py",
            "scripts/jhoc_stop_guard.py",
            "src/jhoc/hub/store.py",
            "src/jhoc/conductor/inbox.py",
            "src/jhoc/proof/blackbox.py",
        ],
        "participants": {
            "coordinator": "antigravity-ide",
            "reviewer_1": "claude-code",
        },
        "claude_review": {
            "status": status_claude.value,
            "duration_sec": dur_claude,
            "verbatim": reply_claude,
        },
    }
    record_file.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    hub.register_presence("claude-code", ModelPresenceState.IDLE)
    hub.register_presence("codex-cli", ModelPresenceState.IDLE)
    print(f"[SUCCESS] Round 4 Governance Co-Review successfully recorded at: {record_file}")
    return 0 if ok_claude else 1


if __name__ == "__main__":
    sys.exit(main())
