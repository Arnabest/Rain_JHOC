from __future__ import annotations

import sqlite3
from threading import RLock

from jhoc.contracts.errors import ContractError
from .store import GraphNode, GraphRelation, _QUALITY


class SQLiteGraphStore:
    """Durable relationship projection; knowledge content remains in Atlas."""

    def __init__(self, path: str) -> None:
        self._db = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("CREATE TABLE IF NOT EXISTS jhoc_graph_node (node_id TEXT PRIMARY KEY, node_type TEXT NOT NULL)")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS jhoc_graph_relation (relation_id TEXT PRIMARY KEY, source_node TEXT NOT NULL, target_node TEXT NOT NULL, relation_type TEXT NOT NULL, confidence REAL NOT NULL, source_ref TEXT NOT NULL, verification_status TEXT NOT NULL, quality TEXT NOT NULL)"
        )
        self._db.commit()
        self._lock = RLock()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def add_node(self, node: GraphNode) -> None:
        with self._lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                row = self._db.execute("SELECT node_type FROM jhoc_graph_node WHERE node_id=?", (node.node_id,)).fetchone()
                if row is not None and row[0] != node.node_type:
                    raise ContractError("graph node ID conflict")
                self._db.execute("INSERT OR IGNORE INTO jhoc_graph_node VALUES(?,?)", (node.node_id, node.node_type))
                self._db.commit()
            except Exception:
                if self._db.in_transaction:
                    self._db.rollback()
                raise

    def add_relation(self, relation: GraphRelation) -> None:
        with self._lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                nodes = self._db.execute("SELECT node_id FROM jhoc_graph_node WHERE node_id IN (?,?)", (relation.source_node, relation.target_node)).fetchall()
                if {row[0] for row in nodes} != {relation.source_node, relation.target_node}:
                    raise ContractError("graph relation references unknown node")
                row = self._db.execute(
                    "SELECT source_node,target_node,relation_type,confidence,source_ref,verification_status,quality FROM jhoc_graph_relation WHERE relation_id=?",
                    (relation.relation_id,),
                ).fetchone()
                expected = (relation.source_node, relation.target_node, relation.relation_type, relation.confidence, relation.source_ref, relation.verification_status, relation.quality)
                if row is not None and tuple(row) != expected:
                    raise ContractError("graph relation ID conflict")
                self._db.execute("INSERT OR IGNORE INTO jhoc_graph_relation VALUES(?,?,?,?,?,?,?,?)", (relation.relation_id, *expected))
                self._db.commit()
            except Exception:
                if self._db.in_transaction:
                    self._db.rollback()
                raise

    @staticmethod
    def _relation(row: tuple[object, ...]) -> GraphRelation:
        return GraphRelation(str(row[0]), str(row[1]), str(row[2]), str(row[3]), float(row[4]), str(row[5]), str(row[6]), str(row[7]))

    def relations(self) -> tuple[GraphRelation, ...]:
        with self._lock:
            rows = self._db.execute("SELECT relation_id,source_node,target_node,relation_type,confidence,source_ref,verification_status,quality FROM jhoc_graph_relation ORDER BY relation_id").fetchall()
        return tuple(self._relation(tuple(row)) for row in rows)

    def relations_by_quality(self, quality: str) -> tuple[GraphRelation, ...]:
        if quality not in _QUALITY:
            raise ContractError("unknown graph relation quality")
        with self._lock:
            rows = self._db.execute("SELECT relation_id,source_node,target_node,relation_type,confidence,source_ref,verification_status,quality FROM jhoc_graph_relation WHERE quality=? ORDER BY relation_id", (quality,)).fetchall()
        return tuple(self._relation(tuple(row)) for row in rows)
