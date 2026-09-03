"""JHOC PreInvocation Context & Memory Injector."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent


def evaluate_pre_invocation(payload: dict) -> dict:
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

    return {"injectSteps": steps}


def main() -> None:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        payload = {}

    res = evaluate_pre_invocation(payload)
    print(json.dumps(res, ensure_ascii=True))


if __name__ == "__main__":
    main()
