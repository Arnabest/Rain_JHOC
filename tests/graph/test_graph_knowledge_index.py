from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from jhoc.graph import (
    GraphKnowledgeIndex,
    GraphNode,
    GraphRelation,
    GraphSearchResult,
    GraphStore,
    SQLiteGraphStore,
)

GRAPH_DB = ROOT / "logs" / "p19-graph.sqlite"


class TestGraphKnowledgeIndex(unittest.TestCase):
    _temp_dir = None

    @classmethod
    def setUpClass(cls) -> None:
        if not GRAPH_DB.exists():
            import tempfile
            cls._temp_dir = tempfile.TemporaryDirectory()
            db_path = Path(cls._temp_dir.name) / "test_graph.sqlite"
            store = SQLiteGraphStore(str(db_path))
            store.add_node(GraphNode("err:lesson-90", "ErrorRecord"))
            store.add_node(GraphNode("subsystem:relay", "Subsystem"))
            store.add_node(GraphNode("project:jhoc", "Project"))
            store.add_relation(GraphRelation("r1", "err:lesson-90", "subsystem:relay", "applies_to", 1.0, "ref", "VERIFIED", "VERIFIED"))
            store.add_node(GraphNode("subsystem:conductor", "Subsystem"))
            store.add_node(GraphNode("subsystem:guard", "Subsystem"))
            store.add_relation(GraphRelation("r2", "subsystem:conductor", "subsystem:guard", "depends_on", 1.0, "ref", "VERIFIED", "VERIFIED"))
            store.close()
            cls.index = GraphKnowledgeIndex(db_path=db_path)
        else:
            cls.index = GraphKnowledgeIndex(db_path=GRAPH_DB)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.index.close()
        if cls._temp_dir is not None:
            cls._temp_dir.cleanup()

    def test_seed_node_resolution(self) -> None:
        # 1. Socket timeout -> lesson-90
        s1 = self.index.resolve_seed_nodes("排查系统 Socket 轮询超时故障")
        self.assertIn("err:lesson-90", s1)

        # 2. Security guard -> subsystem:guard
        s2 = self.index.resolve_seed_nodes("执行安全策略与越权拦截")
        self.assertIn("subsystem:guard", s2)

        # 3. Paper architecture -> lesson-402
        s3 = self.index.resolve_seed_nodes("解决纸面架构与入库不召回问题")
        self.assertIn("err:lesson-402", s3)

    def test_decoupled_search_returns_valid_search_result(self) -> None:
        result = self.index.search("排查 Socket 轮询超时", max_hops=1)
        self.assertIsInstance(result, GraphSearchResult)
        self.assertIn("err:lesson-90", result.seed_nodes)
        self.assertGreater(len(result.expanded_nodes), 1)

        # Must find connected subsystem:relay or project:jhoc
        self.assertTrue(
            "subsystem:relay" in result.expanded_nodes or "project:jhoc" in result.expanded_nodes
        )

        # Must include verified relations
        rel_types = {r["type"] for r in result.relations}
        self.assertTrue("applies_to" in rel_types or "solves" in rel_types or "belongs_to" in rel_types)
        self.assertTrue(result.summary_text.startswith("[GraphIndex]"))

    def test_subsystem_dependency_traversal(self) -> None:
        result = self.index.search("conductor 编排与规划", max_hops=1)
        self.assertIn("subsystem:conductor", result.seed_nodes)

        # Conductor depends on guard, shelf, memory_store
        found_deps = [r for r in result.relations if r["type"] == "depends_on"]
        self.assertGreaterEqual(len(found_deps), 1)
        targets = {r["target"] for r in found_deps}
        self.assertTrue(
            "subsystem:guard" in targets or "subsystem:shelf" in targets or "subsystem:memory_store" in targets
        )

    # =========================================================================
    # 可证伪反例与边界防御测试 (Falsifiable Negative & Cycle Tests)
    # =========================================================================

    def test_falsifiable_negative_irrelevant_query_zero_hallucination(self) -> None:
        """反例 1: 无关查询绝不误识别种子节点，不凭空捏造拓扑关系。"""
        negative_queries = [
            "今天晚饭吃什么好呢？",
            "帮我把这个英文字符串大写",
            "12345 + 67890 等于几",
            "随机乱码 abcxyz123",
        ]
        for q in negative_queries:
            res = self.index.search(q, max_hops=1)
            self.assertEqual(res.seed_nodes, (), f"False positive seed for query: {q}")
            self.assertEqual(res.expanded_nodes, (), f"False positive expansion for query: {q}")
            self.assertEqual(res.relations, (), f"False positive relations for query: {q}")
            self.assertEqual(res.entities, (), f"False positive entities for query: {q}")
            self.assertIn("无匹配的图谱实体种子", res.summary_text)

    def test_falsifiable_circular_graph_bounded_expansion(self) -> None:
        """反例 2: 遇到循环边 (A -> B -> C -> A) 时，拓扑扩散算法必须严格有界，绝不陷入死循环。"""
        store = GraphStore()
        # Create circular topology: N1 -> N2 -> N3 -> N1
        store.add_node(GraphNode("node:1", "TestNode"))
        store.add_node(GraphNode("node:2", "TestNode"))
        store.add_node(GraphNode("node:3", "TestNode"))

        store.add_relation(GraphRelation("r1", "node:1", "node:2", "depends_on", 1.0, "ref", "VERIFIED", "VERIFIED"))
        store.add_relation(GraphRelation("r2", "node:2", "node:3", "depends_on", 1.0, "ref", "VERIFIED", "VERIFIED"))
        store.add_relation(GraphRelation("r3", "node:3", "node:1", "depends_on", 1.0, "ref", "VERIFIED", "VERIFIED"))

        index = GraphKnowledgeIndex(graph_store=store)
        try:
            # Expand with max_hops=10 (much greater than cycle length)
            expanded = index._retriever.expand_subgraph(("node:1",), max_hops=10, min_quality="VERIFIED")
            # Must terminate cleanly and only contain the 3 unique nodes
            self.assertEqual(set(expanded), {"node:1", "node:2", "node:3"})
        finally:
            index.close()


if __name__ == "__main__":
    unittest.main()
