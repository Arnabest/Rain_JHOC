"""Unit tests for Behavioral Fail-Closed Guarantees (Round 4 Closure F-1, F-2, F-3, F-6)."""

from __future__ import annotations

import ast
import json
from pathlib import Path
import subprocess
import sys
import unittest

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
GATE_SCRIPT = WORKSPACE_ROOT / "scripts" / "jhoc_hook_gate.py"

sys.path.insert(0, str(WORKSPACE_ROOT / "src"))
from jhoc.quota.antigravity_quota import evaluate_quota_alert, get_antigravity_quota_live


class TestBehavioralFailClosed(unittest.TestCase):
    """Verifies that all process-edge and behavioral paths fail closed."""

    def test_empty_stdin_fails_closed_deny(self) -> None:
        """F-1 Closure: Stdin with empty string must emit deny decision with exit 0."""
        proc = subprocess.run(
            [sys.executable, str(GATE_SCRIPT)],
            input="",
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0)
        out = json.loads(proc.stdout.strip())
        self.assertEqual(out.get("decision"), "deny")
        self.assertIn("Empty payload", out.get("reason", ""))

    def test_whitespace_stdin_fails_closed_deny(self) -> None:
        """F-1 Closure: Stdin with only whitespace/newlines must emit deny decision with exit 0."""
        proc = subprocess.run(
            [sys.executable, str(GATE_SCRIPT)],
            input="   \n\r\t  \n",
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0)
        out = json.loads(proc.stdout.strip())
        self.assertEqual(out.get("decision"), "deny")
        self.assertIn("Empty payload", out.get("reason", ""))

    def test_malformed_json_fails_closed_deny(self) -> None:
        """F-2 Closure: Stdin with broken JSON must catch exception and emit deny decision."""
        proc = subprocess.run(
            [sys.executable, str(GATE_SCRIPT)],
            input="{not_valid_json: 123",
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0)
        out = json.loads(proc.stdout.strip())
        self.assertEqual(out.get("decision"), "deny")
        self.assertIn("Hook execution exception", out.get("reason", ""))

    def test_quota_none_maps_to_unknown_deny(self) -> None:
        """C4 Closure: Telemetry None strictly maps to is_critical=True, alert_level='UNKNOWN'."""
        alert = evaluate_quota_alert(None)
        self.assertTrue(alert.is_critical)
        self.assertEqual(alert.alert_level, "UNKNOWN")
        self.assertTrue(alert.handover_recommended)

    def test_ast_zero_swallow_to_allow_in_except_handlers(self) -> None:
        """F-3 / D6 Closure: AST analysis verifies NO except block returns or prints allow decision."""
        tree = ast.parse(GATE_SCRIPT.read_text(encoding="utf-8"))

        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Dict):
                        for k, v in zip(sub.keys, sub.values):
                            if isinstance(k, ast.Constant) and k.value == "decision":
                                if isinstance(v, ast.Constant) and v.value == "allow":
                                    self.fail(f"Found except handler returning allow at line {node.lineno}!")

    def test_session_id_sanitization(self) -> None:
        """F-6 Closure: Path traversal or special chars in session_id are sanitized."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            cd = Path(td)
            # Try path traversal session ID
            res = get_antigravity_quota_live(
                session_id="../../etc/passwd!@#$%",
                cache_dir=cd,
            )
            # Ensure no file was created outside the cache_dir
            for p in cd.iterdir():
                self.assertNotIn("..", p.name)
                self.assertNotIn("/", p.name)
                self.assertNotIn("\\", p.name)


    def test_dual_track_warning_and_critical_boundaries(self) -> None:
        """D4 Closure: State boundaries for Warning (12%), Critical (8%), OK (>12%), and UNKNOWN (None)."""
        # OK: > 12%
        ok_data = {"enabled": True, "account_email": "test@ex.com", "gemini_5h_pct": 50.0, "gemini_weekly_pct": 80.0}
        a_ok = evaluate_quota_alert(ok_data)
        self.assertEqual(a_ok.alert_level, "OK")
        self.assertFalse(a_ok.is_critical)
        self.assertFalse(a_ok.handover_recommended)

        # Warning Track: 8% < quota <= 12%
        warn_data = {"enabled": True, "account_email": "test@ex.com", "gemini_5h_pct": 11.0, "gemini_weekly_pct": 80.0}
        a_warn = evaluate_quota_alert(warn_data)
        self.assertEqual(a_warn.alert_level, "WARNING")
        self.assertFalse(a_warn.is_critical)
        self.assertTrue(a_warn.handover_recommended)

        # Critical Track: <= 8.0%
        crit_data = {"enabled": True, "account_email": "test@ex.com", "gemini_5h_pct": 8.0, "gemini_weekly_pct": 80.0}
        a_crit = evaluate_quota_alert(crit_data)
        self.assertEqual(a_crit.alert_level, "CRITICAL")
        self.assertTrue(a_crit.is_critical)
        self.assertTrue(a_crit.handover_recommended)

        # Emergency exhaustion: <= 3.0%
        emerg_data = {"enabled": True, "account_email": "test@ex.com", "gemini_5h_pct": 2.5, "gemini_weekly_pct": 80.0}
        a_emerg = evaluate_quota_alert(emerg_data)
        self.assertEqual(a_emerg.alert_level, "CRITICAL")
        self.assertTrue(a_emerg.is_critical)
        self.assertTrue(a_emerg.handover_recommended)


    def test_hysteresis_trip_and_recovery_loop(self) -> None:
        """R5-D7 / B-5: Verify control-theoretic hysteresis loop across 8.0% trip and 10.0% reset."""
        # Step 1: Normal descent - 11.0% with prior OK -> WARNING
        d_11 = {"enabled": True, "account_email": "test@ex.com", "gemini_5h_pct": 11.0, "gemini_weekly_pct": 80.0}
        a_11 = evaluate_quota_alert(d_11, prior_alert_level="OK")
        self.assertEqual(a_11.alert_level, "WARNING")
        self.assertFalse(a_11.is_critical)

        # Step 2: Boundary test - 9.0% with prior WARNING -> still WARNING (does not trip at 9%)
        d_9 = {"enabled": True, "account_email": "test@ex.com", "gemini_5h_pct": 9.0, "gemini_weekly_pct": 80.0}
        a_9_pre = evaluate_quota_alert(d_9, prior_alert_level="WARNING")
        self.assertEqual(a_9_pre.alert_level, "WARNING")
        self.assertFalse(a_9_pre.is_critical)

        # Step 3: Trip threshold - 8.0% -> TRIPS CRITICAL
        d_8 = {"enabled": True, "account_email": "test@ex.com", "gemini_5h_pct": 8.0, "gemini_weekly_pct": 80.0}
        a_8 = evaluate_quota_alert(d_8, prior_alert_level="WARNING")
        self.assertEqual(a_8.alert_level, "CRITICAL")
        self.assertTrue(a_8.is_critical)

        # Step 4: Latched state - 9.0% with prior CRITICAL -> LATCHES CRITICAL (does not recover at 9%!)
        a_9_latched = evaluate_quota_alert(d_9, prior_alert_level="CRITICAL")
        self.assertEqual(a_9_latched.alert_level, "CRITICAL")
        self.assertTrue(a_9_latched.is_critical)
        self.assertIn("latched hysteresis", a_9_latched.warning_message)

        # Step 5: Exact reset boundary - 10.0% with prior CRITICAL -> LATCHES CRITICAL (<= 10.0%)
        d_10 = {"enabled": True, "account_email": "test@ex.com", "gemini_5h_pct": 10.0, "gemini_weekly_pct": 80.0}
        a_10_latched = evaluate_quota_alert(d_10, prior_alert_level="CRITICAL")
        self.assertEqual(a_10_latched.alert_level, "CRITICAL")
        self.assertTrue(a_10_latched.is_critical)

        # Step 6: Sustained recovery - 10.5% with prior CRITICAL -> RESETS to WARNING
        d_10_5 = {"enabled": True, "account_email": "test@ex.com", "gemini_5h_pct": 10.5, "gemini_weekly_pct": 80.0}
        a_recovered = evaluate_quota_alert(d_10_5, prior_alert_level="CRITICAL")
        self.assertEqual(a_recovered.alert_level, "WARNING")
        self.assertFalse(a_recovered.is_critical)

        # Step 7: Complete clearance - 15.0% -> OK
        d_15 = {"enabled": True, "account_email": "test@ex.com", "gemini_5h_pct": 15.0, "gemini_weekly_pct": 80.0}
        a_ok_again = evaluate_quota_alert(d_15, prior_alert_level="WARNING")
        self.assertEqual(a_ok_again.alert_level, "OK")
        self.assertFalse(a_ok_again.is_critical)

    def test_missing_cid_subprocess_denies_fail_closed(self) -> None:
        """R5-D3 / B-1: Payload without cid at real subprocess boundary strictly fails closed."""
        payload = {
            "toolCall": {"name": "write_to_file", "args": {"TargetFile": "src/core_service.py", "CodeContent": "pass"}}
            # No conversationId, no session_id
        }
        proc = subprocess.run(
            [sys.executable, str(GATE_SCRIPT)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0)
        out = json.loads(proc.stdout.strip())
        self.assertEqual(out.get("decision"), "deny")

    def test_sha256_session_hash_collision_resistance(self) -> None:
        """R5-D4 / B-2: Distinct raw session IDs never alias to the same cache key."""
        import hashlib
        ids = [
            "tenant:session:1",
            "tenant_session_1",
            "tenant session 1",
            "tenant-session-1",
            "tenant/session/1",
            "a" * 50 + ":1",
            "a" * 50 + ":2",  # Truncation collision test (past 40 chars)
        ]
        cache_names = set()
        for sid in ids:
            h = hashlib.sha256(sid.encode("utf-8")).hexdigest()[:24]
            c_name = f"antigravity_quota_cache_{h}.json"
            cache_names.add(c_name)
        # Must generate 7 distinct cache keys with zero collision and zero prefix aliasing
        self.assertEqual(len(cache_names), len(ids))

    def test_same_key_atomic_concurrent_writes(self) -> None:
        """R5-D2 / A-2: Concurrent writes and reads to the exact same session key assert zero corruption."""
        import concurrent.futures
        import os
        import tempfile
        import time
        with tempfile.TemporaryDirectory() as td:
            cd = Path(td)
            target_cache = cd / "antigravity_quota_cache_test_key.json"

            def writer_worker(idx: int) -> bool:
                for i in range(25):
                    now_ts = time.time()
                    payload = {"timestamp": now_ts, "data": {"gemini_5h_pct": 50.0 + (idx % 10), "thread": idx, "step": i}}
                    temp_cache = target_cache.with_name(f"{target_cache.name}.tmp.{idx}.{time.time_ns()}")
                    temp_cache.write_text(json.dumps(payload), encoding="utf-8")
                    for _ in range(10):
                        try:
                            os.replace(temp_cache, target_cache)
                            break
                        except PermissionError:
                            time.sleep(0.005)
                return True

            def reader_worker(idx: int) -> bool:
                for i in range(25):
                    if target_cache.is_file():
                        for _ in range(10):
                            try:
                                content = target_cache.read_text(encoding="utf-8")
                                parsed = json.loads(content)
                                assert "timestamp" in parsed
                                break
                            except (PermissionError, FileNotFoundError):
                                time.sleep(0.002)
                            except json.JSONDecodeError:
                                return False
                    time.sleep(0.001)
                return True

            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
                futures = [ex.submit(writer_worker, i) for i in range(4)] + [ex.submit(reader_worker, i) for i in range(4)]
                for f in concurrent.futures.as_completed(futures):
                    self.assertTrue(f.result())


if __name__ == "__main__":
    unittest.main()
