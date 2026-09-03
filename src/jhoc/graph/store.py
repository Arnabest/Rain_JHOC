from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from jhoc.contracts.errors import ContractError


_RELATION_TYPES = frozenset({
    "related_to", "derived_from", "supports", "contradicts", "verified_by", "used_by",
    "depends_on", "caused", "solves", "belongs_to", "applies_to", "supersedes",
    "observed_in", "produced_by", "reviewed_by", "requires", "blocked_by",
})
_QUALITY = frozenset({"UNASSESSED", "HYPOTHESIS", "SUPPORTED", "VERIFIED", "CONTRADICTED"})


@dataclass(frozen=True, slots=True)
class GraphNode:
    node_id: str
    node_type: str


@dataclass(frozen=True, slots=True)
class GraphRelation:
    relation_id: str
    source_node: str
    target_node: str
    relation_type: str
    confidence: float
    source_ref: str
    verification_status: str
    quality: str = "UNASSESSED"

    def __post_init__(self) -> None:
        if not 0 <= self.confidence <= 1 or not self.source_ref.strip() or self.relation_type not in _RELATION_TYPES:
            raise ContractError("graph relation confidence/source_ref invalid")
        if self.quality not in _QUALITY:
            raise ContractError("unknown graph relation quality")


class GraphStore:
    """Stores only relationship projections; Atlas owns knowledge content."""

    def __init__(self) -> None:
        self._nodes: dict[str, GraphNode] = {}
        self._relations: dict[str, GraphRelation] = {}
        self._lock = RLock()

    def add_node(self, node: GraphNode) -> None:
        with self._lock:
            self._nodes.setdefault(node.node_id, node)

    def add_relation(self, relation: GraphRelation) -> None:
        with self._lock:
            if relation.source_node not in self._nodes or relation.target_node not in self._nodes:
                raise ContractError("graph relation references unknown node")
            if relation.relation_id in self._relations and self._relations[relation.relation_id] != relation:
                raise ContractError("graph relation ID conflict")
            self._relations[relation.relation_id] = relation

    def relations(self) -> tuple[GraphRelation, ...]:
        with self._lock:
            return tuple(self._relations.values())

    def relations_by_quality(self, quality: str) -> tuple[GraphRelation, ...]:
        if quality not in _QUALITY:
            raise ContractError("unknown graph relation quality")
        with self._lock:
            return tuple(item for item in self._relations.values() if item.quality == quality)
