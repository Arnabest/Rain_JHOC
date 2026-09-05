from __future__ import annotations

import datetime
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jhoc.quota.antigravity_quota import (
    CRITICAL_THRESHOLD_PERCENT,
    QuotaAlert,
    evaluate_quota_alert,
    format_iso_reset,
    format_quota_markdown,
)
from scripts.jhoc_token_stats import est_tokens, analyze_transcript


class TestJhocTokenStats(unittest.TestCase):
    def test_evaluate_quota_alert_ok(self) -> None:
        quota_data = {
            "enabled": True,
            "account_email": "test_user@gmail.com",
            "gemini_5h_pct": 95,
            "gemini_5h_reset": "~4h30m",
            "gemini_weekly_pct": 90,
            "gemini_weekly_reset": "~5d12h",
        }
        alert = evaluate_quota_alert(quota_data, threshold_pct=8.0)
        self.assertFalse(alert.is_critical)
        self.assertEqual(alert.alert_level, "OK")
        self.assertEqual(alert.critical_buckets, ())
        self.assertEqual(alert.account_email, "test_user@gmail.com")
        self.assertFalse(alert.handover_recommended)

    def test_evaluate_quota_alert_critical_5h(self) -> None:
        quota_data = {
            "enabled": True,
            "account_email": "test_user@gmail.com",
            "gemini_5h_pct": 7,
            "gemini_5h_reset": "~1h15m",
            "gemini_weekly_pct": 80,
            "gemini_weekly_reset": "~5d",
        }
        alert = evaluate_quota_alert(quota_data, threshold_pct=8.0)
        self.assertTrue(alert.is_critical)
        self.assertEqual(alert.alert_level, "CRITICAL")
        self.assertIn("5-Hour Limit", alert.critical_buckets)
        self.assertTrue(alert.handover_recommended)
        self.assertIn("[CRITICAL QUOTA ALERT]", alert.warning_message)

    def test_evaluate_quota_alert_critical_weekly(self) -> None:
        quota_data = {
            "enabled": True,
            "account_email": "test_user@gmail.com",
            "gemini_5h_pct": 90,
            "gemini_5h_reset": "~4h",
            "gemini_weekly_pct": 6,
            "gemini_weekly_reset": "~2d",
        }
        alert = evaluate_quota_alert(quota_data, threshold_pct=8.0)
        self.assertTrue(alert.is_critical)
        self.assertEqual(alert.alert_level, "CRITICAL")
        self.assertIn("Weekly Limit", alert.critical_buckets)
        self.assertTrue(alert.handover_recommended)

    def test_evaluate_quota_alert_disabled_or_none(self) -> None:
        alert_none = evaluate_quota_alert(None)
        self.assertFalse(alert_none.is_critical)
        self.assertEqual(alert_none.alert_level, "UNKNOWN")

        alert_disabled = evaluate_quota_alert({"enabled": False})
        self.assertFalse(alert_disabled.is_critical)
        self.assertEqual(alert_disabled.alert_level, "UNKNOWN")

    def test_format_iso_reset(self) -> None:
        now = datetime.datetime.now(datetime.timezone.utc)
        target = now + datetime.timedelta(hours=3, minutes=20)
        formatted = format_iso_reset(target.isoformat())
        self.assertTrue("3h" in formatted or "20m" in formatted)

        past = now - datetime.timedelta(minutes=10)
        self.assertEqual(format_iso_reset(past.isoformat()), "refreshing_soon")
        self.assertEqual(format_iso_reset(None), "")

    def test_format_quota_markdown(self) -> None:
        quota_data = {
            "enabled": True,
            "plan": "Google AI Pro",
            "account_email": "alice@gmail.com",
            "gemini_5h_pct": 95,
            "gemini_5h_reset": "~4h",
            "gemini_weekly_pct": 90,
            "gemini_weekly_reset": "~6d",
            "claude_gpt_5h_pct": 100,
        }
        md = format_quota_markdown(quota_data)
        self.assertIn("alice@gmail.com", md)
        self.assertIn("95%", md)
        self.assertIn("90%", md)

        crit_alert = evaluate_quota_alert({**quota_data, "gemini_5h_pct": 5}, threshold_pct=8.0)
        md_crit = format_quota_markdown({**quota_data, "gemini_5h_pct": 5}, alert=crit_alert)
        self.assertIn("[CRITICAL QUOTA ALERT]", md_crit)

    def test_token_estimation_heuristics(self) -> None:
        cjk_text = "这是一段中文测试"
        tok = est_tokens(cjk_text)
        self.assertGreaterEqual(tok, 4)

        ascii_text = "hello world this is a test"
        tok_ascii = est_tokens(ascii_text)
        self.assertGreaterEqual(tok_ascii, 5)

    def test_analyze_transcript_empty(self) -> None:
        res = analyze_transcript(None, "dummy_session")
        self.assertEqual(res["session_id"], "dummy_session")
        self.assertEqual(res["api_calls"], 0)

    def test_evaluate_api_balance_alert_healthy(self) -> None:
        from jhoc.quota.api_balance import APIKeyBalance, evaluate_api_balance_alert, format_api_balance_markdown
        balances = {
            "DeepSeek": APIKeyBalance("DeepSeek", "CNY", 30.0, is_available=True, status="healthy"),
            "OpenRouter": APIKeyBalance("OpenRouter", "USD", 10.0, is_available=True, status="healthy"),
        }
        alert = evaluate_api_balance_alert(balances)
        self.assertFalse(alert.is_critical)
        self.assertEqual(alert.alert_level, "OK")
        md = format_api_balance_markdown(balances, alert)
        self.assertIn("30.00 CNY", md)
        self.assertIn("10.00 USD", md)
        self.assertIn("(充足)", md)

    def test_evaluate_api_balance_alert_critical(self) -> None:
        from jhoc.quota.api_balance import APIKeyBalance, evaluate_api_balance_alert, format_api_balance_markdown
        balances = {
            "DeepSeek": APIKeyBalance("DeepSeek", "CNY", 0.5, is_available=True, status="critical"),
            "OpenRouter": APIKeyBalance("OpenRouter", "USD", 10.0, is_available=True, status="healthy"),
        }
        alert = evaluate_api_balance_alert(balances, threshold_cny=2.0)
        self.assertTrue(alert.is_critical)
        self.assertEqual(alert.alert_level, "CRITICAL")
        self.assertIn("DeepSeek", alert.critical_providers)
        self.assertIn("[CRITICAL API KEY BALANCE ALERT]", alert.warning_message)
        md = format_api_balance_markdown(balances, alert)
        self.assertIn("0.50 CNY (告急)", md)
        self.assertIn("[WARN: 需及时充值]", md)


if __name__ == "__main__":
    unittest.main()

