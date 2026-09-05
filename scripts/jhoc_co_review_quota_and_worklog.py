"""JHOC Multi-Model Co-Review Dispatcher for Quota Fuse & Worklog Distillation Pipeline.

Dispatches the architectural plan to local Claude Code and Codex CLI,
capturing their genuine verbatim critiques and persisting in p19-hub.sqlite and logs/co-review/.
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


REVIEW_PROMPT = """You are a Principal Systems Architect and Red-Team Reviewer auditing a critical infrastructure fix in the JHOC Multi-Agent Governance Framework.

[STRICT OPERATING CONSTRAINT]
Do NOT execute any tools or read files from disk. Evaluate this architecture purely based on the text and code definitions provided below. Output ASCII only (NO emojis).

[INCIDENT BACKGROUND]
1. Incident A (Silent Quota Fuse Bypass):
   - In recent live sessions, an account's Gemini quota dropped to 8% (and previously 1%).
   - While documentation (06-quota-fuse-and-harness-circuit-breaker.md) mandated an 8% hard circuit breaker in `jhoc_hook_gate.py`, the physical code was missing `docs/worklogs/` and `jhoc_worklog.py` in the emergency whitelist.
   - Furthermore, `jhoc_pre_inject.py` only injected quota warnings on user pre-invocation, not at turn completion.
   - In `jhoc_shougong.py`, closure quota was only printed to stdout as `[INFO]` without a prominent banner, so the user was completely unalerted when the quota hit 8% upon task completion.

2. Incident B (Doc-Runtime Disconnect in Worklog Generation):
   - `worklog-distiller` skill has a complete script (`scripts/jhoc_worklog.py`) with 11 passing unit tests, supporting 9-section standalone pedagogical problem blogs and knowledge graphs.
   - However, it was never hooked into `jhoc_shougong.py`. As a result, when tasks close and state is persisted, no blog post or knowledge graph is automatically generated, requiring manual triggering.

[PROPOSED ARCHITECTURAL FIXES]
1. `scripts/jhoc_hook_gate.py`:
   - Enforce 8% quota fuse in `_evaluate_inner` on mutating tools (`write_to_file`, `replace_file_content`, `multi_replace_file_content`, `run_command`).
   - Strict whitelist to avoid deadlocks:
     `whitelist_targets`: `implementation_plan.md`, `walkthrough.md`, `memory/`, `docs/lessons/`, `docs/worklogs/`, `logs/token-stats/`.
     `whitelist_cmds`: `jhoc_shougong.py`, `jhoc_token_stats.py`, `jhoc_worklog.py`, `git status`, `git add`, `git commit`, `git diff`, `git log`.
   - Any other mutation when quota <= 8.0% returns `decision: deny`.

2. `scripts/jhoc_shougong.py`:
   - Step 6.2: If `is_quota_crit`, output a high-visibility ASCII alert banner:
     `[CRITICAL QUOTA ALERT] 严重警告：当前账户配额已跌入 <= 8% 危险水位！`
     and record `quota_critical: True`, `switch_account_recommended: True` in `handoff-latest.json`.
   - Step 7: When `archive=True`, automatically run:
     `[sys.executable, "scripts/jhoc_worklog.py", "--blog", "--save", "--graph"]`
     to bind task closure with pedagogical blog generation and knowledge graph updates.

3. `scripts/jhoc_stop_guard.py`:
   - If quota <= 8.0% and no fresh, alert-marked `handoff-latest.json` exists, fail-closed block termination (`decision: continue`) requiring explicit handoff.

[AUDIT TASK]
Please evaluate this architectural fix across 4 dimensions:
1. Deadlock & Handoff Safety: Can an agent at 8% quota still cleanly persist plan, memory, handoff package, and worklog blog without being blocked by the hook gate?
2. Performance & Timeout: Does calling `jhoc_worklog.py` in `shougong.py` pose timeout risks during task closure?
3. Human Visibility: Does the combination of terminal banner, handoff package flag, and stop guard block effectively eliminate the "human unnotified" blind spot?
4. Edge cases & Residual Deficiencies: What edge cases or failure modes remain unaddressed?

Format your response in plain text / ASCII (NO emojis):
- [VERDICT] <APPROVED / APPROVED_WITH_CONDITIONS / REJECTED>
- [ANALYSIS-DEADLOCK]
- [ANALYSIS-PERFORMANCE]
- [ANALYSIS-VISIBILITY]
- [RESIDUAL-RISKS-AND-RECOMMENDATIONS]
"""


def run_claude_review(prompt: str) -> tuple[bool, str]:
    print("[INFO] Invoking real Claude Code CLI (claude -p -)...")
    cmd_bin = shutil.which("claude") or shutil.which("claude.cmd") or "claude"
    try:
        res = subprocess.run(
            [cmd_bin, "-p", "-"],
            input=prompt.strip(),
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
        )
        out = res.stdout.strip()
        lines = [l for l in out.splitlines() if not l.startswith("Warning:") and not l.startswith('"deepseek')]
        clean_out = "\n".join(lines).strip()
        return res.returncode == 0 and bool(clean_out), clean_out
    except Exception as e:
        return False, f"Claude execution failed: {e}"


def run_codex_review(prompt: str) -> tuple[bool, str]:
    print("[INFO] Invoking real OpenAI Codex CLI (codex exec --ephemeral ...)...")
    cmd_bin = shutil.which("codex") or shutil.which("codex.cmd") or "codex"
    out_file = ROOT / "runtime" / "codex_review_quota.txt"
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
            timeout=90,
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
    corr_id = f"co-review-quota-worklog-{now_str}"

    print("=== [JHOC REAL MULTI-MODEL CO-REVIEW CHANNELS INITIATION] ===")
    print(f"[INFO] Correlation ID: {corr_id}")

    hub.register_presence("antigravity-ide", ModelPresenceState.CO_REVIEWING, metadata={"topic": "quota_worklog_remediation"})
    hub.register_presence("claude-code", ModelPresenceState.CO_REVIEWING, metadata={"topic": "quota_worklog_remediation"})
    hub.register_presence("codex-cli", ModelPresenceState.CO_REVIEWING, metadata={"topic": "quota_worklog_remediation"})

    # 1. Dispatch to Claude Code
    msg_claude = hub.send_message(
        "antigravity-ide", "claude-code", "CO_REVIEW",
        {"prompt": REVIEW_PROMPT, "topic": "quota_worklog_remediation"},
        correlation_id=corr_id
    )
    print(f"[INFO] Dispatched review envelope to Claude Code ({msg_claude})")

    t0 = time.monotonic()
    ok_claude, reply_claude = run_claude_review(REVIEW_PROMPT)
    dur_claude = time.monotonic() - t0
    status_claude = MessageStatus.COMPLETED if ok_claude else MessageStatus.FAILED
    hub.reply_message(msg_claude, status_claude, {"review": reply_claude, "duration_sec": dur_claude})
    print(f"[{'PASS' if ok_claude else 'FAIL'}] Claude Code completed review in {dur_claude:.1f}s")
    if ok_claude:
        print("\n--- [CLAUDE CODE VERBATIM REVIEW] ---")
        print(reply_claude)
        print("-------------------------------------\n")

    # 2. Dispatch to Codex CLI
    msg_codex = hub.send_message(
        "antigravity-ide", "codex-cli", "CO_REVIEW",
        {"prompt": REVIEW_PROMPT, "topic": "quota_worklog_remediation"},
        correlation_id=corr_id
    )
    print(f"[INFO] Dispatched review envelope to Codex CLI ({msg_codex})")

    t1 = time.monotonic()
    ok_codex, reply_codex = run_codex_review(REVIEW_PROMPT)
    dur_codex = time.monotonic() - t1
    status_codex = MessageStatus.COMPLETED if ok_codex else MessageStatus.FAILED
    hub.reply_message(msg_codex, status_codex, {"review": reply_codex, "duration_sec": dur_codex})
    print(f"[{'PASS' if ok_codex else 'FAIL'}] Codex CLI completed review in {dur_codex:.1f}s")
    if ok_codex:
        print("\n--- [OPENAI CODEX VERBATIM REVIEW] ---")
        print(reply_codex)
        print("--------------------------------------\n")

    # 3. Save to persistent file
    record_file = ROOT / "logs" / "co-review" / f"{now_str}-quota-and-worklog-co-review.json"
    record_file.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": "jhoc-co-review/v1",
        "task_id": f"quota-worklog-review-{now_str}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "participants": {
            "coordinator": "antigravity-ide",
            "reviewer_claude": "claude-code",
            "reviewer_codex": "codex-cli",
        },
        "claude_review": {
            "status": status_claude.value,
            "duration_sec": dur_claude,
            "verbatim": reply_claude,
        },
        "codex_review": {
            "status": status_codex.value,
            "duration_sec": dur_codex,
            "verbatim": reply_codex,
        }
    }
    record_file.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")

    hub.register_presence("antigravity-ide", ModelPresenceState.IDLE)
    hub.register_presence("claude-code", ModelPresenceState.IDLE)
    hub.register_presence("codex-cli", ModelPresenceState.IDLE)

    print("=" * 60)
    print(f"[CO-REVIEW RECORD PERSISTED] {record_file}")
    print("=" * 60)

    return 0 if (ok_claude and ok_codex) else 1


if __name__ == "__main__":
    sys.exit(main())
