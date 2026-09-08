import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from jhoc.atlas import AtlasStore, KnowledgeRecord, KnowledgeStatus  # noqa: E402
from jhoc.contracts import ContractError, ErrorCode  # noqa: E402
from jhoc.graph import GraphNode, GraphRelation, GraphStore  # noqa: E402
from jhoc.memory_store import MemoryRecord, MemoryStore  # noqa: E402
from jhoc.proof import EvidencePackage, ProofStore  # noqa: E402


class KnowledgeMemoryProofTests(unittest.TestCase):
    def test_atlas_lifecycle_requires_order_and_version(self):
        atlas = AtlasStore()
        record = atlas.ingest(KnowledgeRecord({"fact": 1}, "FACT", "task:1", "public"))
        with self.assertRaises(ContractError):
            atlas.transition(record.record_id, KnowledgeStatus.PUBLISHED)
        current = atlas.transition(record.record_id, KnowledgeStatus.PARSED)
        with self.assertRaises(ContractError) as error:
            atlas.transition(record.record_id, KnowledgeStatus.NORMALIZED, expected_version=1)
        self.assertEqual(error.exception.code, ErrorCode.STALE_STATE)
        self.assertEqual(current.status, KnowledgeStatus.PARSED)

    def test_graph_is_projection_only_and_requires_nodes(self):
        graph = GraphStore()
        graph.add_node(GraphNode("a", "Task"))
        with self.assertRaises(ContractError):
            graph.add_relation(GraphRelation("r", "a", "missing", "supports", 1.0, "task:1", "VERIFIED"))
        graph.add_node(GraphNode("b", "Evidence"))
        graph.add_relation(GraphRelation("r", "a", "b", "supports", 1.0, "task:1", "VERIFIED"))
        self.assertEqual(len(graph.relations()), 1)

    def test_memory_write_gate_defaults_to_deny(self):
        store = MemoryStore()
        record = MemoryRecord({"note": "x"}, "TaskMemory", "task:1", "internal")
        with self.assertRaises(ContractError):
            store.write(record)
        store.write(record, approved=True)
        self.assertIsNotNone(store.get(record.record_id))

    def test_proof_requires_complete_references_and_is_deduplicated(self):
        proof = ProofStore()
        package = EvidencePackage("t1", "w1", "policy:v1", "cap:v1", {"ok": True}, {"out": 1}, {"checked": True}, "SUCCEEDED", ("artifact:1",))
        digest = proof.record_evidence(package)
        self.assertEqual(proof.record_evidence(package), digest)
        self.assertEqual(proof.evidence(digest), package)
        with self.assertRaises(ContractError):
            EvidencePackage("t1", "w1", "", "cap:v1", {}, {}, {}, "SUCCEEDED", ())

    def test_sensitivity_lifecycle_and_relation_quality_matrix(self):
        atlas = AtlasStore()
        record = atlas.ingest(KnowledgeRecord({"fact": 1}, "FACT", "task:matrix", "confidential"))
        self.assertEqual(record.sensitivity, "CONFIDENTIAL")
        for status in (
            KnowledgeStatus.PARSED, KnowledgeStatus.NORMALIZED, KnowledgeStatus.CANDIDATE,
            KnowledgeStatus.VERIFIED, KnowledgeStatus.PUBLISHED, KnowledgeStatus.EXPIRED,
            KnowledgeStatus.ARCHIVED,
        ):
            record = atlas.transition(record.record_id, status)
        self.assertEqual(len(atlas.history(record.record_id)), 8)
        with self.assertRaises(ContractError):
            KnowledgeRecord({}, "FACT", "task:bad", "secret-ish")

        graph = GraphStore()
        graph.add_node(GraphNode("source", "Task"))
        graph.add_node(GraphNode("evidence", "Evidence"))
        graph.add_relation(GraphRelation("verified", "source", "evidence", "supports", 0.95, "task:matrix", "VERIFIED", "VERIFIED"))
        self.assertEqual(len(graph.relations_by_quality("VERIFIED")), 1)
        with self.assertRaises(ContractError):
            graph.add_relation(GraphRelation("unknown", "source", "evidence", "invented", 1.0, "task:matrix", "VERIFIED"))


if __name__ == "__main__":
    unittest.main()
