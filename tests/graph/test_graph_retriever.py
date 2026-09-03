from __future__ import annotations

import unittest

from jhoc.graph.retriever import GraphRAGRetriever
from jhoc.graph.store import GraphNode, GraphRelation, GraphStore


class TestGraphRAGRetriever(unittest.TestCase):
    def setUp(self) -> None:
        self.store = GraphStore()
        # Create a small sub-graph:
        # ErrorPattern -(solves)-> TaskExperience -(depends_on)-> CodeModule
        n1 = GraphNode("error:pattern:DB_DEADLOCK", "ErrorPattern")
        n2 = GraphNode("experience:SOLVE_DEADLOCK", "TaskExperience")
        n3 = GraphNode("code:module:jhoc.storage.sqlite", "CodeEntity")

        self.store.add_node(n1)
        self.store.add_node(n2)
        self.store.add_node(n3)

        r1 = GraphRelation(
            relation_id="rel:1",
            source_node=n2.node_id,
            target_node=n1.node_id,
            relation_type="solves",
            confidence=1.0,
            source_ref="audit:1",
            verification_status="VERIFIED",
            quality="VERIFIED",
        )
        r2 = GraphRelation(
            relation_id="rel:2",
            source_node=n2.node_id,
            target_node=n3.node_id,
            relation_type="depends_on",
            confidence=1.0,
            source_ref="audit:2",
            verification_status="VERIFIED",
            quality="VERIFIED",
        )
        self.store.add_relation(r1)
        self.store.add_relation(r2)

        self.retriever = GraphRAGRetriever(self.store)

    def test_subgraph_expansion_1_hop(self) -> None:
        expanded = self.retriever.expand_subgraph(["error:pattern:DB_DEADLOCK"], max_hops=1)
        self.assertIn("error:pattern:DB_DEADLOCK", expanded)
        self.assertIn("experience:SOLVE_DEADLOCK", expanded)
        self.assertNotIn("code:module:jhoc.storage.sqlite", expanded)

    def test_subgraph_expansion_2_hop(self) -> None:
        expanded = self.retriever.expand_subgraph(["error:pattern:DB_DEADLOCK"], max_hops=2)
        self.assertIn("error:pattern:DB_DEADLOCK", expanded)
        self.assertIn("experience:SOLVE_DEADLOCK", expanded)
        self.assertIn("code:module:jhoc.storage.sqlite", expanded)

    def test_retrieve_context_sources_output(self) -> None:
        sources = self.retriever.retrieve_context_sources(["error:pattern:DB_DEADLOCK"], max_hops=2)
        self.assertEqual(len(sources), 3)

        source_ids = {s.source_id for s in sources}
        self.assertIn("graph:error:pattern:DB_DEADLOCK", source_ids)
        self.assertIn("graph:experience:SOLVE_DEADLOCK", source_ids)
        self.assertIn("graph:code:module:jhoc.storage.sqlite", source_ids)

        for s in sources:
            self.assertTrue(s.provenance[0].startswith("graph_traversal:"))
            self.assertEqual(s.sensitivity, "INTERNAL")
            self.assertGreater(s.confidence, 0.0)


if __name__ == "__main__":
    unittest.main()
