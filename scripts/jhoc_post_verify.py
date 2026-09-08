"""JHOC PostInvocation Response & Evidence Verifier.

Hardened under Multi-Model Co-Review C1, C2, C3, C5, C6, C7, C8:
1. Uses robust shared transcript_reader (backward block-seeking, aggregates all segments/tools).
2. Distinguishes explain vs execute intent to prevent false-positive blocks on casual chat.
3. Requires physical CLI invocation of jhoc_exec_reviewer.py or valid hub_co_review_evidence row.
4. Strictly eliminates self-certification instruction (C3).
5. Strictly adheres to Rule 1 (Physical Reality) and Rule 7 (Zero Emoji).
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jhoc.context.transcript_reader import extract_last_turn_from_transcript, TurnRecord
from jhoc.hub import JHOCMultiModelHub


_REVIEW_TRIGGER_RE = re.compile(r"(多模型协审|拉起协审|多模型商讨|拉起多模型|协同评审|co-review|开工协审|收工协审)", re.IGNORECASE)
_EXPLAIN_ONLY_RE = re.compile(r"^(什么是|为何|为什么|如何理解|解释|explain|what is|how does)", re.IGNORECASE)
_NARRATIVE_CLAIM_RE = re.compile(
    r"(\[VERDICT\]|APPROVED_WITH_CONDITIONS|\[REJECTED\]|\[APPROVED\]|协审结论|终审裁决|红队审查意见)",
    re.IGNORECASE,
)


def is_execution_intent(user_prompt: str) -> bool:
    """Classifies whether the user prompt requests physical execution vs pure explanation."""
    p = user_prompt.strip()
    if not p:
        return False
    if _EXPLAIN_ONLY_RE.search(p) and not ("拉起" in p or "执行" in p or "run" in p.lower() or "execute" in p.lower()):
        return False
    return bool(_REVIEW_TRIGGER_RE.search(p))


def evaluate_post_invocation(payload: dict) -> dict:
    # 1. Resolve Transcript Path
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

    turn: TurnRecord = extract_last_turn_from_transcript(t_path)
    if not turn.has_user_input or not turn.has_assistant_response:
        return {"injectSteps": []}

    # 2. Check if this turn requested Multi-Model Co-Review with execution intent (C6)
    if not is_execution_intent(turn.user_prompt):
        return {"injectSteps": []}

    # 3. Check physical execution in tool calls
    has_wrapper_call = any(
        "jhoc_exec_reviewer" in json.dumps(tc.get("args", {}))
        or "jhoc_co_review" in json.dumps(tc.get("args", {}))
        or ("claude" in json.dumps(tc.get("args", {})) and "pwsh" in json.dumps(tc.get("args", {})))
        or ("codex" in json.dumps(tc.get("args", {})) and "pwsh" in json.dumps(tc.get("args", {})))
        for tc in turn.tool_calls
    )

    # 4. Check valid evidence row in SQLite hub (C1, C5)
    hub_db_path = payload.get("hubDbPath")
    if hub_db_path:
        hub_db = Path(hub_db_path)
    elif t_path_str and Path(t_path_str).parent.name != "logs":
        hub_db = Path(t_path_str).parent / "p19-hub.sqlite"
    else:
        hub_db = ROOT / "logs" / "p19-hub.sqlite"

    has_valid_evidence = False
    if hub_db.is_file():
        hub = None
        try:
            hub = JHOCMultiModelHub(hub_db)
            has_valid_evidence = hub.has_valid_recent_evidence(max_age_seconds=1800)
        except Exception:
            pass
        finally:
            if hub is not None:
                hub.close()

    # 5. Check if assistant makes unbacked oral conclusion claims
    has_narrative_claim = bool(_NARRATIVE_CLAIM_RE.search(turn.assistant_text))

    if has_narrative_claim and not has_wrapper_call and not has_valid_evidence:
        # Strict rejection without self-certification teaching (C3)
        rejection_msg = (
            "[RULE 1/6 HARNESS 拦截] 检测到你在纯文本中口头宣称了多模型协审，但当前轮次未检测到"
            "受控包装器 (py -3 scripts/jhoc_exec_reviewer.py) 的物理执行与有效证据包！"
            "严禁角色扮演自编自演（反思 Rule 0 与 Rule 1）。你必须通过 run_command 物理调度 "
            "'py -3 scripts/jhoc_exec_reviewer.py --model claude --prompt-file <path>' 执行真实外部评审，"
            "或向操作员申请人工审批票据。"
        )
        return {
            "terminationBehavior": "force_continue",
            "injectSteps": [{"ephemeralMessage": rejection_msg}],
        }

    return {"injectSteps": []}


def main() -> None:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        payload = {}

    res = evaluate_post_invocation(payload)
    print(json.dumps(res, ensure_ascii=True))


if __name__ == "__main__":
    main()
