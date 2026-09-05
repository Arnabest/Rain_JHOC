"""Antigravity IDE Hook Adapter for Governance Engine.

Provides sub-millisecond tail reading of transcript.jsonl, intent classification,
and structured ephemeralMessage injection.
Enforces strict 15ms watchdog budget to protect IDE interactivity.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

try:
    from ..core.tri_tier_classifier import GovernanceIntentEngine
except ImportError:
    core_dir = Path(__file__).resolve().parent.parent / "core"
    if str(core_dir) not in sys.path:
        sys.path.insert(0, str(core_dir))
    from tri_tier_classifier import GovernanceIntentEngine


def extract_latest_user_prompt_fast(transcript_path: Path, max_tail_bytes: int = 8192) -> str:
    """Reads only the last N bytes of transcript.jsonl to avoid linear O(file) scan."""
    if not transcript_path.is_file():
        return ""

    try:
        size = transcript_path.stat().st_size
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
            if size > max_tail_bytes:
                f.seek(size - max_tail_bytes)
            chunk = f.read()

        lines = chunk.strip().split("\n")
        for line in reversed(lines):
            line_s = line.strip()
            if not line_s or '"type":"USER_INPUT"' not in line_s and '"type": "USER_INPUT"' not in line_s:
                continue
            try:
                data = json.loads(line_s)
                if data.get("type") == "USER_INPUT":
                    content = data.get("content", "")
                    m = re.search(r"<USER_REQUEST>(.*?)</USER_REQUEST>", content, re.DOTALL)
                    if m:
                        return m.group(1).strip()
                    return content.strip()
            except Exception:
                continue
    except Exception:
        pass
    return ""


class IDEHookDriver:
    """Handles PreInvocation and PostInvocation lifecycles within Antigravity IDE."""

    def __init__(self, workspace_root: Path | None = None) -> None:
        self.root = workspace_root or ROOT
        self.engine = GovernanceIntentEngine(self.root)

    def evaluate_pre_invocation(self, payload: dict, timeout_ms: float = 20.0) -> dict:
        t0 = time.monotonic()
        steps: list[dict[str, Any]] = []

        # 1. Active Task Lifecycle Guard
        state_file = self.root / "memory" / "v3_task_state.json"
        if state_file.is_file():
            try:
                state = json.loads(state_file.read_text(encoding="utf-8"))
                if state.get("status") == "ARMED":
                    title = state.get("title", "Active Task")
                    task_id = state.get("task_id", "")
                    sha = state.get("git_baseline_sha", "HEAD")[:10]
                    inquiry_status = state.get("inquiry_status", "CONFIRMED")
                    inquiry_alert = " [INQUIRY PENDING]" if inquiry_status == "PENDING" else ""
                    msg = (
                        f"[JHOC LIFECYCLE GUARD] Active Task: '{title}' ({task_id}){inquiry_alert} [Baseline: {sha}]. "
                        "Skill Ordering: INCEPTION -> ELABORATION -> ARM -> EXECUTE -> VERIFY (shougong) -> CLOSE. "
                        "Before completing your response, you MUST execute 'python scripts/jhoc_shougong.py' to close the task."
                    )
                    steps.append({"ephemeralMessage": msg})
            except Exception:
                pass

        # Check timeout budget
        if (time.monotonic() - t0) * 1000.0 > timeout_ms:
            return {"injectSteps": steps}

        # 2. Extract Latest User Prompt from Transcript
        transcript_path_str = payload.get("transcriptPath")
        if transcript_path_str:
            t_path = Path(transcript_path_str)
        else:
            cid = payload.get("conversationId") or payload.get("session_id")
            if not cid:
                brain = Path.home() / ".gemini" / "antigravity-ide" / "brain"
                if brain.is_dir():
                    cand = sorted(brain.glob("*/.system_generated/logs/transcript.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
                    if cand:
                        cid = cand[0].parent.parent.parent.name
            t_path = Path.home() / ".gemini" / "antigravity-ide" / "brain" / (cid or "") / ".system_generated" / "logs" / "transcript.jsonl"

        user_prompt = extract_latest_user_prompt_fast(t_path)
        if user_prompt:
            res = self.engine.classify(user_prompt)
            if res.ephemeral_lines:
                combined_msg = "\n".join(res.ephemeral_lines)
                steps.append({"ephemeralMessage": combined_msg})

                # Log into Hub SQLite if possible
                self._record_hub_intent(user_prompt, res)

        return {"injectSteps": steps}

    def _record_hub_intent(self, prompt: str, res: Any) -> None:
        hub_db = self.root / "logs" / "p19-hub.sqlite"
        if not hub_db.is_file():
            return
        try:
            import sqlite3
            now_iso = datetime.now(timezone.utc).isoformat()
            msg_id = f"intent-{int(time.time()*1000)}"
            with sqlite3.connect(str(hub_db), timeout=1.0) as conn:
                conn.execute(
                    """
                    INSERT INTO hub_messages (message_id, source_model, target_model, operation, payload_json, correlation_id, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        msg_id,
                        "governance-engine",
                        "antigravity-ide",
                        "INTENT_DETECTED",
                        json.dumps({"prompt": prompt[:200], "intent": res.intent.value, "tier": res.tier_hit, "tools": res.matched_asset.executable_tools if res.matched_asset else []}, ensure_ascii=False),
                        "session-active",
                        "COMPLETED",
                        now_iso,
                        now_iso,
                    ),
                )
                conn.commit()
        except Exception:
            pass
