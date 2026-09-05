"""JHOC PostInvocation Response & Evidence Verifier.

Intercepts model outputs after invocation ends:
1. Inspects whether the turn claimed multi-model review or governance compliance purely via text.
2. If pure-text narrative roleplay is detected without physical CLI execution or SHA-256 evidence packages,
   immediately forces continuation (terminationBehavior: force_continue) and injects rejection reason.
3. Strictly adheres to Rule 1 (Physical Reality) and Rule 7 (Zero Emoji).
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

try:
    from jhoc.hub import JHOCMultiModelHub, ModelPresenceState
except ImportError:
    pass


def extract_last_turn_from_transcript(transcript_path: Path, max_tail_bytes: int = 16384) -> tuple[str, str, list[dict]]:
    """Extracts (latest_user_prompt, latest_assistant_text, latest_tool_calls)."""
    if not transcript_path.is_file():
        return "", "", []

    try:
        size = transcript_path.stat().st_size
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
            if size > max_tail_bytes:
                f.seek(size - max_tail_bytes)
            chunk = f.read()

        lines = [l.strip() for l in chunk.strip().split("\n") if l.strip()]
        last_user = ""
        last_assistant = ""
        tool_calls: list[dict] = []

        for line in reversed(lines):
            try:
                data = json.loads(line)
                stype = data.get("type")
                if not last_assistant and stype in {"MODEL", "PLANNER_RESPONSE"}:
                    last_assistant = data.get("content", "")
                    tool_calls = data.get("tool_calls", [])
                elif not last_user and stype == "USER_INPUT":
                    content = data.get("content", "")
                    m = re.search(r"<USER_REQUEST>(.*?)</USER_REQUEST>", content, re.DOTALL)
                    last_user = m.group(1).strip() if m else content.strip()
                if last_user and last_assistant:
                    break
            except Exception:
                continue

        return last_user, last_assistant, tool_calls
    except Exception:
        return "", "", []


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

    last_user, last_assistant, tool_calls = extract_last_turn_from_transcript(t_path)
    if not last_user or not last_assistant:
        return {"injectSteps": []}

    # 2. Check if this turn requested Multi-Model Co-Review
    review_trigger_re = re.compile(r"(多模型协审|拉起协审|多模型商讨|拉起多模型|协同评审|co-review)", re.IGNORECASE)
    is_review_request = bool(review_trigger_re.search(last_user))

    if is_review_request:
        # Check if the assistant actually invoked the real tool or produced fresh evidence
        has_real_cli_call = any(
            "jhoc_co_review" in json.dumps(tc.get("args", {}))
            or "claude" in json.dumps(tc.get("args", {}))
            or "codex" in json.dumps(tc.get("args", {}))
            for tc in tool_calls
        )

        # Check fresh file in logs/co-review/ (or payload specified dir)
        co_dir_override = payload.get("coReviewDir")
        co_dir = Path(co_dir_override) if co_dir_override else ROOT / "logs" / "co-review"
        has_fresh_evidence = False
        if co_dir.is_dir():
            recent_files = sorted(co_dir.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
            for rf in recent_files:
                if (time.time() - rf.stat().st_mtime) < 180:
                    try:
                        data = json.loads(rf.read_text(encoding="utf-8"))
                        if data.get("evidence_package_sha256"):
                            has_fresh_evidence = True
                            break
                    except Exception:
                        continue

        # If model outputs text claiming verdicts or pretending to be codex/claude, but didn't run tool
        narrative_mimic_re = re.compile(r"(\[VERDICT\]|Claude.*评审|Codex.*评审|APPROVED_WITH_CONDITIONS)", re.IGNORECASE)
        has_narrative_claim = bool(narrative_mimic_re.search(last_assistant))

        if has_narrative_claim and not has_real_cli_call and not has_fresh_evidence:
            rejection_msg = (
                "[RULE 1/6 HARNESS 拦截] 检测到你在纯文本中口头宣称了多模型协审，但本轮未检测到物理 CLI 工具调用与有效证据包！"
                "严禁角色扮演自嗨（反思 LESSON #147）。你必须通过 run_command 物理调用 'py -3 scripts/jhoc_co_review.py' "
                "或生成带 SHA-256 的证据包！"
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
