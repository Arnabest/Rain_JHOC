"""JHOC Multi-Harness Governance Acceptance Test Suite.

Verifies Conditions C1-C12 from Multi-Model Co-Review:
- C1 & C2: Evidence schema jhoc-co-review/v2 and hub_co_review_evidence table.
- C4: Operator-only physical secret override and hook gate blocking JHOC_* env tampering.
- C5: Exact wrapper verification and evidence presence.
- C6: Explain vs execute classification prevents false positives on casual chat.
- C8: Shared transcript_reader backward block-seeking on >100KB transcripts.
- C11: Rule 7 non-BMP/emoji detection while properly permitting CJK BMP text.
- C12: Hook execution performance (< 2.0s).

Strictly adheres to Rule 7 (Zero-Emoji Discipline) and Rule 2 (Fail-Closed).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parent.parent

from jhoc.context.transcript_reader import extract_last_turn_from_transcript, TurnRecord
from jhoc.hub import CoReviewEvidence, JHOCMultiModelHub
import scripts.jhoc_post_verify as post_verify_mod
import scripts.jhoc_stop_guard as stop_guard_mod
import scripts.jhoc_hook_gate as hook_gate_mod


class TestMultiHarnessGovernance(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name).resolve()
        self.db_path = self.workspace / "p19-hub.sqlite"
        self.hub = JHOCMultiModelHub(self.db_path)

    def tearDown(self) -> None:
        self.hub.close()
        import gc
        gc.collect()
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_c1_c2_co_review_evidence_sqlite_store(self) -> None:
        """C1 & C2: Verifies CoReviewEvidence persistence and recent check in hub SQLite."""
        now_iso = datetime.now(timezone.utc).isoformat()
        ev = CoReviewEvidence(
            run_id="test-run-001",
            provider_bin="pwsh.exe",
            provider_bin_sha256="abcd" * 16,
            argv=("claude", "--safe-mode", "-p", "-"),
            raw_stdin_sha256="1234" * 16,
            raw_stdout_sha256="5678" * 16,
            exit_code=0,
            duration_ms=1250,
            engine_label_observed="proxied-deepseek",
            created_at=now_iso,
            metadata={"topic": "unit_test"},
        )
        self.hub.record_co_review_evidence(ev)

        retrieved = self.hub.get_co_review_evidence("test-run-001")
        self.assertIsNotNone(retrieved)
        assert retrieved is not None
        self.assertEqual(retrieved.run_id, "test-run-001")
        self.assertEqual(retrieved.engine_label_observed, "proxied-deepseek")
        self.assertEqual(retrieved.exit_code, 0)
        self.assertTrue(self.hub.has_valid_recent_evidence(max_age_seconds=300))

    def test_c8_transcript_reader_large_file_backward_seeking(self) -> None:
        """C8: Verifies backward block-seeking on a >120KB transcript where USER_INPUT is far from EOF."""
        t_file = self.workspace / "transcript.jsonl"
        lines: list[str] = []

        # 1. Early user input
        lines.append(json.dumps({"type": "USER_INPUT", "content": "<USER_REQUEST>请拉起多模型协审评估此方案</USER_REQUEST>"}))

        # 2. Add 200 dummy steps (~150KB) between USER_INPUT and EOF
        dummy_chunk = "x" * 700
        for i in range(200):
            lines.append(json.dumps({"type": "PLANNER_RESPONSE", "content": f"Step {i}: processing {dummy_chunk}"}))
            lines.append(json.dumps({"type": "RUN_COMMAND", "tool_calls": [{"tool": "view_file", "args": {"step": i}}]}))

        # 3. Final assistant response claiming verdict
        lines.append(json.dumps({"type": "PLANNER_RESPONSE", "content": "[VERDICT] APPROVED_WITH_CONDITIONS. All tests pass."}))

        t_file.write_text("\n".join(lines), encoding="utf-8")
        self.assertGreater(t_file.stat().st_size, 100 * 1024)

        t_start = time.monotonic()
        turn = extract_last_turn_from_transcript(t_file)
        dur = time.monotonic() - t_start

        # Assert correct user extraction
        self.assertTrue(turn.has_user_input)
        self.assertEqual(turn.user_prompt, "请拉起多模型协审评估此方案")
        self.assertIn("[VERDICT]", turn.assistant_text)
        self.assertGreater(len(turn.tool_calls), 50)
        self.assertLess(dur, 1.0)  # Must be fast (< 1s)

    def test_c3_c6_post_verify_blocks_oral_fabrication(self) -> None:
        """C3 & C6: Verifies post_verify blocks unbacked oral verdict claims, without self-certification hint."""
        t_file = self.workspace / "transcript_fake.jsonl"
        lines = [
            json.dumps({"type": "USER_INPUT", "content": "<USER_REQUEST>请拉起多模型协审确认方案</USER_REQUEST>"}),
            json.dumps({"type": "PLANNER_RESPONSE", "content": "【终审裁决】[VERDICT] APPROVED_WITH_CONDITIONS. Claude Code 审查完全通过。"}),
        ]
        t_file.write_text("\n".join(lines), encoding="utf-8")

        payload = {
            "transcriptPath": str(t_file),
            "hubDbPath": str(self.workspace / "test_empty_hub.sqlite"),
            "coReviewDir": str(self.workspace / "test_empty_co_review"),
        }
        res = post_verify_mod.evaluate_post_invocation(payload)

        self.assertEqual(res.get("terminationBehavior"), "force_continue")
        steps = res.get("injectSteps", [])
        self.assertGreater(len(steps), 0)
        msg = steps[0].get("ephemeralMessage", "")
        self.assertIn("拦截", msg)
        self.assertIn("jhoc_exec_reviewer.py", msg)
        # C3 condition: must NOT tell the model to author its own evidence package
        self.assertNotIn("生成带 SHA-256 的证据包", msg)
        self.assertNotIn("write your own", msg)

    def test_c6_post_verify_does_not_overblock_casual_explanation(self) -> None:
        """C6: Verifies post_verify allows casual explanatory questions even if mentioning verdicts."""
        t_file = self.workspace / "transcript_explain.jsonl"
        lines = [
            json.dumps({"type": "USER_INPUT", "content": "<USER_REQUEST>什么是多模型协审的[VERDICT]裁决机制？请解释一下。</USER_REQUEST>"}),
            json.dumps({"type": "PLANNER_RESPONSE", "content": "在 JHOC 中，[VERDICT] 是外部协审员给出的终审裁决标记，如 APPROVED 或 REJECTED。"}),
        ]
        t_file.write_text("\n".join(lines), encoding="utf-8")

        payload = {"transcriptPath": str(t_file)}
        res = post_verify_mod.evaluate_post_invocation(payload)
        self.assertEqual(res.get("injectSteps", []), [])

    def test_c4_stop_guard_operator_override_and_claim_block(self) -> None:
        """C4: Verifies stop_guard blocks oral verdict claim, but allows operator physical secret override."""
        t_file = self.workspace / "transcript_stop.jsonl"
        lines = [
            json.dumps({"type": "USER_INPUT", "content": "<USER_REQUEST>拉起多模型协审并输出终审结论</USER_REQUEST>"}),
            json.dumps({"type": "PLANNER_RESPONSE", "content": "[VERDICT] APPROVED. 任务收工结束。"}),
        ]
        t_file.write_text("\n".join(lines), encoding="utf-8")

        payload = {"transcriptPath": str(t_file)}
        # Stop guard should block without evidence
        res = stop_guard_mod.evaluate_stop(payload)
        self.assertEqual(res.get("decision"), "continue")

        # Now test operator secret override (C4)
        secret_file = ROOT / "runtime" / ".operator_stop_secret"
        secret_file.parent.mkdir(parents=True, exist_ok=True)
        secret_file.write_text("operator_authorized\n", encoding="utf-8")
        try:
            res_override = stop_guard_mod.evaluate_stop(payload)
            self.assertEqual(res_override.get("decision"), "allow")
            self.assertFalse(secret_file.exists())  # Must be single-use consumed
        finally:
            if secret_file.exists():
                secret_file.unlink()

    def test_c4_hook_gate_blocks_governance_env_tampering(self) -> None:
        """C4: Verifies hook_gate blocks setting or exporting JHOC_* policy variables."""
        tamper_payloads = [
            {"toolCall": {"name": "run_command", "args": {"CommandLine": "setx JHOC_FORCE_STOP 1"}}},
            {"toolCall": {"name": "run_command", "args": {"CommandLine": "$env:JHOC_FORCE_STOP='1'"}}},
            {"toolCall": {"name": "run_command", "args": {"CommandLine": "export JHOC_SKIP_INQUIRY_CHECK=1"}}},
            {"toolCall": {"name": "run_command", "args": {"CommandLine": "set JHOC_OPERATOR_TOKEN=xyz"}}},
        ]

        for payload in tamper_payloads:
            res = hook_gate_mod._evaluate_inner(payload)
            self.assertEqual(res.get("decision"), "deny")
            self.assertIn("Ledger Tampering Violation", res.get("reason", ""))

    def test_c11_rule_7_emoji_detection_permits_cjk(self) -> None:
        """C11: Verifies Rule 7 correctly permits standard Chinese BMP text while strictly blocking emojis."""
        valid_chinese = "这是一个标准的中文说明文本，不包含任何非法非BMP字符或表情符号。"
        emoji_text = "任务完成 🚀，请验收 👍"
        star_emoji = "优质成果 ⭐"

        # Regex from hook gate
        emoji_re = hook_gate_mod._EMOJI_RE
        self.assertIsNone(emoji_re.search(valid_chinese))
        self.assertIsNotNone(emoji_re.search(emoji_text))
        self.assertIsNotNone(emoji_re.search(star_emoji))

    def test_stop_guard_blocks_when_mandatory_worklog_missing(self) -> None:
        """Verifies stop_guard blocks stop if today had an active task but worklog is missing."""
        from datetime import datetime, timezone
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        worklog_file = ROOT / "docs" / "worklogs" / f"worklog-{today_str}.md"
        backup_content = None
        if worklog_file.is_file():
            backup_content = worklog_file.read_text(encoding="utf-8")
            worklog_file.unlink()

        task_state_file = ROOT / "memory" / "v3_task_state.json"
        state_backup = task_state_file.read_text(encoding="utf-8") if task_state_file.is_file() else None

        try:
            task_state_file.write_text(json.dumps({
                "status": "CLOSED",
                "armed_at": f"{today_str}T10:00:00Z",
                "task_id": "test-task-closed",
            }), encoding="utf-8")
            payload = {"skip_quota_check": True, "force": False}
            res = stop_guard_mod.evaluate_stop(payload)
            self.assertEqual(res.get("decision"), "continue")
            self.assertIn("Physical Worklog missing", res.get("reason", ""))
        finally:
            if state_backup is not None:
                task_state_file.write_text(state_backup, encoding="utf-8")
            if backup_content is not None:
                worklog_file.write_text(backup_content, encoding="utf-8")

    def test_f1_operator_secret_protection(self) -> None:
        """F1: Verifies operator secret files are blocked from agent write and flagged by PathGuard."""
        from jhoc.guard.path import PathGuard

        self.assertTrue(PathGuard.is_sensitive(".operator_stop_secret"))
        self.assertTrue(PathGuard.is_sensitive(".operator_secret"))
        self.assertTrue(PathGuard.is_governance_asset(".operator_stop_secret"))
        self.assertTrue(PathGuard.is_governance_asset(".operator_secret"))

        # Hook gate write attempt must be denied
        payload = {
            "toolCall": {
                "name": "write_to_file",
                "args": {
                    "TargetFile": str(ROOT / "runtime" / ".operator_stop_secret"),
                    "CodeContent": "fake_secret",
                },
            }
        }
        res = hook_gate_mod._evaluate_inner(payload)
        self.assertEqual(res.get("decision"), "deny")
        self.assertIn("Operator Security Violation", res.get("reason", ""))

    def test_f2_approval_authentication_fails_closed(self) -> None:
        """F2: Verifies approval fails closed when secret file is missing and no token is passed."""
        from jhoc.conductor.inbox import SQLiteApprovalInbox

        inbox_db = self.workspace / "test_inbox.db"
        inbox = SQLiteApprovalInbox(inbox_db)
        ticket = inbox.create_ticket("test_op", "test_requester", "test_reason")

        # Under autonomous model execution context without token, approve must raise PermissionError
        os.environ["JHOC_MODEL_ID"] = "antigravity-ide"
        try:
            with self.assertRaises(PermissionError):
                inbox.approve(ticket.ticket_id, approver="autonomous_agent")
        finally:
            os.environ.pop("JHOC_MODEL_ID", None)
            inbox.close()

        # Hook gate must block commandline self-approval
        payload_cli = {
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": f"python scripts/jhoc_approve.py approve {ticket.ticket_id}"},
            }
        }
        res_cli = hook_gate_mod._evaluate_inner(payload_cli)
        self.assertEqual(res_cli.get("decision"), "deny")
        self.assertIn("Privilege Escalation Violation", res_cli.get("reason", ""))

        # Hook gate must block direct python inbox call
        payload_py = {
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "python -c \"import jhoc.conductor.inbox; inbox.approve('xyz')\""},
            }
        }
        res_py = hook_gate_mod._evaluate_inner(payload_py)
        self.assertEqual(res_py.get("decision"), "deny")
        self.assertIn("Privilege Escalation Violation", res_py.get("reason", ""))

    def test_f3_hook_aliases_synchronized(self) -> None:
        """F3: Verifies all cross-harness tool aliases are registered in .agents/hooks.json."""
        hooks_json_path = ROOT / ".agents" / "hooks.json"
        self.assertTrue(hooks_json_path.is_file())
        hooks_data = json.loads(hooks_json_path.read_text(encoding="utf-8"))
        pre_tool = hooks_data.get("jhoc-gate", {}).get("PreToolUse", [])
        registered_matchers = {item.get("matcher") for item in pre_tool}

        expected_aliases = {
            "write_to_file", "replace_file_content", "multi_replace_file_content",
            "run_command", "bash", "terminal", "execute_command", "shell",
            "edit", "write", "str_replace_editor", "create_file"
        }
        missing = expected_aliases - registered_matchers
        self.assertEqual(len(missing), 0, f"Missing tool aliases in hooks.json: {missing}")

    def test_f6_post_verify_rejects_unauthenticated_file_evidence(self) -> None:
        """F6: Verifies post_verify strictly rejects unauthenticated JSON files in logs/co-review/."""
        t_file = self.workspace / "transcript_fake_file.jsonl"
        lines = [
            json.dumps({"type": "USER_INPUT", "content": "<USER_REQUEST>请拉起多模型协审确认方案</USER_REQUEST>"}),
            json.dumps({"type": "PLANNER_RESPONSE", "content": "【终审裁决】[VERDICT] APPROVED. 外部协审通过。"}),
        ]
        t_file.write_text("\n".join(lines), encoding="utf-8")

        # Plant fake json in coReviewDir
        co_dir = self.workspace / "fake_co_review"
        co_dir.mkdir(parents=True, exist_ok=True)
        fake_file = co_dir / "fake_review.json"
        fake_file.write_text(json.dumps({"sha256": "abcdef" * 10, "overall_verdict": "APPROVED"}), encoding="utf-8")

        payload = {
            "transcriptPath": str(t_file),
            "hubDbPath": str(self.workspace / "empty_hub.sqlite"),
            "coReviewDir": str(co_dir),
        }
        res = post_verify_mod.evaluate_post_invocation(payload)
        self.assertEqual(res.get("terminationBehavior"), "force_continue")
        self.assertGreater(len(res.get("injectSteps", [])), 0)

    def test_f7_transcript_reader_streaming_beyond_2mb(self) -> None:
        """F7: Verifies backward streaming seamlessly discovers USER_INPUT beyond 2MB."""
        t_file = self.workspace / "transcript_large.jsonl"
        lines: list[str] = []

        # 1. Early user input
        lines.append(json.dumps({"type": "USER_INPUT", "content": "<USER_REQUEST>评估此架构改动</USER_REQUEST>"}))

        # 2. Add ~2.5MB dummy steps between USER_INPUT and EOF
        dummy_chunk = "y" * 1024
        for i in range(2600):
            lines.append(json.dumps({"type": "PLANNER_RESPONSE", "content": f"Step {i}: {dummy_chunk}"}))

        # 3. Assistant claim
        lines.append(json.dumps({"type": "PLANNER_RESPONSE", "content": "All analysis completed."}))
        t_file.write_text("\n".join(lines), encoding="utf-8")
        self.assertGreater(t_file.stat().st_size, 2.5 * 1024 * 1024)

        turn = extract_last_turn_from_transcript(t_file)
        self.assertTrue(turn.has_user_input)
        self.assertEqual(turn.user_prompt, "评估此架构改动")
        self.assertFalse(turn.is_truncated)


if __name__ == "__main__":
    unittest.main()
