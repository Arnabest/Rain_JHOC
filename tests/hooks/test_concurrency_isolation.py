"""Concurrency & Multi-Session Isolation Integration Test (Round 4 Closure C3 / D3)."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE_ROOT / "src"))
sys.path.insert(0, str(WORKSPACE_ROOT / "scripts"))

from jhoc.quota.antigravity_quota import evaluate_quota_alert, get_antigravity_quota_live
from jhoc_hook_gate import evaluate_payload


class TestConcurrencyIsolation(unittest.TestCase):
    """Verifies that concurrent sessions never cross-contaminate and unknown sessions fail closed."""

    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.cache_dir = Path(self._temp_dir.name)

    def tearDown(self) -> None:
        self._temp_dir.cleanup()

    def test_session_scoped_cache_isolation(self) -> None:
        """D3: Session A (5% critical) and Session B (95% healthy) maintain strict isolation."""
        now = time.time()
        # Session A cache: Critical 5% (safe_sid for canonicalized 'session_a')
        import hashlib
        import unicodedata
        sid_a_hash = hashlib.sha256(unicodedata.normalize("NFC", "session_a").encode("utf-8")).hexdigest()[:24]
        file_a = self.cache_dir / f"antigravity_quota_cache_{sid_a_hash}.json"
        file_a.write_text(
            json.dumps({
                "timestamp": now,
                "data": {"enabled": True, "account_email": "tenant_a@ex.com", "gemini_5h_pct": 5.0, "gemini_weekly_pct": 10.0}
            }),
            encoding="utf-8",
        )

        # Session B cache: Healthy 95% (safe_sid for canonicalized 'session_b')
        sid_b_hash = hashlib.sha256(unicodedata.normalize("NFC", "session_b").encode("utf-8")).hexdigest()[:24]
        file_b = self.cache_dir / f"antigravity_quota_cache_{sid_b_hash}.json"
        file_b.write_text(
            json.dumps({
                "timestamp": now,
                "data": {"enabled": True, "account_email": "tenant_b@ex.com", "gemini_5h_pct": 95.0, "gemini_weekly_pct": 90.0}
            }),
            encoding="utf-8",
        )

        # Query Session A
        data_a = get_antigravity_quota_live(session_id="session_A", cache_dir=self.cache_dir)
        self.assertIsNotNone(data_a)
        self.assertEqual(data_a["gemini_5h_pct"], 5.0)
        alert_a = evaluate_quota_alert(data_a)
        self.assertTrue(alert_a.is_critical)
        self.assertEqual(alert_a.alert_level, "CRITICAL")

        # Query Session B
        data_b = get_antigravity_quota_live(session_id="session_B", cache_dir=self.cache_dir)
        self.assertIsNotNone(data_b)
        self.assertEqual(data_b["gemini_5h_pct"], 95.0)
        alert_b = evaluate_quota_alert(data_b)
        self.assertFalse(alert_b.is_critical)
        self.assertEqual(alert_b.alert_level, "OK")

        # Query Non-existent Session C: must NOT return Session A or B's data
        data_c = get_antigravity_quota_live(session_id="session_C", cache_dir=self.cache_dir)
        # Session C has no cache and live probe won't match -> None
        if data_c is not None:
            # If live probe ran in environment, ensure it did not cross-read A or B
            self.assertNotEqual(data_c.get("account_email"), "tenant_a@ex.com")
            self.assertNotEqual(data_c.get("account_email"), "tenant_b@ex.com")

    def test_gate_decision_isolation_across_sessions(self) -> None:
        """D3: Gate trips quota fuse for Session A (5%), allows Session B (95%), denies UNKNOWN."""
        now = time.time()
        # Session A: 5% (Critical)
        payload_a = {
            "conversationId": "session_A",
            "toolCall": {"name": "write_to_file", "args": {"TargetFile": "src/main.py", "CodeContent": "x = 1"}},
            "quota_data": {"enabled": True, "account_email": "tenant_a@ex.com", "gemini_5h_pct": 5.0, "gemini_weekly_pct": 10.0},
        }
        res_a = evaluate_payload(payload_a)
        self.assertEqual(res_a.get("decision"), "deny")
        self.assertIn("CRITICAL QUOTA", res_a.get("reason", ""))

        # Session B: 95% (Healthy)
        payload_b = {
            "conversationId": "session_B",
            "toolCall": {"name": "write_to_file", "args": {"TargetFile": "src/main.py", "CodeContent": "x = 1"}},
            "quota_data": {"enabled": True, "account_email": "tenant_b@ex.com", "gemini_5h_pct": 95.0, "gemini_weekly_pct": 90.0},
        }
        res_b = evaluate_payload(payload_b)
        self.assertEqual(res_b.get("decision"), "allow")

        # Session C: Quota probe unavailable (None) -> Fail-Closed Deny
        payload_c = {
            "conversationId": "session_C",
            "toolCall": {"name": "write_to_file", "args": {"TargetFile": "src/main.py", "CodeContent": "x = 1"}},
            "quota_data": None,
        }
        res_c = evaluate_payload(payload_c)
        self.assertEqual(res_c.get("decision"), "deny")
        self.assertIn("CRITICAL QUOTA", res_c.get("reason", ""))



    def test_canonicalization_anti_evasion(self) -> None:
        """R6-D6: Case, whitespace, and Unicode NFC variants share identical bucket identity."""
        variants = ["Tenant_Alpha", "tenant_alpha", "  Tenant_Alpha  ", "tenant_alpha\ufeff"]
        now = time.time()
        # Seed cache via one variant
        import hashlib, unicodedata
        norm = unicodedata.normalize("NFC", "tenant_alpha").strip().casefold()
        canon = "".join(ch for ch in norm if not unicodedata.category(ch).startswith("C")).strip()
        h = hashlib.sha256(canon.encode("utf-8")).hexdigest()[:24]
        target_file = self.cache_dir / f"antigravity_quota_cache_{h}.json"
        target_file.write_text(
            json.dumps({"timestamp": now, "data": {"enabled": True, "gemini_5h_pct": 4.0, "account_email": "anti_evasion@ex.com"}}),
            encoding="utf-8",
        )

        # All variants must read the exact same cache file and observe critical state
        for v in variants:
            data = get_antigravity_quota_live(session_id=v, cache_dir=self.cache_dir)
            self.assertIsNotNone(data, f"Variant '{v}' failed to resolve canonical cache")
            self.assertEqual(data["gemini_5h_pct"], 4.0)
            self.assertTrue(evaluate_quota_alert(data).is_critical)

if __name__ == "__main__":
    unittest.main()
