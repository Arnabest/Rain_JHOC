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
        "produced_by",
        "triggered_by",
        "touches_file",
        "modified_by",
        "observed_in",
        "used_by",
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

    def find_file_lineage(self, file_identifier: str) -> dict[str, Any]:
        """Finds upstream tasks, sessions, projects, errors, and lessons for a given file node."""
        clean_needle = file_identifier.replace("\\", "/").replace("%3A", ":").replace("%3a", ":").strip().lower()
        if clean_needle.startswith("file:"):
            clean_needle = clean_needle[5:]

        # Fetch all relations
        try:
            relations = self.graph.relations()
        except Exception:
            relations = ()

        # Collect candidate matching nodes in the graph
        candidate_nodes: set[str] = set()
        for r in relations:
            for n in (r.source_node, r.target_node):
                if n.startswith("file:"):
                    norm_n = n.replace("%3A", ":").replace("%3a", ":").lower()
                    if norm_n.endswith(clean_needle) or f"/{clean_needle}" in norm_n or norm_n == f"file:{clean_needle}":
                        candidate_nodes.add(n)

        upstream_tasks: set[str] = set()
        upstream_sessions: set[str] = set()
        related_errors: set[str] = set()
        related_lessons: set[str] = set()
        related_projects: set[str] = set()

        # Pass 1: Direct 1-hop relations around candidate_nodes
        for r in relations:
            src, tgt, rtype = r.source_node, r.target_node, r.relation_type
            if tgt in candidate_nodes:
                if src.startswith("task:"):
                    upstream_tasks.add(src)
                elif src.startswith("error:"):
                    related_errors.add(src)
                elif src.startswith("lesson:"):
                    related_lessons.add(src)
                elif src.startswith("session:"):
                    upstream_sessions.add(src)
            elif src in candidate_nodes:
                if tgt.startswith("project:"):
                    related_projects.add(tgt)
                elif tgt.startswith("task:"):
                    upstream_tasks.add(tgt)
                elif tgt.startswith("session:"):
                    upstream_sessions.add(tgt)

        # Pass 2: 2-hop relations from tasks to sessions and lessons
        for r in relations:
            src, tgt, rtype = r.source_node, r.target_node, r.relation_type
            if tgt in upstream_tasks:
                if src.startswith("session:") or src.startswith("raw:"):
                    upstream_sessions.add(src)
                elif src.startswith("lesson:"):
                    related_lessons.add(src)
            elif src in upstream_tasks:
                if tgt.startswith("session:") or tgt.startswith("raw:"):
                    upstream_sessions.add(tgt)
                elif tgt.startswith("lesson:"):
                    related_lessons.add(tgt)
                elif tgt.startswith("project:"):
                    related_projects.add(tgt)

        matched_node = sorted(candidate_nodes)[0] if candidate_nodes else f"file:{clean_needle}"
        return {
            "file_node": DataSanitizer.sanitize_text(matched_node)[0],
            "matched_nodes": [DataSanitizer.sanitize_text(n)[0] for n in sorted(candidate_nodes)],
            "upstream_tasks": [DataSanitizer.sanitize_text(t)[0] for t in sorted(upstream_tasks)],
            "upstream_sessions": [DataSanitizer.sanitize_text(s)[0] for s in sorted(upstream_sessions)],
            "related_errors": [DataSanitizer.sanitize_text(e)[0] for e in sorted(related_errors)],
            "related_lessons": [DataSanitizer.sanitize_text(l)[0] for l in sorted(related_lessons)],
            "related_projects": [DataSanitizer.sanitize_text(p)[0] for p in sorted(related_projects)],
        }

    def find_related_lessons(self, target_node_id: str) -> tuple[str, ...]:
        """Traverses within 2 hops to collect any applicable lesson nodes."""
        expanded = self.expand_subgraph([target_node_id], max_hops=2)
        return tuple(sorted(DataSanitizer.sanitize_text(n)[0] for n in expanded if n.startswith("lesson:")))

