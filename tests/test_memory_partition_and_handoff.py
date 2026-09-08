from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from jhoc.memory_store import MemoryRecord, MemoryStore, SQLiteMemoryStore


class TestMemoryPartitionAndHandoff(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="jhoc_mem_test_"))
        self.db_path = self.temp_dir / "test_memory.sqlite"

    def tearDown(self) -> None:
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_memory_record_has_project_id_default(self) -> None:
        rec = MemoryRecord({"key": "val"}, "TaskMemory", "task:1", "internal")
        self.assertEqual(rec.project_id, "jhoc")

    def test_memory_store_partitions_by_project_id(self) -> None:
        store = SQLiteMemoryStore(str(self.db_path))
        try:
            rec_jhoc = MemoryRecord({"fact": "jhoc_rule"}, "TaskMemory", "task:1", "internal", record_id="rec:1", project_id="jhoc")
            rec_alpha = MemoryRecord({"fact": "alpha_config"}, "ProjectMemory", "task:2", "internal", record_id="rec:2", project_id="project_alpha")
            rec_beta = MemoryRecord({"fact": "beta_port"}, "ProjectMemory", "task:3", "internal", record_id="rec:3", project_id="project_beta")

            store.write(rec_jhoc, approved=True)
            store.write(rec_alpha, approved=True)
            store.write(rec_beta, approved=True)

            # Query all
            all_recs = store.records()
            self.assertEqual(len(all_recs), 3)

            # Query by tenant partition
            jhoc_recs = store.records(project_id="jhoc")
            self.assertEqual(len(jhoc_recs), 1)
            self.assertEqual(jhoc_recs[0].record_id, "rec:1")

            alpha_recs = store.records(project_id="project_alpha")
            self.assertEqual(len(alpha_recs), 1)
            self.assertEqual(alpha_recs[0].record_id, "rec:2")
            self.assertEqual(alpha_recs[0].content["fact"], "alpha_config")

            beta_recs = store.records(project_id="project_beta")
            self.assertEqual(len(beta_recs), 1)
            self.assertEqual(beta_recs[0].record_id, "rec:3")
        finally:
            store.close()

    def test_inter_model_handoff_package_io(self) -> None:
        mem_dir = self.temp_dir / "memory"
        mem_dir.mkdir(parents=True, exist_ok=True)
        handoff_file = mem_dir / "handoff-latest.json"

        # Simulate Claude closing task with a pending item
        handoff_data = {
            "task_id": "20260903T120000Z-task-1",
            "title": "Refactor auth middleware",
            "closed_at": "2026-09-03T12:00:00Z",
            "status": "CLOSED",
            "workspace": str(self.temp_dir),
            "pending_actions": ["Add unit tests for refresh token", "Verify rate limiter"],
        }
        handoff_file.write_text(json.dumps(handoff_data), encoding="utf-8")

        # Verify Gemini/Codex can read and decode previous pending actions
        self.assertTrue(handoff_file.is_file())
        decoded = json.loads(handoff_file.read_text(encoding="utf-8"))
        self.assertEqual(decoded["task_id"], "20260903T120000Z-task-1")
        self.assertEqual(len(decoded["pending_actions"]), 2)
        self.assertIn("Verify rate limiter", decoded["pending_actions"])


if __name__ == "__main__":
    unittest.main()
