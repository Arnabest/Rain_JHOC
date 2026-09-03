from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class RetrievedMemoryItem:
    record_id: str
    tier: str
    domain: str
    title: str
    summary: str
    source_ref: str
    sensitivity: str


class MemoryRetriever:
    """Retrieves tiered L1 Hot Context and L2 Distilled Architectural Memories."""

    _DOMAIN_KEYWORDS: Mapping[str, tuple[str, ...]] = {
        "Network & Proxy Routing": ("代理", "proxy", "网络", "urllib", "http_proxy", "https_proxy", "端口", "socket"),
        "Multi-Model & Provider Interop": ("模型", "provider", "deepseek", "codex", "claude", "gemini", "interop", "多模型", "分发", "协审"),
        "Architecture & Infrastructure": ("架构", "infrastructure", "重构", "微内核", "supervisor", "relay", "guard", "trust", "pipeline"),
        "Desktop Agent & UI Automation": ("桌面", "gui", "pyside", "ui", "界面", "window", "overlay"),
        "Memory & State Governance": ("状态", "治理", "audit", "ledger", "记忆", "快照", "taxonomy", "分类"),
        "Legacy Media & Audio Overlay": ("音频", "tts", "asr", "sovits", "funasr", "media", "转写", "obs"),
    }

    def __init__(
        self,
        db_path: str | Path | None = None,
        catalog_path: str | Path | None = None,
    ) -> None:
        root = Path(__file__).resolve().parent.parent.parent.parent
        self.db_path = Path(db_path) if db_path else root / "logs" / "p19-memory.sqlite"
        self.catalog_path = Path(catalog_path) if catalog_path else root / "docs" / "taxonomy" / "jhoc-memory-taxonomy-catalog.json"
        self._catalog_cache: list[dict[str, Any]] | None = None

    def _load_catalog(self) -> list[dict[str, Any]]:
        if self._catalog_cache is not None:
            return self._catalog_cache
        if not self.catalog_path.exists():
            return []
        try:
            data = json.loads(self.catalog_path.read_text(encoding="utf-8"))
            self._catalog_cache = data.get("records", [])
            return self._catalog_cache
        except Exception:
            return []

    def _fetch_record_body(self, record_id: str) -> str:
        if not self.db_path.exists():
            return ""
        conn = None
        try:
            conn = sqlite3.connect(str(self.db_path), timeout=10)
            cursor = conn.cursor()
            cursor.execute("SELECT content FROM jhoc_memory WHERE record_id=?", (record_id,))
            row = cursor.fetchone()
            if not row:
                return ""
            payload = json.loads(row[0])
            if isinstance(payload, dict):
                return str(payload.get("body") or payload.get("text") or payload.get("summary") or "")
            return str(payload)
        except Exception:
            return ""
        finally:
            if conn is not None:
                conn.close()

    def infer_domain(self, query: str) -> str | None:
        q_lower = query.lower()
        domain_scores: dict[str, int] = {}
        for domain, kws in self._DOMAIN_KEYWORDS.items():
            score = sum(1 for kw in kws if kw.lower() in q_lower)
            if score > 0:
                domain_scores[domain] = score
        if domain_scores:
            return max(domain_scores.items(), key=lambda x: x[1])[0]
        return None

    def retrieve_l1_hot_context(self, limit: int = 1, project_id: str | None = None) -> tuple[RetrievedMemoryItem, ...]:
        """Retrieves active L1 hot session and cutover memories."""
        catalog = self._load_catalog()
        l1_records = [r for r in catalog if r.get("tier") == "L1"]
        if project_id:
            l1_records = [r for r in l1_records if r.get("project_id", "jhoc") in (project_id, "jhoc", "global")]
        # Filter out superseded or obsolete memories
        l1_records = [
            r for r in l1_records
            if not r.get("superseded_by") and r.get("status") not in ("SUPERSEDED", "OBSOLETE", "DEPRECATED")
        ]
        if not l1_records:
            return ()

        # Prioritize recent JHOC architecture activation sessions
        selected = l1_records[:limit]
        results: list[RetrievedMemoryItem] = []
        for r in selected:
            body = self._fetch_record_body(r["record_id"])
            # Extract high-density summary (first 250 chars of meaningful text)
            summary = self._clean_summary(body, max_len=250)
            if not summary:
                summary = str(r.get("abstract") or r.get("title") or f"L1 Context: {r.get('record_id')}")
            results.append(
                RetrievedMemoryItem(
                    record_id=r["record_id"],
                    tier="L1",
                    domain=r.get("domain", "General"),
                    title=r.get("title", ""),
                    summary=summary,
                    source_ref=r.get("relative_path", ""),
                    sensitivity=r.get("sensitivity", "INTERNAL"),
                )
            )
        return tuple(results)

    def retrieve_l2_distilled_memory(
        self,
        query: str,
        domain: str | None = None,
        limit: int = 2,
        project_id: str | None = None,
    ) -> tuple[RetrievedMemoryItem, ...]:
        """Retrieves targeted L2 architectural patterns with time decay and contradiction elimination."""
        catalog = self._load_catalog()
        l2_records = [r for r in catalog if r.get("tier") == "L2"]
        if not l2_records:
            return ()

        target_domain = domain or self.infer_domain(query)
        q_tokens = set(re.findall(r"[A-Za-z0-9_\-#]{2,}", query.lower()))

        scored: list[tuple[float, dict[str, Any]]] = []
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)

        for r in l2_records:
            # 1. Contradiction & Obsolescence Elimination
            if r.get("superseded_by") or r.get("status") in ("SUPERSEDED", "OBSOLETE", "DEPRECATED"):
                continue

            # 2. Multi-Tenant Partition Filtering
            r_project = r.get("project_id", "jhoc")
            if project_id and r_project not in (project_id, "jhoc", "global"):
                continue

            score = 0.0
            r_domain = r.get("domain", "")
            r_title = r.get("title", "").lower()

            if target_domain and r_domain == target_domain:
                score += 5.0

            for tok in q_tokens:
                if tok in r_title:
                    score += 3.0

            # CJK term matching
            for _, kws in self._DOMAIN_KEYWORDS.items():
                for kw in kws:
                    if kw in query and kw.lower() in r_title:
                        score += 4.0

            # 3. Time Decay & Freshness Scoring
            # Extract date stamp YYYYMMDD from source path or record id
            date_match = re.search(r"202[0-9]{5}", r.get("relative_path", "") + r.get("record_id", ""))
            if date_match:
                try:
                    rec_date = datetime.datetime.strptime(date_match.group(0), "%Y%m%d").replace(tzinfo=datetime.timezone.utc)
                    days_old = max(0, (now - rec_date).days)
                    # Freshness boost up to +2.0, smoothly decays over 365 days
                    freshness_bonus = max(0.0, 2.0 * (1.0 - (days_old / 365.0)))
                    score += freshness_bonus
                except Exception:
                    pass

            if score > 0:
                scored.append((score, r))

        scored.sort(key=lambda x: x[0], reverse=True)
        chosen = [r for _, r in scored[:limit]]

        results: list[RetrievedMemoryItem] = []
        for r in chosen:
            body = self._fetch_record_body(r["record_id"])
            summary = self._clean_summary(body, max_len=250)
            if not summary:
                summary = str(r.get("abstract") or r.get("title") or f"L2 Memory: {r.get('record_id')}")
            results.append(
                RetrievedMemoryItem(
                    record_id=r["record_id"],
                    tier="L2",
                    domain=r.get("domain", "Architecture & Infrastructure"),
                    title=r.get("title", ""),
                    summary=summary,
                    source_ref=r.get("relative_path", ""),
                    sensitivity=r.get("sensitivity", "INTERNAL"),
                )
            )
        return tuple(results)

    def retrieve_active_memory_bundle(self, query: str, project_id: str | None = None) -> dict[str, Any]:
        """Produces a unified, sanitized memory payload for ContextOrchestrator."""
        l1_items = self.retrieve_l1_hot_context(limit=1, project_id=project_id)
        l2_items = self.retrieve_l2_distilled_memory(query, limit=2, project_id=project_id)

        return {
            "l1_hot_context": [
                {
                    "record_id": item.record_id,
                    "title": item.title,
                    "domain": item.domain,
                    "summary": item.summary,
                    "source": item.source_ref,
                }
                for item in l1_items
            ],
            "l2_distilled_architecture": [
                {
                    "record_id": item.record_id,
                    "title": item.title,
                    "domain": item.domain,
                    "summary": item.summary,
                    "source": item.source_ref,
                }
                for item in l2_items
            ],
            "total_recalled": len(l1_items) + len(l2_items),
        }

    @staticmethod
    def _clean_summary(raw_text: str, max_len: int = 250) -> str:
        if not raw_text:
            return ""
        # Strip code blocks, markdown headings, excessive newlines
        clean = re.sub(r"```.*?```", "", raw_text, flags=re.DOTALL)
        clean = re.sub(r"#+\s*", "", clean)
        clean = re.sub(r"\s+", " ", clean).strip()
        if len(clean) > max_len:
            return clean[:max_len] + "..."
        return clean
