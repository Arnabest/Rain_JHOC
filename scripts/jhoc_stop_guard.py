"""JHOC Lifecycle Stop Guard - Intercepts agent termination if task is ARMED or claims unverified.

Hardened under Multi-Model Co-Review C1, C4, C6, C7:
1. Operator-only override via physical runtime/.operator_stop_secret (blocks env tampering).
2. Blocks stop if active task is ARMED without shougong.
3. Blocks stop if turn contains unverified oral co-review claims without physical evidence.
4. Quota critical stop guard preserves handoff requirement when quota <= 8%.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent


def evaluate_stop(payload: dict) -> dict:
    # 0. Forced stop override from payload (e.g. IDE or test harness explicit force flag)
    if payload.get("force"):
        return {"decision": "allow", "reason": "Forced stop override triggered."}

    # 1. Operator-only override: check physical operator secret file or approval ticket (C4)
    operator_secret_file = ROOT / "runtime" / ".operator_stop_secret"
    if operator_secret_file.is_file():
        try:
            operator_secret_file.unlink()
        except Exception:
            pass
        return {"decision": "allow", "reason": "Operator physical stop secret verified."}

    # 2. Check task state (ARMED blocks stop)
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

    # 3. Unverified Oral Claim Stop Guard (C1, C4, C6)
    t_path_str = payload.get("transcriptPath")
    if t_path_str:
        t_path = Path(t_path_str)
    else:
        cid = payload.get("conversationId") or payload.get("session_id")
        if not cid:
            brain = Path.home() / ".gemini" / "antigravity-ide" / "brain"
            if brain.is_dir():
                cand = sorted(brain.glob("*/.system_generated/logs/transcript.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
                if cand:
                    cid = cand[0].parent.parent.parent.name
        t_path = Path.home() / ".gemini" / "antigravity-ide" / "brain" / (cid or "") / ".system_generated" / "logs" / "transcript.jsonl"

    if t_path.is_file():
        try:
            if str(ROOT / "src") not in sys.path:
                sys.path.insert(0, str(ROOT / "src"))
            from jhoc.context.transcript_reader import extract_last_turn_from_transcript
            from jhoc.hub import JHOCMultiModelHub

            turn = extract_last_turn_from_transcript(t_path)
            narrative_claim_re = re.compile(
                r"(\[VERDICT\]|APPROVED_WITH_CONDITIONS|\[REJECTED\]|\[APPROVED\]|协审结论|终审裁决|红队审查意见)",
                re.IGNORECASE,
            )
            if turn.is_truncated and not turn.has_user_input and narrative_claim_re.search(turn.assistant_text):
                return {
                    "decision": "continue",
                    "reason": (
                        "[RULE 1/6 HARNESS 物理拦截] 终止停机请求已被拦截：Transcript 截断未能定位用户提示词边界，"
                        "且检测到口头宣称终审裁决。在无明确上下文边界时严禁直接结案停机。"
                    ),
                }

            if turn.has_user_input and turn.has_assistant_response:
                review_trigger_re = re.compile(r"(多模型协审|拉起协审|多模型商讨|拉起多模型|协同评审|co-review)", re.IGNORECASE)
                explain_only_re = re.compile(r"^(什么是|为何|为什么|如何理解|解释|explain|what is|how does)", re.IGNORECASE)

                # Only block if user requested execution (not casual explanation) and assistant makes verdict claim
                is_exec = bool(review_trigger_re.search(turn.user_prompt)) and not explain_only_re.search(turn.user_prompt)
                if is_exec and narrative_claim_re.search(turn.assistant_text):
                    has_wrapper_call = any(
                        "jhoc_exec_reviewer" in json.dumps(tc.get("args", {}))
                        or "jhoc_co_review" in json.dumps(tc.get("args", {}))
                        or ("claude" in json.dumps(tc.get("args", {})) and "pwsh" in json.dumps(tc.get("args", {})))
                        or ("codex" in json.dumps(tc.get("args", {})) and "pwsh" in json.dumps(tc.get("args", {})))
                        for tc in turn.tool_calls
                    )
                    hub_db_path = payload.get("hubDbPath") or payload.get("hub_db")
                    if hub_db_path:
                        hub_db = Path(hub_db_path)
                    elif t_path and t_path.is_file() and not t_path.resolve().is_relative_to(ROOT):
                        if (t_path.parent / "logs" / "p19-hub.sqlite").is_file():
                            hub_db = t_path.parent / "logs" / "p19-hub.sqlite"
                        elif (t_path.parent / "p19-hub.sqlite").is_file():
                            hub_db = t_path.parent / "p19-hub.sqlite"
                        else:
                            hub_db = t_path.parent / "logs" / "p19-hub.sqlite"
                    else:
                        hub_db = ROOT / "logs" / "p19-hub.sqlite"
                    has_evidence = False
                    if hub_db.is_file():
                        hub = None
                        try:
                            hub = JHOCMultiModelHub(hub_db)
                            has_evidence = hub.has_valid_recent_evidence(max_age_seconds=1800)
                        except Exception:
                            pass
                        finally:
                            if hub is not None:
                                hub.close()

                    if not has_wrapper_call and not has_evidence:
                        return {
                            "decision": "continue",
                            "reason": (
                                "[RULE 1/6 HARNESS 物理拦截] 终止停机请求已被拦截：检测到你在本轮口头声称了多模型协审结论，"
                                "但底层既未调用受控包装器 (scripts/jhoc_exec_reviewer.py)，数据库亦无匹配证据行！"
                                "严禁自编自演后直接结案停机。你必须物理调度外部模型产出有效凭据包。"
                            ),
                        }
        except Exception:
            pass

    # 3.5. Mandatory Worklog Physical Verification: If today has an active/closed task, ensure today's worklog exists
    if not payload.get("skip_worklog_check") and not payload.get("force"):
        try:
            from datetime import datetime, timezone
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            today_worklog = ROOT / "docs" / "worklogs" / f"worklog-{today_str}.md"
            task_state_p = ROOT / "memory" / "v3_task_state.json"
            if task_state_p.is_file():
                task_st = json.loads(task_state_p.read_text(encoding="utf-8"))
                task_armed_at = task_st.get("armed_at", "")
                if today_str in task_armed_at:
                    if not today_worklog.is_file() or today_worklog.stat().st_size == 0:
                        return {
                            "decision": "continue",
                            "reason": (
                                f"[JHOC LIFECYCLE GUARD] Physical Worklog missing: 'docs/worklogs/worklog-{today_str}.md' "
                                "does not exist or is empty. You must execute 'py -3 scripts/jhoc_shougong.py' or "
                                "'py -3 scripts/jhoc_worklog.py --save' to persist human-readable worklog before stopping."
                            ),
                        }
        except Exception:
            pass

    # 4. Multi-Model Hub Presence Check
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

    # 5. Quota Critical Stop Guard: Prevent stopping without handoff when quota <= 8%
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
