#!/usr/bin/env python3
"""jhoc_token_stats.py - JHOC Conversation token and live quota statistics CLI.

Extracts real-time Antigravity dual-bucket quotas and alerts when quota falls <= 8%.
"""

from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from jhoc.quota.antigravity_quota import (
    CRITICAL_THRESHOLD_PERCENT,
    QuotaAlert,
    evaluate_quota_alert,
    format_quota_markdown,
    get_antigravity_quota_live,
)

# CJK detection for token estimation
CJK_RE = re.compile(r"[\u3000-\u9fff\uf900-\ufaff\uff00-\uffef]")
RETRIEVAL_TOOLS = {
    "view_file", "grep_search", "list_dir", "search_web", "read_url_content",
    "Read", "Grep", "Glob", "WebFetch", "WebSearch"
}


def est_tokens(text: str) -> int:
    """Rough heuristic token estimator (CJK ~ chars/1.6, ASCII ~ chars/4)."""
    cjk_count = len(CJK_RE.findall(text))
    return int(cjk_count / 1.6 + (len(text) - cjk_count) / 4)


def pick_session(project_dir: Path, session: str | None = None) -> tuple[Path | None, str]:
    if session:
        p = Path(session)
        if p.is_file():
            sid = p.parent.parent.parent.name if p.name == "transcript.jsonl" else p.stem
            return p, sid
        brain = Path.home() / ".gemini" / "antigravity-ide" / "brain"
        if brain.is_dir():
            target_f = brain / session / ".system_generated" / "logs" / "transcript.jsonl"
            if target_f.is_file():
                return target_f, session
        return None, session

    # Search Antigravity brain transcripts sorted by mtime
    brain = Path.home() / ".gemini" / "antigravity-ide" / "brain"
    candidates: list[tuple[float, Path, str]] = []
    if brain.is_dir():
        for f in brain.glob("*/.system_generated/logs/transcript.jsonl"):
            if f.is_file():
                candidates.append((f.stat().st_mtime, f, f.parent.parent.parent.name))

    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1], candidates[0][2]

    return None, "default_session"


def analyze_transcript(session_file: Path | None, session_id: str) -> dict:
    if not session_file or not session_file.is_file():
        return {
            "session_id": session_id,
            "session_file": str(session_file) if session_file else None,
            "api_calls": 0,
            "user_prompts": 0,
            "context_total": 0,
            "fresh_input": 0,
            "output": 0,
            "model_name": "Gemini 3.7 Flash (Antigravity)",
        }

    user_prompts = 0
    api_calls = 0
    accumulated_context_tokens = 0
    base_bootstrap_tokens = 3500
    fresh_input = 0
    output_tokens = 0
    detected_model = "Gemini 3.7 Flash (Antigravity)"

    try:
        with open(session_file, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue

                t = d.get("type")
                content = str(d.get("content") or "")

                if t == "USER_INPUT":
                    user_prompts += 1
                    if "Model Selection" in content:
                        m = re.search(r"Model Selection[`\s]+from\s+[^\s]+\s+to\s+([^`\n]+)", content)
                        if m:
                            raw_val = m.group(1).strip().rstrip(".")
                            detected_model = re.split(r"\.\s+", raw_val)[0].strip()
                    accumulated_context_tokens += est_tokens(content)
                    fresh_input += est_tokens(content)

                elif t == "PLANNER_RESPONSE":
                    api_calls += 1
                    thinking_str = str(d.get("thinking") or "")
                    resp_content = content
                    out_tok = est_tokens(thinking_str) + est_tokens(resp_content)
                    output_tokens += out_tok
                    accumulated_context_tokens += out_tok

                elif t in {"RUN_COMMAND", "VIEW_FILE", "CODE_ACTION", "GREP_SEARCH", "GENERIC", "LIST_DIR", "READ_URL_CONTENT", "SEARCH_WEB"}:
                    accumulated_context_tokens += est_tokens(content)
                    fresh_input += est_tokens(content)
    except Exception:
        pass

    context_total = accumulated_context_tokens + base_bootstrap_tokens
    return {
        "session_id": session_id,
        "session_file": str(session_file),
        "api_calls": api_calls,
        "user_prompts": user_prompts,
        "context_total": context_total,
        "fresh_input": fresh_input,
        "output": output_tokens,
        "model_name": detected_model,
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="JHOC Conversation token and quota stats")
    ap.add_argument("--project-dir", default=".", help="Target project root (default: .)")
    ap.add_argument("--session", default=None, help="Target session id or transcript path")
    ap.add_argument("--format", choices=("md", "json"), default="md")
    ap.add_argument("--check-alert", action="store_true", help="Exit code 1 if quota is at or below 8%% threshold")
    ap.add_argument("--threshold", type=float, default=CRITICAL_THRESHOLD_PERCENT, help="Quota alert threshold percentage (default: 8.0)")
    ap.add_argument("--no-record", action="store_true", help="Do not record to logs/token-stats/")
    args = ap.parse_args()

    project_dir = Path(args.project_dir).resolve()
    session_file, session_id = pick_session(project_dir, args.session)

    # 1. Fetch live quota via Connect-RPC
    quota_data = get_antigravity_quota_live(session_id=session_id)
    alert = evaluate_quota_alert(quota_data, threshold_pct=args.threshold)

    # 2. Analyze transcript metrics
    metrics = analyze_transcript(session_file, session_id)
    metrics["quota"] = quota_data
    metrics["alert"] = {
        "is_critical": alert.is_critical,
        "alert_level": alert.alert_level,
        "critical_buckets": list(alert.critical_buckets),
        "warning_message": alert.warning_message,
        "handover_recommended": alert.handover_recommended,
    }
    metrics["timestamp"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # 3. Record to logs if requested
    if not args.no_record:
        out_dir = project_dir / "logs" / "token-stats"
        out_dir.mkdir(parents=True, exist_ok=True)
        rec_file = out_dir / f"{session_id}.jsonl"
        with open(rec_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(metrics, ensure_ascii=True) + "\n")
        latest_file = out_dir / "latest.json"
        latest_file.write_text(json.dumps(metrics, ensure_ascii=True, indent=2), encoding="utf-8")

    # 4. Render output
    if args.format == "json":
        print(json.dumps(metrics, ensure_ascii=True, indent=2))
    else:
        md_lines = [
            "## [JHOC TOKEN & QUOTA STATS]",
            f"- 会话: `{session_id}` | API 调用 {metrics['api_calls']} 次 | 用户提问 {metrics['user_prompts']} 轮",
            f"- 模型: `{metrics['model_name']}`",
            format_quota_markdown(quota_data, alert),
            f"- 上下文总数 (估算): **{metrics['context_total']:,}** tokens",
            f"- 累计输入: {metrics['fresh_input']:,} | 累计输出: {metrics['output']:,}",
        ]
        print("\n".join(md_lines))

    if args.check_alert and alert.is_critical:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
