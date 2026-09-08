"""JHOC PreInvocation Context & Memory Injector."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent


def evaluate_pre_invocation(payload: dict, check_quota: bool = False) -> dict:
    steps: list[dict] = []
    state_file = ROOT / "memory" / "v3_task_state.json"

    if state_file.is_file():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
            if state.get("status") == "ARMED":
                title = state.get("title", "Active Task")
                task_id = state.get("task_id", "")
                sha = state.get("git_baseline_sha", "HEAD")[:10]
                msg = (
                    f"[JHOC LIFECYCLE GUARD] Active Task: '{title}' ({task_id}) [Baseline: {sha}]. "
                    "Skill Ordering: INCEPTION -> ELABORATION -> ARM -> EXECUTE -> VERIFY (shougong) -> CLOSE. "
                    "Before completing your response, you MUST execute 'python scripts/jhoc_shougong.py' to close the task."
                )
                steps.append({"ephemeralMessage": msg})
        except Exception:
            pass

    if check_quota and not payload.get("skip_quota_check"):
        try:
            if str(ROOT / "src") not in sys.path:
                sys.path.insert(0, str(ROOT / "src"))
            from jhoc.quota.antigravity_quota import evaluate_quota_alert, get_antigravity_quota_live

            sid = payload.get("conversationId") or payload.get("session_id")
            if not sid:
                brain = Path.home() / ".gemini" / "antigravity-ide" / "brain"
                if brain.is_dir():
                    cand = sorted(brain.glob("*/.system_generated/logs/transcript.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
                    if cand:
                        sid = cand[0].parent.parent.parent.name

            quota_data = get_antigravity_quota_live(session_id=sid)
            alert = evaluate_quota_alert(quota_data, threshold_pct=8.0)
            if alert.is_critical:
                quota_msg = (
                    f"[CRITICAL QUOTA ALERT] 当前账户 '{alert.account_email}' 配额已低于 8% 临界阈值 (告急项: {', '.join(alert.critical_buckets)})！"
                    "根据 token-stats 契约：请立即物理落盘改动、沉淀 handoff 与任务记忆，准备跨模型/跨账号交接。"
                )
                steps.append({"ephemeralMessage": quota_msg})
        except Exception:
            pass

    # 3. Governance Engine JIT Intent & Lesson Injection
    try:
        driver_path = ROOT / ".agents" / "plugins" / "governance-engine" / "adapters"
        if str(driver_path) not in sys.path:
            sys.path.insert(0, str(driver_path))
        from ide_hook_driver import IDEHookDriver
        driver = IDEHookDriver(ROOT)
        gov_res = driver.evaluate_pre_invocation(payload, timeout_ms=20.0)
        for s in gov_res.get("injectSteps", []):
            msg = s.get("ephemeralMessage", "")
            if "[JHOC LIFECYCLE GUARD]" in msg:
                continue
            steps.append(s)
    except Exception:
        pass

    return {"injectSteps": steps}


def main() -> None:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        payload = {}

    res = evaluate_pre_invocation(payload, check_quota=True)
    print(json.dumps(res, ensure_ascii=True))


if __name__ == "__main__":
    main()

