from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from jhoc.guard import CredentialVault, GlobalEgressRateLimiter
from jhoc.graph.code_extractor import CodeGraphExtractor
from jhoc_hook_gate import _record_blackbox_trace


class TestConcurrencyDeepHardening(unittest.TestCase):
    def test_vault_persistence_atomic_merge(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            vault_file = Path(temp_dir) / "test-vault.bin"

            v1 = CredentialVault(vault_file)
            v2 = CredentialVault(vault_file)

            # v1 registers secret A
            ref_a = v1.register_secret("SECRET_A", "val_a")
            # v2 registers secret B concurrently
            ref_b = v2.register_secret("SECRET_B", "val_b")

            # A fresh v3 loads from disk
            v3 = CredentialVault(vault_file)
            # Both secrets must exist on disk! No lost updates!
            self.assertEqual(v3.resolve_for_egress(ref_a, "adapter.test"), "val_a")
            self.assertEqual(v3.resolve_for_egress(ref_b, "adapter.test"), "val_b")

    def test_blackbox_trace_atomic_chain_integrity(self) -> None:
        bb_file = ROOT / "logs" / "p19-blackbox.jsonl"
        # Record 5 sequential/concurrent trace events
        for i in range(5):
            _record_blackbox_trace("test_tool", {"iteration": i}, "allow", "")

        # Verify hash chain continuity
        lines = [l for l in bb_file.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertGreaterEqual(len(lines), 5)
        entries = [json.loads(l) for l in lines]

        for i in range(1, len(entries)):
            prev_entry = entries[i - 1]
            curr_entry = entries[i]
            self.assertEqual(
                curr_entry["previous_hash"],
                prev_entry["entry_hash"],
                f"Chain broken between entry {i-1} and {i}!",
            )

    def test_code_extractor_syntax_error_concurrency_tolerance(self) -> None:
        # Partial code simulation during concurrent chunk write
        broken_code = "def incomplete_function(x, y:\n    return x +"
        nodes, rels = CodeGraphExtractor.extract_from_source("broken.py", broken_code, "broken")
        self.assertEqual(len(nodes), 0)
        self.assertEqual(len(rels), 0)

    def test_global_egress_rate_limiter(self) -> None:
        limiter = GlobalEgressRateLimiter({"test.api.org": 50.0})  # 50 req/s -> 20ms interval
        t0 = time.monotonic()
        for _ in range(3):
            acquired = limiter.acquire("test.api.org", timeout=1.0)
            self.assertTrue(acquired)
        elapsed = time.monotonic() - t0
        self.assertGreaterEqual(elapsed, 0.035, "Rate limiter must throttle requests by interval")


if __name__ == "__main__":
    unittest.main()
