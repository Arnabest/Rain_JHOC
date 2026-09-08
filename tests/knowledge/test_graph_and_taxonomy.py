import json
import unittest
from pathlib import Path

from jhoc.graph.sqlite import SQLiteGraphStore
from jhoc.guard.policy import Decision, PolicyRequest
from jhoc.guard.sqlite import SQLiteGuardRuntime

ROOT = Path(__file__).resolve().parents[2]
GRAPH_DB = ROOT / "logs" / "p19-graph.sqlite"
GUARD_DB = ROOT / "logs" / "p19-guard.sqlite"
CATALOG_JSON = ROOT / "docs" / "taxonomy" / "jhoc-memory-taxonomy-catalog.json"


class GraphAndTaxonomyTests(unittest.TestCase):
    def test_graph_projection_populated(self):
        if not GRAPH_DB.is_file():
            self.skipTest("Graph database not present in zero-data release")
        store = SQLiteGraphStore(str(GRAPH_DB))
        try:
            relations = store.relations()
            self.assertGreater(len(relations), 3000, "Should have more than 3000 relations")
            verified_rels = store.relations_by_quality("VERIFIED")
            self.assertGreater(len(verified_rels), 500, "Should have verified relations")
        finally:
            store.close()

    def test_memory_taxonomy_catalog_complete(self):
        if not CATALOG_JSON.is_file():
            self.skipTest("Taxonomy catalog not present in zero-data release")
        catalog = json.loads(CATALOG_JSON.read_text(encoding="utf-8"))
        self.assertGreaterEqual(catalog["total_records"], 1)
        self.assertIn("L1", catalog["tier_summary"])
        self.assertIn("L2", catalog["tier_summary"])
        self.assertGreater(catalog["tier_summary"]["L1"], 0)

    def test_guard_policy_runtime_decisions(self):
        if not GUARD_DB.is_file():
            self.skipTest("Guard database not present in zero-data release")
        guard = SQLiteGuardRuntime(str(GUARD_DB))
        try:
            # Safe read should be ALLOW
            d1 = guard.evaluate(None, PolicyRequest(operation="read_knowledge", risk_level=0))
            self.assertEqual(d1.decision, Decision.ALLOW)

            # Code mutation should be REQUIRE_APPROVAL
            d2 = guard.evaluate(None, PolicyRequest(operation="mutate_code", risk_level=3, external_side_effect=True))
            self.assertEqual(d2.decision, Decision.REQUIRE_APPROVAL)

            # Legacy bus connect should be DENY
            d3 = guard.evaluate(None, PolicyRequest(operation="legacy_bus_connect", risk_level=2))
            self.assertEqual(d3.decision, Decision.DENY)

            # Dumping credentials should be DENY
            d4 = guard.evaluate(None, PolicyRequest(operation="dump_credentials", risk_level=4, sensitive=True))
            self.assertEqual(d4.decision, Decision.DENY)
        finally:
            guard.close()


if __name__ == "__main__":
    unittest.main()
