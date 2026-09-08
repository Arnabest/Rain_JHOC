from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from jhoc.contracts.errors import ContractError, ErrorCode
from jhoc.context.sanitizer import DataSanitizer
from .retriever import GraphRAGRetriever
from .sqlite import SQLiteGraphStore
from .store import GraphNode, GraphRelation


@dataclass(frozen=True, slots=True)
class GraphSearchResult:
    """Decoupled, strongly-typed result returned by GraphKnowledgeIndex."""
    query: str
    seed_nodes: tuple[str, ...]
    expanded_nodes: tuple[str, ...]
    relations: tuple[dict[str, Any], ...]
    entities: tuple[dict[str, Any], ...]
    summary_text: str


class GraphKnowledgeIndex:
    """Independent Knowledge Graph Index service providing autonomous entity resolution & topological subgraph queries."""

    _SEED_KEYWORDS: Mapping[str, tuple[str, ...]] = {
        # Subsystems
        "subsystem:guard": ("guard", "守卫", "安全策略", "越权", "提权", "fail_closed", "path_guard", "token_guard"),
        "subsystem:relay": ("relay", "总线", "租约", "lease", "ack", "nack", "死信", "dlq", "消息信封"),
        "subsystem:shelf": ("shelf", "货架", "技能准入", "能力", "skill", "loader", "shelf_eligible"),
        "subsystem:memory_store": ("memory", "记忆", "l1", "l2", "l3", "taxonomy", "分层记忆", "记忆召回"),
        "subsystem:conductor": ("conductor", "编排", "选模", "planner", "评估", "assessment"),
        "subsystem:context": ("context", "上下文", "两阶段", "pass_a", "pass_b", "脱敏", "sanitizer", "快照"),
        "subsystem:plugins": ("plugin", "插件", "沙箱", "plugin_protocol", "工具调用"),
        "subsystem:intent": ("intent", "意图", "门禁", "classifier", "enforcer", "scaffolding"),
        # Canonical Lessons
        "err:lesson-147": ("147", "元认知", "蒸馏三问", "三问", "批判性反问", "反顺从", "sycophancy", "迎合"),
        "err:lesson-90": ("90", "socket", "轮询", "超时", "轮询超时", "hung", "长连接"),
        "err:lesson-394": ("394", "单测", "暗道", "治理失守", "双平面隔离", "假测试"),
        "err:lesson-402": ("402", "纸面架构", "入库不召回", "沉睡", "空头支票", "文档自欺"),
        "err:lesson-322": ("322", "盲跑", "继续", "连续指令", "探针缺失"),
        "err:lesson-350": ("350", "过虑", "堆叠", "context_rot", "注意力稀释", "overthinking"),
        # Core Domains
        "domain:canonical-lessons": ("教训", "避坑", "规范错题", "错题本"),
        "domain:distilled_architecture": ("架构精炼", "架构模式", "设计模式"),
    }

    def __init__(
        self,
        db_path: str | Path | None = None,
        graph_store: SQLiteGraphStore | None = None,
    ) -> None:
        root = Path(__file__).resolve().parent.parent.parent.parent
        self.db_path = Path(db_path) if db_path else root / "logs" / "p19-graph.sqlite"
        self._owns_store = graph_store is None
        self._store = graph_store or SQLiteGraphStore(str(self.db_path))
        self._retriever = GraphRAGRetriever(self._store)

    def close(self) -> None:
        if self._owns_store and self._store is not None:
            self._store.close()

    def resolve_seed_nodes(self, query: str, limit: int = 3) -> tuple[str, ...]:
        """Maps query concepts and keywords to canonical graph seed node IDs."""
        q_lower = query.lower()
        scored_seeds: dict[str, int] = {}

        for node_id, keywords in self._SEED_KEYWORDS.items():
            match_count = 0
            for kw in keywords:
                kw_lower = kw.lower()
                if kw_lower.isdigit():
                    # 纯数字编号（如 90, 147）必须有非数字边界或前缀，防止 67890 误触
                    if re.search(rf"(?:^|[^\d]){re.escape(kw_lower)}(?:[^\d]|$)", q_lower):
                        match_count += 1
                else:
                    if kw_lower in q_lower:
                        match_count += 1
            if match_count > 0:
                scored_seeds[node_id] = match_count

        if not scored_seeds:
            return ()

        # Sort by match score descending
        sorted_seeds = sorted(scored_seeds.items(), key=lambda x: x[1], reverse=True)
        return tuple(node_id for node_id, _ in sorted_seeds[:limit])

    def search(
        self,
        query: str,
        *,
        max_hops: int = 1,
        min_quality: str = "VERIFIED",
        limit_seeds: int = 3,
    ) -> GraphSearchResult:
        """Independently searches knowledge graph, expands reachable subgraph, and returns structured projection."""
        seeds = self.resolve_seed_nodes(query, limit=limit_seeds)
        if not seeds:
            return GraphSearchResult(
                query=query,
                seed_nodes=(),
                expanded_nodes=(),
                relations=(),
                entities=(),
                summary_text="[GraphIndex] 无匹配的图谱实体种子，未检索到拓扑关联。",
            )

        # 1. Expand BFS subgraph
        expanded_nodes = self._retriever.expand_subgraph(
            seeds,
            max_hops=max_hops,
            min_quality=min_quality,
        )

        # 2. Extract edge relations connecting the expanded nodes
        all_relations = self._store.relations_by_quality(min_quality)
        node_set = set(expanded_nodes)
        matched_relations: list[dict[str, Any]] = []

        for rel in all_relations:
            if rel.source_node in node_set and rel.target_node in node_set:
                matched_relations.append({
                    "relation_id": rel.relation_id,
                    "source": rel.source_node,
                    "target": rel.target_node,
                    "type": rel.relation_type,
                    "confidence": rel.confidence,
                    "quality": rel.quality,
                })

        # 3. Resolve entity summaries
        entities: list[dict[str, Any]] = []
        for n_id in expanded_nodes:
            parts = n_id.split(":", 1)
            e_type = parts[0]
            name = parts[1] if len(parts) > 1 else n_id
            entities.append({
                "node_id": n_id,
                "type": e_type,
                "name": name,
                "is_seed": n_id in seeds,
            })

        # 4. Generate clean sanitized topological summary text
        summary_lines = [
            f"[GraphIndex] 检索词 '{query}' 命中图谱种子节点 {list(seeds)}，在 {max_hops} 跳范围内拓展出 {len(expanded_nodes)} 个关联节点：",
        ]
        for rel in matched_relations[:8]:
            summary_lines.append(f"  • ({rel['source']}) --[{rel['type']}]--> ({rel['target']}) [质量: {rel['quality']}]")

        summary_text = "\n".join(summary_lines)
        sanitized_summary = DataSanitizer.sanitize_source({"summary": summary_text})

        return GraphSearchResult(
            query=query,
            seed_nodes=seeds,
            expanded_nodes=expanded_nodes,
            relations=tuple(matched_relations),
            entities=tuple(entities),
            summary_text=str(sanitized_summary.content.get("summary", "")),
        )
