"""JHOC Governance Round 5 Adversarial Blindspot Hardening Tests.

Verifies remediation of deep blindspots identified during Multi-Model Co-Review:
1. NTFS aliasing protection: trailing dots and trailing spaces on sensitive files.
2. NTFS Alternate Data Stream (ADS) evasion attempts.
3. Credential sprawl coverage (.git-credentials, .npmrc, .pypirc, token.json, etc.).
4. Subprocess environment secret scrubbing (JHOC_OPERATOR_TOKEN not leaked to children).
5. Keyed artifact SHA-256 physical recomputation and tamper rejection in post-verification.
6. Zero-width invisible Unicode character detection (\u200b, \ufeff, \u2060).
7. Whitelist channel secret laundering block during quota circuit breaker.

Conforms strictly to Rule 7 (Zero-Emoji Discipline) and Rule 1 (Physical Reality).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from jhoc.contracts.errors import ContractError
from jhoc.guard.path import PathGuard
from jhoc.hub.store import JHOCMultiModelHub
from jhoc.runner.encoding import get_subprocess_env
from scripts.jhoc_hook_gate import _EMOJI_RE, evaluate_payload


class TestGovernanceRound5AdversarialBlindspots(unittest.TestCase):
    """Adversarial negative test suite verifying immunity against red-team bypass vectors."""

    def test_ntfs_trailing_dot_and_space_aliasing(self) -> None:
        """Verifies that trailing dots and spaces cannot bypass PathGuard."""
        # Trailing dots
        self.assertTrue(PathGuard.is_sensitive(".operator_secret."))
        self.assertTrue(PathGuard.is_sensitive(".operator_stop_secret.."))
        self.assertTrue(PathGuard.is_sensitive("id_rsa."))
        self.assertTrue(PathGuard.is_sensitive(".env."))

        # Trailing spaces
        self.assertTrue(PathGuard.is_sensitive(".operator_secret   "))
        self.assertTrue(PathGuard.is_sensitive("credentials.json  "))

        # Governance asset trailing dot/space
        self.assertTrue(PathGuard.is_governance_asset("inbox.db."))
        self.assertTrue(PathGuard.is_governance_asset("hooks.json   "))
        self.assertTrue(PathGuard.is_governance_asset("jhoc_hook_gate.py."))

    def test_ntfs_alternate_data_streams(self) -> None:
        """Verifies that Alternate Data Streams (ADS) are detected and blocked."""
        self.assertTrue(PathGuard.is_sensitive(".operator_secret:stream"))
        self.assertTrue(PathGuard.is_sensitive("id_rsa:hidden_zone"))
        self.assertTrue(PathGuard.is_sensitive(".env:Zone.Identifier"))

    def test_credential_sprawl_coverage(self) -> None:
        """Verifies expanded coverage for developer credential files."""
        credentials = [
            ".git-credentials",
            ".npmrc",
            ".pypirc",
            "token.json",
            "oauth2_token.json",
            "id_ed25519_sk",
            "id_ecdsa_sk",
        ]
        for cred in credentials:
            self.assertTrue(PathGuard.is_sensitive(cred), f"Failed to detect sensitive credential: {cred}")

    def test_subprocess_env_secret_scrubbing(self) -> None:
        """Verifies that operator secrets are scrubbed from child process environments."""
        orig_token = os.environ.get("JHOC_OPERATOR_TOKEN")
        orig_secret = os.environ.get("JHOC_OPERATOR_SECRET")
        try:
            os.environ["JHOC_OPERATOR_TOKEN"] = "super_secret_operator_token_xyz"
            os.environ["JHOC_OPERATOR_SECRET"] = "super_secret_file_value_123"

            clean_env = get_subprocess_env()
            self.assertNotIn("JHOC_OPERATOR_TOKEN", clean_env)
            self.assertNotIn("JHOC_OPERATOR_SECRET", clean_env)
            self.assertNotIn("OPERATOR_TOKEN", clean_env)
            self.assertNotIn("OPERATOR_SECRET", clean_env)
        finally:
            if orig_token is not None:
                os.environ["JHOC_OPERATOR_TOKEN"] = orig_token
            else:
                os.environ.pop("JHOC_OPERATOR_TOKEN", None)
            if orig_secret is not None:
                os.environ["JHOC_OPERATOR_SECRET"] = orig_secret
            else:
                os.environ.pop("JHOC_OPERATOR_SECRET", None)

    def test_keyed_evidence_tamper_rejection(self) -> None:
        """Verifies that has_valid_recent_evidence physically checks capture file on disk."""
        with tempfile.TemporaryDirectory() as td:
            db_p = Path(td) / "test_hub.sqlite"
            cap_p = Path(td) / "capture_stdout.txt"
            content = "VALID_CO_REVIEW_CONTENT_12345"
            cap_p.write_text(content, encoding="utf-8")
            valid_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()

            hub = JHOCMultiModelHub(db_p)
            try:
                # 1. Insert authentic row
                from jhoc.hub import CoReviewEvidence
                ev = CoReviewEvidence(
                    run_id="run-test-01",
                    provider_bin="claude",
                    provider_bin_sha256="0" * 64,
                    argv=("claude", "-p"),
                    raw_stdin_sha256="0" * 64,
                    raw_stdout_sha256=valid_sha,
                    exit_code=0,
                    duration_ms=500,
                    engine_label_observed="claude",
                    created_at="2099-01-01T00:00:00+00:00",
                    metadata={"capture_file": str(cap_p)},
                )
                hub.record_co_review_evidence(ev)

                # Must pass when physical capture matches
                self.assertTrue(hub.has_valid_recent_evidence(max_age_seconds=999999999))

                # 2. Tamper physical capture file -> must fail!
                cap_p.write_text("TAMPERED_OUTPUT_BYTES", encoding="utf-8")
                self.assertFalse(hub.has_valid_recent_evidence(max_age_seconds=999999999))

                # 3. Delete physical capture file -> must fail!
                cap_p.unlink()
                self.assertFalse(hub.has_valid_recent_evidence(max_age_seconds=999999999))
            finally:
                hub.close()

    def test_empty_sha256_evidence_rejected(self) -> None:
        """Verifies that empty SHA-256 e3b0c442... is rejected as valid evidence."""
        with tempfile.TemporaryDirectory() as td:
            db_p = Path(td) / "test_hub.sqlite"
            hub = JHOCMultiModelHub(db_p)
            try:
                from jhoc.hub import CoReviewEvidence
                empty_sha = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
                ev = CoReviewEvidence(
                    run_id="run-test-empty",
                    provider_bin="claude",
                    provider_bin_sha256="0" * 64,
                    argv=("claude", "-p"),
                    raw_stdin_sha256="0" * 64,
                    raw_stdout_sha256=empty_sha,
                    exit_code=0,
                    duration_ms=100,
                    engine_label_observed="claude",
                    created_at="2099-01-01T00:00:00+00:00",
                    metadata={},
                )
                hub.record_co_review_evidence(ev)
                self.assertFalse(hub.has_valid_recent_evidence(max_age_seconds=999999999))
            finally:
                hub.close()

    def test_zero_width_unicode_discipline(self) -> None:
        """Verifies that invisible Unicode characters (zero-width spaces, BOM, joiners) are rejected."""
        self.assertIsNotNone(_EMOJI_RE.search("clean text with \u200b zero width space"))
        self.assertIsNotNone(_EMOJI_RE.search("\ufeffBOM at start"))
        self.assertIsNotNone(_EMOJI_RE.search("word\u2060joiner"))
        self.assertIsNotNone(_EMOJI_RE.search("zero\u200cwidth non joiner"))

    def test_secret_laundering_block_on_whitelist(self) -> None:
        """Verifies that attempting to exfiltrate operator secret into whitelisted files is blocked."""
        with tempfile.TemporaryDirectory() as td:
            sec_file = Path(td) / "runtime" / ".operator_secret"
            sec_file.parent.mkdir(parents=True, exist_ok=True)
            sec_token = "SEC_TOKEN_ABC123_XYZ"
            sec_file.write_text(sec_token, encoding="utf-8")

            # Write critical quota cache into runtime
            quota_cache_file = Path(td) / "runtime" / ".quota_cache.json"
            import time
            quota_cache_file.write_text(
                json.dumps({
                    "enabled": True,
                    "account_email": "test@gmail.com",
                    "gemini_5h_pct": 2.0,  # Critical <= 8%
                    "gemini_weekly_pct": 2.0,
                    "cached_at": time.time(),
                }),
                encoding="utf-8",
            )

            target_file_path = str(Path(td) / "memory" / "leaked_notes.md")
            payload = {
                "toolCall": {
                    "name": "write_to_file",
                    "args": {
                        "TargetFile": target_file_path,
                        "CodeContent": f"Here is the leaked token: {sec_token}",
                    },
                },
                "quota_data": {
                    "enabled": True,
                    "account_email": "test@gmail.com",
                    "gemini_5h_pct": 2.0,
                    "gemini_weekly_pct": 2.0,
                },
            }
            # Temporarily point WORKSPACE_ROOT
            import scripts.jhoc_hook_gate as hg
            old_root = hg.WORKSPACE_ROOT
            try:
                hg.WORKSPACE_ROOT = Path(td)
                res = evaluate_payload(payload)
                self.assertEqual(res.get("decision"), "deny")
                self.assertIn("Security Laundering Block", res.get("reason", ""))
            finally:
                hg.WORKSPACE_ROOT = old_root


if __name__ == "__main__":
    unittest.main()
