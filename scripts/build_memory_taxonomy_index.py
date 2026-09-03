"""Builds a structured L1/L2/L3 multi-tier taxonomy catalog for migrated Memory records.

Categorizes 3,205 memory records into:
- Tier L1: Hot Context Memory (Current JHOC cutover, migration, and takeover sessions)
- Tier L2: Distilled Architectural Memory (1,092 distilled reflections and design patterns)
- Tier L3: Cold Archive Memory (Historical Verse transcripts, legacy QQMusicOverlay, archive logs)

Also clusters records into 6 primary functional domains and generates JSON + Markdown catalogs.
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jhoc.memory_store.sqlite import SQLiteMemoryStore  # noqa: E402

MEMORY_DB = ROOT / "logs" / "p19-memory.sqlite"
CATALOG_JSON = ROOT / "docs" / "taxonomy" / "jhoc-memory-taxonomy-catalog.json"
CATALOG_MD = ROOT / "docs" / "taxonomy" / "jhoc-memory-taxonomy-catalog.md"


def _classify_tier(rel_path: str, title: str) -> tuple[str, str]:
    """Classifies a memory record into L1, L2, or L3."""
    lower = rel_path.lower()
    lower_title = title.lower()

    if "session-2026090" in lower or "session 4" in lower_title or "jhoc" in lower_title:
        return "L1", "Hot Context Memory (Active JHOC Operations & Sessions)"
    if "distilled" in lower:
        return "L2", "Distilled Architectural Memory (Refined Principles & Runbooks)"
    if "qqmusicoverlay" in lower:
        return "L3", "Cold Archive Memory (Legacy QQMusicOverlay Subsystem)"
    if "sessions/" in lower or "archive/" in lower:
        return "L3", "Cold Archive Memory (Historical Verse Session Transcripts)"
    return "L3", "Cold Archive Memory (Historical Project Records)"


def _classify_domain(rel_path: str, title: str) -> str:
    """Classifies a memory record into a functional domain."""
    text = (rel_path + " " + title).lower()
    if any(k in text for k in ["proxy", "network", "port", "http", "socket", "apinode"]):
        return "Network & Proxy Routing"
    if any(k in text for k in ["model", "provider", "deepseek", "codex", "agy", "claude", "collab", "harness"]):
        return "Multi-Model & Provider Interop"
    if any(k in text for k in ["memory", "state", "atlas", "taxonomy", "digest", "history", "store", "sqlite"]):
        return "Memory & State Governance"
    if any(k in text for k in ["qqmusic", "media", "overlay", "audio", "lyrics"]):
        return "Legacy Media & Audio Overlay"
    if any(k in text for k in ["agent", "ui", "automation", "click", "screen", "keyboard", "window"]):
        return "Desktop Agent & UI Automation"
    return "Architecture & Infrastructure"


def build_taxonomy_catalog() -> dict[str, Any]:
    if not MEMORY_DB.is_file():
        raise SystemExit("Memory database missing in logs/")

    memory = SQLiteMemoryStore(str(MEMORY_DB))
    records = memory.records()

    tier_counts: dict[str, int] = defaultdict(int)
    domain_counts: dict[str, int] = defaultdict(int)
    tier_domain_matrix: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    catalog_items: list[dict[str, Any]] = []

    for r in records:
        content = r.content if isinstance(r.content, dict) else {}
        rel_path = content.get("source_relative_path", "")
        title = content.get("title", rel_path)
        sha = content.get("source_sha256", "")

        tier, tier_desc = _classify_tier(rel_path, title)
        domain = _classify_domain(rel_path, title)

        tier_counts[tier] += 1
        domain_counts[domain] += 1
        tier_domain_matrix[tier][domain] += 1

        catalog_items.append({
            "record_id": r.record_id,
            "tier": tier,
            "domain": domain,
            "title": title,
            "relative_path": rel_path,
            "source_sha256": sha,
            "sensitivity": r.sensitivity.value if hasattr(r.sensitivity, "value") else str(r.sensitivity),
        })

    report = {
        "catalog_version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "total_records": len(records),
        "tier_summary": dict(tier_counts),
        "domain_summary": dict(domain_counts),
        "tier_domain_matrix": {k: dict(v) for k, v in tier_domain_matrix.items()},
        "records": catalog_items,
    }

    CATALOG_JSON.parent.mkdir(parents=True, exist_ok=True)
    CATALOG_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    # Generate Markdown Catalog
    md_lines = [
        "# JHOC Multi-Tier Memory Taxonomy Catalog",
        "",
        f"- Generated At: `{report['generated_at_utc']}`",
        f"- Total Memory Records Categorized: `{len(records)}`",
        "",
        "## 1. Memory Tier Breakdown (L1 / L2 / L3)",
        "",
        "| Tier | Level Name | Count | Purpose |",
        "|:---:|---|---:|---|",
        f"| **L1** | Hot Context Memory | {tier_counts.get('L1', 0)} | 运行时热上下文、当前 JHOC 迁移与操作者交互会话 |",
        f"| **L2** | Distilled Architectural Memory | {tier_counts.get('L2', 0)} | 精炼的架构原则、代理排障运行手册与跨模型规范 |",
        f"| **L3** | Cold Archive Memory | {tier_counts.get('L3', 0)} | 全量历史 Verse 对话实录与 QQMusicOverlay 遗留资产 |",
        "",
        "## 2. Functional Domain Distribution",
        "",
        "| Domain Topic | Record Count | Proportion |",
        "|---|---:|---:|",
    ]
    for dom, count in sorted(domain_counts.items(), key=lambda x: x[1], reverse=True):
        pct = (count / len(records)) * 100
        md_lines.append(f"| `{dom}` | {count} | {pct:.1f}% |")

    md_lines.extend([
        "",
        "## 3. Tier × Domain Matrix",
        "",
        "| Domain | L1 (Hot) | L2 (Distilled) | L3 (Cold Archive) | Total |",
        "|---|---:|---:|---:|---:|",
    ])
    for dom in sorted(domain_counts.keys()):
        l1 = tier_domain_matrix["L1"].get(dom, 0)
        l2 = tier_domain_matrix["L2"].get(dom, 0)
        l3 = tier_domain_matrix["L3"].get(dom, 0)
        md_lines.append(f"| `{dom}` | {l1} | {l2} | {l3} | {l1 + l2 + l3} |")

    md_lines.extend([
        "",
        "## 4. Query & Lookup Optimization",
        "",
        "- **L1 优先注入**：在对话启动时默认加载 L1 热上下文；",
        "- **L2 按需召回**：当意图涉及架构决策、网络代理配置或多模型分发时，精准召回对应 L2 精炼条目；",
        "- **L3 隔离归档**：历史全量归档仅在进行深度溯源和审计时通过图谱节点索引调阅，杜绝长尾干扰。",
    ])

    CATALOG_MD.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    res = build_taxonomy_catalog()
    print(json.dumps({
        "status": "PASS",
        "total_records": res["total_records"],
        "tier_summary": res["tier_summary"],
        "domain_summary": res["domain_summary"],
        "catalog_json": str(CATALOG_JSON),
        "catalog_md": str(CATALOG_MD),
    }, indent=2))
