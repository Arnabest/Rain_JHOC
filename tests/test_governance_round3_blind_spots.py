from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from jhoc.contracts.errors import ContractError
from jhoc.guard.path import PathAccessMode, PathGuard
from jhoc.hub import JHOCMultiModelHub
from jhoc.proof.blackbox import BlackBoxEntry, BlackBoxStepType
from jhoc_hook_gate import _record_blackbox_trace, evaluate_payload


class TestGovernanceRound3BlindSpots(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_hub.sqlite"
        self.hub = JHOCMultiModelHub(self.db_path)

    def tearDown(self) -> None:
        self.hub.close()
        self.temp_dir.cleanup()

    def test_round3_01_reverse_isolation_blocks_external_write_to_mother_core(self) -> None:
        # 1. External workspace trying to modify mother core proof module
        external_proj = Path(self.temp_dir.name) / "external_project"
        external_proj.mkdir(parents=True, exist_ok=True)

        payload1 = {
            "caller": "claude-code",
            "workspacePaths": [str(external_proj)],
            "toolCall": {
                "name": "write_to_file",
                "args": {
                    "TargetFile": str(ROOT / "src" / "jhoc" / "proof" / "trojan.py"),
                    "CodeContent": "# backdoor",
                },
            },
        }
        res1 = evaluate_payload(payload1)
        self.assertEqual(res1["decision"], "deny")
        self.assertTrue(
            "Reverse Isolation Violation" in res1["reason"] or "Governance Root Violation" in res1["reason"]
        )

        # 2. PathGuard.evaluate on any src/jhoc module raises ContractError for WRITE mode
        with self.assertRaises(ContractError):
            PathGuard.evaluate(ROOT / "src" / "jhoc" / "runner" / "runtime.py", ROOT, mode=PathAccessMode.WRITE)

        with self.assertRaises(ContractError):
            PathGuard.evaluate(ROOT / "src" / "jhoc" / "graph" / "store.py", ROOT, mode=PathAccessMode.WRITE)

        # 3. But READ mode remains permitted for pair-programming inspection
        read_path = PathGuard.evaluate(ROOT / "src" / "jhoc" / "runner" / "runtime.py", ROOT, mode=PathAccessMode.READ)
        self.assertEqual(read_path, (ROOT / "src" / "jhoc" / "runner" / "runtime.py").resolve())

    def test_round3_02_blackbox_hash_conformance_and_lock_retries(self) -> None:
        # 1. Verify schema and hash conformance between gate and BlackBoxEntry
        content = {
            "tool": "run_command",
            "args_keys": ["CommandLine"],
            "decision": "allow",
            "reason": "Safe command",
            "actor": "antigravity-ide",
            "task_id": "task-xyz",
        }
        seq = 10
        now_iso = "2026-09-04T00:00:00+00:00"
        actor = "antigravity-ide"
        prev_hash = "0" * 64

        canonical_hash = BlackBoxEntry.compute_hash(
            sequence=seq,
            timestamp=now_iso,
            step_type=BlackBoxStepType.TOOL,
            actor=actor,
            content=content,
            previous_hash=prev_hash,
        )

        gate_payload = {
            "sequence": seq,
            "timestamp": now_iso,
            "step_type": "TOOL",
            "actor": actor,
            "content": content,
            "previous_hash": prev_hash,
        }
        gate_hash = hashlib.sha256(
            json.dumps(gate_payload, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()

        self.assertEqual(gate_hash, canonical_hash)

        # 2. Verify lock contention fail-closed
        lock_path = ROOT / "runtime" / "blackbox_write.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text("pre-held lock", encoding="utf-8")
        try:
            # When lock is held, _record_blackbox_trace returns cleanly without raising or corrupting file
            _record_blackbox_trace(
                tool_name="test_tool",
                args={},
                decision="deny",
                reason="testing",
                actor="test_actor",
            )
        finally:
            if lock_path.exists():
                lock_path.unlink()

    def test_round3_03_hub_lease_token_enforcement(self) -> None:
        target_file = ROOT / "src" / "jhoc" / "supervisor.py"

        # 1. Model A acquires lease
        ok1, msg1, lease1 = self.hub.acquire_file_lease("claude-code", target_file, ttl_seconds=60)
        self.assertTrue(ok1)
        self.assertIsNotNone(lease1)
        lid = lease1.lease_id

        # 2. Model A attempts to renew with WRONG lease_id -> MUST FAIL
        ok2, msg2, _ = self.hub.acquire_file_lease("claude-code", target_file, ttl_seconds=60, lease_id="fake-lease-id")
        self.assertFalse(ok2)
        self.assertIn("Lease token mismatch", msg2)

        # 3. Model A renews with CORRECT lease_id -> SUCCESS
        ok3, msg3, lease3 = self.hub.acquire_file_lease("claude-code", target_file, ttl_seconds=60, lease_id=lid)
        self.assertTrue(ok3)
        self.assertEqual(lease3.lease_id, lid)

        # 4. Model B tries to release Model A's lease -> MUST FAIL
        released_b = self.hub.release_file_lease("codex-cli", target_file)
        self.assertFalse(released_b)

        # 5. Model A tries to release with WRONG lease_id -> MUST FAIL
        released_wrong = self.hub.release_file_lease("claude-code", target_file, lease_id="fake-id")
        self.assertFalse(released_wrong)

        # 6. Model A releases with CORRECT lease_id -> SUCCESS
        released_ok = self.hub.release_file_lease("claude-code", target_file, lease_id=lid)
        self.assertTrue(released_ok)


if __name__ == "__main__":
    unittest.main()
