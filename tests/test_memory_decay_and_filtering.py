from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jhoc.memory_store.retriever import MemoryRetriever


class TestMemoryDecayAndFiltering(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="jhoc_decay_test_"))
        self.catalog_path = self.temp_dir / "catalog.json"
        self.db_path = self.temp_dir / "mock_mem.sqlite"

        # Mock catalog with 3 records:
        # 1. Fresh active record
        # 2. Stale / Superseded record
        # 3. Other-tenant project record
        catalog_data = {
            "records": [
                {
                    "record_id": "rec:fresh:20260902",
                    "tier": "L2",
                    "domain": "Architecture & Infrastructure",
                    "title": "Fresh microkernel architecture guidelines",
                    "relative_path": "memory/session-20260902-architecture.md",
                    "project_id": "jhoc",
                    "status": "ACTIVE",
                },
                {
                    "record_id": "rec:stale:20240101",
                    "tier": "L2",
                    "domain": "Architecture & Infrastructure",
                    "title": "Old superseded microkernel guidelines",
                    "relative_path": "memory/session-20240101-legacy.md",
                    "project_id": "jhoc",
                    "status": "SUPERSEDED",
                    "superseded_by": "rec:fresh:20260902",
                },
                {
                    "record_id": "rec:other:20260902",
                    "tier": "L2",
                    "domain": "Architecture & Infrastructure",
                    "title": "Special tenant architecture guidelines",
                    "relative_path": "memory/session-20260902-tenant.md",
                    "project_id": "project_external_x",
                    "status": "ACTIVE",
                },
            ]
        }
        self.catalog_path.write_text(json.dumps(catalog_data), encoding="utf-8")

    def tearDown(self) -> None:
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_superseded_memory_eliminated_from_recall(self) -> None:
        retriever = MemoryRetriever(db_path=self.db_path, catalog_path=self.catalog_path)
        items = retriever.retrieve_l2_distilled_memory("microkernel architecture", limit=5)

        recalled_ids = [item.record_id for item in items]
        self.assertIn("rec:fresh:20260902", recalled_ids)
        self.assertNotIn("rec:stale:20240101", recalled_ids, "Superseded memory must be strictly eliminated")

    def test_tenant_partition_filtering_in_retriever(self) -> None:
        retriever = MemoryRetriever(db_path=self.db_path, catalog_path=self.catalog_path)

        # 1. Query as default jhoc tenant -> external_x must not leak
        jhoc_items = retriever.retrieve_l2_distilled_memory("architecture guidelines", project_id="jhoc", limit=5)
        jhoc_ids = [item.record_id for item in jhoc_items]
        self.assertIn("rec:fresh:20260902", jhoc_ids)
        self.assertNotIn("rec:other:20260902", jhoc_ids, "Other project memory must not leak into jhoc tenant")

        # 2. Query as project_external_x tenant -> external_x and jhoc common are both accessible
        tenant_items = retriever.retrieve_l2_distilled_memory("architecture guidelines", project_id="project_external_x", limit=5)
        tenant_ids = [item.record_id for item in tenant_items]
        self.assertIn("rec:other:20260902", tenant_ids)


if __name__ == "__main__":
    unittest.main()
