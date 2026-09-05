"""JHOC Multi-Model Co-Review Dispatcher for Intent Distillation & Local Asset Matching Pipeline.

Dispatches the architectural plan to local Claude Code and Codex CLI,
capturing their genuine verbatim critiques and persisting in p19-hub.sqlite and logs/co-review/.
Strictly adheres to Rule 7 (Zero-Emoji Discipline) and Rule 0 (Anti-Sycophancy).
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


REVIEW_PROMPT = """You are a Principal Systems Architect and Red-Team Reviewer auditing a core enhancement to the JHOC Multi-Agent Governance Framework.

[STRICT OPERATING CONSTRAINT]
Do NOT execute any tools or modify files on disk. Evaluate this architecture purely based on the engineering specifications provided below. Output ASCII only (NO emojis).

[ARCHITECTURAL PROBLEM DEFINITION]
1. Problem 1 (Runtime Wiring Gap for Intent & Lessons):
   - JHOC has an IntentClassifier (src/jhoc/intent/classifier.py), a lessons store (src/jhoc/lessons/store.py), and a skill shelf (src/jhoc/shelf/loader.py).
   - However, during actual user prompt execution, the IDE's PreInvocation hook (scripts/jhoc_pre_inject.py) did not extract the latest user request from transcript, did not classify intent, and did not inject relevant shelf skills or past negative lessons (e.g. Lesson #147: Never roleplay external models; Lesson #402: Paper architecture without dynamic recall).
   - As a result, when given prompts like '拉起多模型协审', the agent succumbed to autoregressive impulsiveness and roleplayed external model dialogue rather than calling the real CLI tools.

2. Problem 2 (Manual Regex Brittle Scaling):
   - The intent classifier's Tier 1 regexes are manually hardcoded and brittle. New tasks and user prompt variations often fall back to GENERAL_CONVERSATION with zero scaffolding.

[PROPOSED 4-STAGE ARCHITECTURAL SOLUTION]
1. Automated Experience Distillation at Task Closure (Flywheel 1):
   - In jhoc_shougong.py / jhoc_worklog.py, parse the completed task's prompt, modified files, tools used, and rules adhered to, creating a structured TaskExperienceRecord.
   - Update docs/lessons/*.md atomically via LessonsAccumulator.

2. Local Asset Inverted Index & Graph Projection (Flywheel 2):
   - A single-node offline index builder (scripts/build_asset_index.py) scans:
     a) All .agents/skills/*/SKILL.md via SkillShelfLoader (extracts triggers, when_to_use, categories);
     b) All docs/lessons/*.md via LessonsStore (extracts lesson_id, symptom, root_cause, rule);
     c) All scripts/jhoc_*.py tools (extracts cli commands, descriptions);
   - Projects into a unified local index logs/local_asset_index.json linking:
     Intent / Trigger -> [Matched Skill] + [Executable Script] + [Negative Lessons / Anti-Patterns] + [Verification Tests].

3. Tri-Tier Hybrid Intent Engine (Flywheel 3):
   - Tier 1: Deterministic regex and exact command anchors (<0.1ms);
   - Tier 2: Local token overlap & BM25 lexical similarity against the projected asset index (~1ms, pure Python / SQLite FTS5, no heavy external dependencies);
   - Tier 3: Local structured LLM arbitration fallback only when confidence is in gray zone (0.3 ~ 0.6).

4. Multi-Stage Phased Context Injection & Physical Friction Brake (Flywheel 4):
   - Stage 1 (Pre-Invocation Hook): Extracts latest user prompt from transcript, queries the index (<5ms), and injects a 3-line ephemeralMessage:
     Line 1: Detected Intent & Scaffolding Skill Path;
     Line 2: Target CLI Tool to run (e.g., scripts/jhoc_co_review.py);
     Line 3: Top negative lesson warning (e.g. [LESSON #147]: Strictly forbidden to roleplay external models; must invoke real CLI!).
   - Stage 2 (Pre-Tool Hook Gate): Physically denies code mutation if inquiry is pending (Check 4.5) or if mutating protected files without review, providing actionable error reason.
   - Stage 3 (Stop Guard Hook): Physically denies session exit if 36 co-review & handoff package have not been generated.

[AUDIT TASK]
Please evaluate this architectural proposal across 4 dimensions:
1. Feasibility & Latency Budget: Can the transcript extraction, Tier 1/Tier 2 classification, and ephemeral injection execute within a strict 10ms-20ms budget on every user turn without lagging the IDE?
2. Determinism vs Drift: How to prevent the automated indexing and token matching from drifting or producing false-positive skill activations?
3. Anti-Impulse Effectiveness: Will the combination of JIT negative lesson injection (Pre-Invocation) and fail-closed physical gating (Pre-Tool) truly suppress model hallucinations and roleplaying?
4. Edge Cases & Implementation Traps: What potential deadlocks, Windows file path encoding issues, or concurrency conflicts must be safeguarded against?

Format your response in plain text / ASCII (NO emojis):
- [VERDICT] <APPROVED / APPROVED_WITH_CONDITIONS / REJECTED>
- [ANALYSIS-LATENCY-AND-FEASIBILITY]
- [ANALYSIS-DETERMINISM-AND-DRIFT]
- [ANALYSIS-ANTI-IMPULSE-EFFECTIVENESS]
- [EDGE-CASES-AND-RECOMMENDATIONS]
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
            timeout=120,
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
    out_file = ROOT / "runtime" / "codex_review_intent.txt"
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
    corr_id = f"co-review-intent-assets-{now_str}"

    print("=== [JHOC REAL MULTI-MODEL CO-REVIEW: INTENT & ASSET MATCHING] ===")
    print(f"[INFO] Correlation ID: {corr_id}")

    hub.register_presence("antigravity-ide", ModelPresenceState.CO_REVIEWING, metadata={"topic": "intent_and_assets"})
    hub.register_presence("claude-code", ModelPresenceState.CO_REVIEWING, metadata={"topic": "intent_and_assets"})
    hub.register_presence("codex-cli", ModelPresenceState.CO_REVIEWING, metadata={"topic": "intent_and_assets"})

    # 1. Dispatch to Claude Code
    msg_claude = hub.send_message(
        "antigravity-ide", "claude-code", "CO_REVIEW",
        {"prompt": REVIEW_PROMPT, "topic": "intent_and_assets"},
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
        {"prompt": REVIEW_PROMPT, "topic": "intent_and_assets"},
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
    record_file = ROOT / "logs" / "co-review" / f"{now_str}-intent-and-assets-co-review.json"
    record_file.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": "jhoc-co-review/v1",
        "task_id": f"intent-assets-review-{now_str}",
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
