from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from jhoc.context.orchestrator import ContextSource
from jhoc.context.sanitizer import DataSanitizer
from .store import GraphRelation, GraphStore


class GraphRAGRetriever:
    """Graph-augmented retriever linking topological projections with Atlas knowledge and code entities."""

    DEFAULT_ALLOWED_RELATIONS = frozenset({
        "solves",
        "caused",
        "depends_on",
        "verified_by",
        "belongs_to",
        "derived_from",
        "requires",
        "applies_to",
        "supports",
    })

    def __init__(self, graph_store: Any, atlas_store: Any | None = None) -> None:
        self.graph = graph_store
        self.atlas = atlas_store

    def expand_subgraph(
        self,
        seed_node_ids: Iterable[str],
        *,
        max_hops: int = 1,
        allowed_relations: frozenset[str] | None = None,
        min_quality: str = "VERIFIED",
    ) -> tuple[str, ...]:
        """Performs BFS graph expansion from seed nodes along high-confidence relationship edges."""
        allowed_rel_types = allowed_relations or self.DEFAULT_ALLOWED_RELATIONS
        visited: set[str] = set(seed_node_ids)
        queue: deque[tuple[str, int]] = deque((node_id, 0) for node_id in seed_node_ids)

        # Retrieve candidate relations filtered by quality
        try:
            candidate_relations = self.graph.relations_by_quality(min_quality)
        except Exception:
            candidate_relations = self.graph.relations()

        # Build adjacency map for fast bidirectional hop
        adjacency: dict[str, set[str]] = {}
        for rel in candidate_relations:
            if rel.relation_type in allowed_rel_types:
                adjacency.setdefault(rel.source_node, set()).add(rel.target_node)
                adjacency.setdefault(rel.target_node, set()).add(rel.source_node)

        while queue:
            curr_node, hop = queue.popleft()
            if hop >= max_hops:
                continue

            for neighbor in adjacency.get(curr_node, ()):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, hop + 1))

        return tuple(visited)

    def retrieve_context_sources(
        self,
        seed_node_ids: Iterable[str],
        *,
        max_hops: int = 1,
        allowed_relations: frozenset[str] | None = None,
        min_quality: str = "VERIFIED",
        default_sensitivity: str = "INTERNAL",
        expires_in_minutes: int = 10,
    ) -> tuple[ContextSource, ...]:
        """Retrieves and sanitizes knowledge and code entities from an expanded subgraph."""
        reachable_node_ids = self.expand_subgraph(
            seed_node_ids,
            max_hops=max_hops,
            allowed_relations=allowed_relations,
            min_quality=min_quality,
        )

        sources: list[ContextSource] = []
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=expires_in_minutes)

        for node_id in reachable_node_ids:
            raw_data: dict[str, Any] = {}
            sensitivity = default_sensitivity

            # 1. Check if node is resolvable in Atlas Knowledge Store
            if self.atlas is not None:
                record = self.atlas.get(node_id)
                if record is not None:
                    raw_data = {"knowledge_id": record.record_id, "payload": record.content}
                    sensitivity = record.sensitivity

            # 2. If not an Atlas record, structure code entity or work node
            if not raw_data:
                if node_id.startswith("code:"):
                    parts = node_id.split(":", 2)
                    raw_data = {"entity_id": node_id, "kind": parts[1] if len(parts) > 1 else "code", "symbol": parts[-1]}
                elif node_id.startswith("work:") or node_id.startswith("task:"):
                    raw_data = {"workflow_id": node_id, "status": "PROJECTED"}
                elif node_id.startswith("evidence:"):
                    raw_data = {"evidence_digest": node_id.replace("evidence:", "")}
                else:
                    raw_data = {"node_id": node_id}

            # 3. Cleanse through DataSanitizer to guarantee prompt-injection immunity
            sanitized_payload = DataSanitizer.sanitize_source(raw_data)

            sources.append(
                ContextSource(
                    source_id=f"graph:{node_id}",
                    data=sanitized_payload.content,
                    sensitivity=sensitivity,
                    expires_at=expires_at,
                    allowed_consumers=frozenset({"runner", "agent"}),
                    provenance=(f"graph_traversal:{node_id}",),
                    confidence=sanitized_payload.purity_score,
                )
            )

        return tuple(sources)
