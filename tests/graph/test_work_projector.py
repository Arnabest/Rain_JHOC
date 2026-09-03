from __future__ import annotations

import unittest

from jhoc.graph.store import GraphStore
from jhoc.graph.work_projector import WorkGraphProjector


class TestWorkGraphProjector(unittest.TestCase):
    def test_project_task_execution_with_evidence(self) -> None:
        store = GraphStore()
        added_ids = WorkGraphProjector.project_task_execution(
            store,
            task_id="task-888",
            work_id="work-999",
            policy_ref="policy-v1",
            evidence_digest="sha256:abcd1234ef",
            target_code_entity="module:jhoc.guard.path",
        )
        self.assertGreater(len(added_ids), 3)

        relations = store.relations()
        rel_map = {(r.source_node, r.relation_type, r.target_node) for r in relations}

        self.assertIn(("task:task-888", "requires", "work:work-999"), rel_map)
        self.assertIn(("decision:policy-v1", "applies_to", "task:task-888"), rel_map)
        self.assertIn(("work:work-999", "produced_by", "evidence:sha256:abcd1234ef"), rel_map)
        self.assertIn(("evidence:sha256:abcd1234ef", "verified_by", "work:work-999"), rel_map)
        self.assertIn(("work:work-999", "applies_to", "code:module:jhoc.guard.path"), rel_map)


if __name__ == "__main__":
    unittest.main()
