"""Unit tests for JHOC Full-Mesh Lineage Graph and Graph-RAG Recall."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from jhoc.graph.sqlite import SQLiteGraphStore
from jhoc.graph.store import GraphNode, GraphRelation
from jhoc.graph.retriever import GraphRAGRetriever


class TestLineageGraphStoreAndRetriever(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_lineage.sqlite"
        self.store = SQLiteGraphStore(str(self.db_path))
        self.retriever = GraphRAGRetriever(self.store)

    def tearDown(self) -> None:
        self.store.close()
        self.temp_dir.cleanup()

    def test_lineage_graph_nodes_and_relations(self) -> None:
        # Register nodes: Project, Task, WorkArtifact, RawTranscript, Error
        p_node = GraphNode("project:qqmusicoverlay", "Project")
        s_node = GraphNode("session:vsc:1022beae", "RawTranscript")
        t_node = GraphNode("task:20260624T000000Z-smtc-fix", "Task")
        f_node = GraphNode("file:render/gl_engine.py", "WorkArtifact")
        e_node = GraphNode("error:2026-06-24:SMTC_CRASH", "Error")

        for n in [p_node, s_node, t_node, f_node, e_node]:
            self.store.add_node(n)

        # Register relations
        r1 = GraphRelation("rel:1", t_node.node_id, s_node.node_id, "triggered_by", 1.0, "test", "VERIFIED", "VERIFIED")
        r2 = GraphRelation("rel:2", t_node.node_id, f_node.node_id, "touches_file", 1.0, "test", "VERIFIED", "VERIFIED")
        r3 = GraphRelation("rel:3", f_node.node_id, p_node.node_id, "belongs_to", 1.0, "test", "VERIFIED", "VERIFIED")
        r4 = GraphRelation("rel:4", e_node.node_id, f_node.node_id, "observed_in", 1.0, "test", "VERIFIED", "VERIFIED")

        for r in [r1, r2, r3, r4]:
            self.store.add_relation(r)

        self.assertEqual(len(self.store.relations()), 4)

        # Query lineage
        lineage = self.retriever.find_file_lineage("render/gl_engine.py")
        self.assertEqual(lineage["file_node"], "file:render/gl_engine.py")
        self.assertIn("task:20260624T000000Z-smtc-fix", lineage["upstream_tasks"])
        self.assertIn("session:vsc:1022beae", lineage["upstream_sessions"])
        self.assertIn("project:qqmusicoverlay", lineage["related_projects"])
        self.assertIn("error:2026-06-24:SMTC_CRASH", lineage["related_errors"])

    def test_expand_subgraph_2_hops(self) -> None:
        p_node = GraphNode("project:jhoc", "Project")
        t_node = GraphNode("task:bootstrap", "Task")
        f_node = GraphNode("file:ARCHITECTURE.md", "WorkArtifact")

        self.store.add_node(p_node)
        self.store.add_node(t_node)
        self.store.add_node(f_node)

        self.store.add_relation(GraphRelation("r:t->f", t_node.node_id, f_node.node_id, "touches_file", 1.0, "ref", "VERIFIED", "VERIFIED"))
        self.store.add_relation(GraphRelation("r:f->p", f_node.node_id, p_node.node_id, "belongs_to", 1.0, "ref", "VERIFIED", "VERIFIED"))

        expanded = self.retriever.expand_subgraph([t_node.node_id], max_hops=2)
        self.assertIn(t_node.node_id, expanded)
        self.assertIn(f_node.node_id, expanded)
        self.assertIn(p_node.node_id, expanded)


if __name__ == "__main__":
    unittest.main()
