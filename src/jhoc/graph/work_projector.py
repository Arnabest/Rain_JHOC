from __future__ import annotations

import hashlib
from typing import Any

from .store import GraphNode, GraphRelation


class WorkGraphProjector:
    """Projects task workflows, policy decisions, and Gate evidence packages into GraphStore."""

    @classmethod
    def project_task_execution(
        cls,
        graph_store: Any,
        task_id: str,
        work_id: str,
        policy_ref: str,
        *,
        evidence_digest: str | None = None,
        target_code_entity: str | None = None,
        source_ref: str = "jhoc.runner.execution",
    ) -> list[str]:
        """Projects a completed or pending execution event into the work node graph."""
        task_node_id = f"task:{task_id}"
        work_node_id = f"work:{work_id}"
        decision_node_id = f"decision:{policy_ref}"

        # 1. Register base nodes
        graph_store.add_node(GraphNode(task_node_id, "Task"))
        graph_store.add_node(GraphNode(work_node_id, "WorkItem"))
        graph_store.add_node(GraphNode(decision_node_id, "Decision"))

        relations_to_add: list[GraphRelation] = []

        def make_rel(src: str, tgt: str, rel_type: str, quality: str = "VERIFIED") -> GraphRelation:
            rel_id = f"rel:work:{hashlib.sha256(f'{src}:{rel_type}:{tgt}'.encode()).hexdigest()[:16]}"
            return GraphRelation(
                relation_id=rel_id,
                source_node=src,
                target_node=tgt,
                relation_type=rel_type,
                confidence=1.0,
                source_ref=source_ref,
                verification_status="VERIFIED",
                quality=quality,
            )

        # 2. Base task and policy relations
        relations_to_add.append(make_rel(task_node_id, work_node_id, "requires"))
        relations_to_add.append(make_rel(decision_node_id, task_node_id, "applies_to"))

        # 3. Evidence relation if present
        if evidence_digest:
            evidence_node_id = f"evidence:{evidence_digest}"
            graph_store.add_node(GraphNode(evidence_node_id, "Evidence"))
            relations_to_add.append(make_rel(work_node_id, evidence_node_id, "produced_by"))
            relations_to_add.append(make_rel(evidence_node_id, work_node_id, "verified_by"))

        # 4. Target code entity relation if specified
        if target_code_entity:
            code_node_id = f"code:{target_code_entity}"
            graph_store.add_node(GraphNode(code_node_id, "CodeEntity"))
            relations_to_add.append(make_rel(work_node_id, code_node_id, "applies_to"))

        # 5. Commit relations
        added_ids: list[str] = []
        for rel in relations_to_add:
            try:
                graph_store.add_relation(rel)
                added_ids.append(rel.relation_id)
            except Exception:
                pass

        return added_ids
