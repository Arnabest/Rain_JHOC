"""JHOC LightMem Offline Sleep-Time Memory Consolidator.

Executes offline batch memory consolidation during shougong or offline sleep:
- C1: Clear tier separation: L1_HOT_CONTEXT, L2_DISTILLED_DOMAIN, L3_COLD_ARCHIVE, GOLDEN_INVARIANT.
- C2: Shape-stable distilled invariant schema (<= 500 chars body, <= 620 chars total).
- C3: Exact-kind equivalence key dedup (project_id, memory_type, domain, sensitivity, kind)
      with Jaccard tie-breaker.
- C4: Deterministic contradiction resolution: physical probe > newer UTC timestamp > record_id tiebreak.
      Losers marked SUPERSEDED with linkage; append-only, zero physical deletes.
- C10: Single source of truth in SQLite WAL store; derived artifacts (catalog, index) regenerated
      atomically with post-pass consistency verification.

Enforces Rule 7 (Zero-Emoji & Pure ASCII) and Rule 2 (Fail-Closed).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from typing import Any, Mapping

from jhoc.contracts.errors import ContractError, ErrorCode
from jhoc.contracts.sensitivity import normalize_sensitivity
from jhoc.storage.atomic import atomic_write_text


MAX_INVARIANT_BODY_CHARS = 500
MAX_INVARIANT_TOTAL_CHARS = 620


class MemoryTier(StrEnum):
    L1_HOT_CONTEXT = "L1_HOT_CONTEXT"
    L2_DISTILLED_DOMAIN = "L2_DISTILLED_DOMAIN"
    L3_COLD_ARCHIVE = "L3_COLD_ARCHIVE"
    GOLDEN_INVARIANT = "GOLDEN_INVARIANT"


class KnowledgeKind(StrEnum):
    PROPOSITIONAL = "propositional"  # Facts, paths, versions, port configs
    PRESCRIPTIVE = "prescriptive"    # Invariants, rules, guard policies


@dataclass(frozen=True, slots=True)
class DistilledInvariantContent:
    statement: str
    rationale: str
    boundary: str
    evidence_sha256: str
    source_ref: str
    recorded_at: str

    def to_dict(self) -> dict[str, str]:
        return {
            "statement": self.statement,
            "rationale": self.rationale,
            "boundary": self.boundary,
            "evidence_sha256": self.evidence_sha256,
            "source_ref": self.source_ref,
            "recorded_at": self.recorded_at,
        }

    def validate(self) -> None:
        if not self.statement.strip() or not self.rationale.strip() or not self.boundary.strip():
            raise ContractError("Distilled invariant fields cannot be empty", ErrorCode.INVALID_CONTRACT)
        if len(self.statement) > MAX_INVARIANT_BODY_CHARS:
            raise ContractError(
                f"Invariant statement exceeds {MAX_INVARIANT_BODY_CHARS} chars: {len(self.statement)}",
                ErrorCode.INVALID_CONTRACT,
            )
        serialized = json.dumps(self.to_dict(), ensure_ascii=True)
        if len(serialized) > MAX_INVARIANT_TOTAL_CHARS:
            raise ContractError(
                f"Invariant record exceeds {MAX_INVARIANT_TOTAL_CHARS} chars: {len(serialized)}",
                ErrorCode.INVALID_CONTRACT,
            )


@dataclass(frozen=True, slots=True)
class ConsolidationRecord:
    record_id: str
    tier: MemoryTier
    kind: KnowledgeKind
    domain: str
    content: Mapping[str, Any]
    source_ref: str
    sensitivity: str
    evidence_sha256: str
    recorded_at: str  # ISO UTC
    project_id: str = "jhoc"
    status: str = "ACTIVE"  # ACTIVE, SUPERSEDED
    superseded_by: str = ""
    supersedes_sha256: str = ""


@dataclass(slots=True)
class ConsolidationResult:
    total_processed: int = 0
    deduplicated_count: int = 0
    contradictions_resolved: int = 0
    invariants_promoted: int = 0
    superseded_count: int = 0
    active_count: int = 0
    sqlite_sha256: str = ""
    catalog_sha256: str = ""
    consistency_verified: bool = False
    audit_trail: list[str] = field(default_factory=list)


def _tokenize_text(text: str) -> set[str]:
    cleaned = re.sub(r"[^\w\s]", " ", text.lower())
    tokens = {tok for tok in cleaned.split() if tok}
    return tokens


def _jaccard_similarity(set_a: set[str], set_b: set[str]) -> float:
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a.intersection(set_b))
    union = len(set_a.union(set_b))
    return intersection / union if union > 0 else 0.0


class MemoryConsolidator:
    """Offline batch consolidator implementing LightMem sleep-time consolidation."""

    def __init__(self, db_path: Path | str, workspace_root: Path | str | None = None) -> None:
        self.db_path = Path(db_path).resolve()
        self.workspace_root = Path(workspace_root).resolve() if workspace_root else self.db_path.parent.parent
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS consolidated_memory (
                    record_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    tier TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    content_json TEXT NOT NULL,
                    source_ref TEXT NOT NULL,
                    sensitivity TEXT NOT NULL,
                    evidence_sha256 TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'ACTIVE',
                    superseded_by TEXT NOT NULL DEFAULT '',
                    supersedes_sha256 TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_cons_lookup
                ON consolidated_memory(project_id, tier, kind, domain, status);
                """
            )
            conn.commit()
        finally:
            conn.close()

    def consolidate(
        self,
        new_records: list[ConsolidationRecord],
        catalog_path: Path | str | None = None,
        index_path: Path | str | None = None,
    ) -> ConsolidationResult:
        """Consolidates memory records, resolves contradictions, and regenerates derived artifacts."""
        result = ConsolidationResult(total_processed=len(new_records))
        now_utc = datetime.now(timezone.utc).isoformat()

        # Load existing active records from SQLite
        existing_records = self._load_existing_records()
        all_records: dict[str, ConsolidationRecord] = {r.record_id: r for r in existing_records}

        for rec in new_records:
            all_records[rec.record_id] = rec

        # Phase 1: Group by exact-kind equivalence key
        # (project_id, memory_type/tier, domain, sensitivity, kind)
        clusters: dict[tuple[str, str, str, str, str], list[ConsolidationRecord]] = {}
        for rec in all_records.values():
            key = (rec.project_id, rec.tier.value, rec.domain, rec.sensitivity, rec.kind.value)
            clusters.setdefault(key, []).append(rec)

        resolved_records: dict[str, ConsolidationRecord] = {}

        for key, cluster in clusters.items():
            # Separate already superseded
            active_items = [r for r in cluster if r.status == "ACTIVE"]
            superseded_items = [r for r in cluster if r.status != "ACTIVE"]

            for s in superseded_items:
                resolved_records[s.record_id] = s

            if not active_items:
                continue

            # Sort active items by recorded_at ascending, then record_id ascending
            active_items.sort(key=lambda x: (x.recorded_at, x.record_id))

            # Step 1: Detect contradictions and resolve
            deduped_group: list[ConsolidationRecord] = []
            for item in active_items:
                contradiction_found = False
                for idx, existing in enumerate(deduped_group):
                    # Check for contradiction on key assertions
                    if self._is_contradiction(existing, item):
                        contradiction_found = True
                        result.contradictions_resolved += 1
                        result.superseded_count += 1
                        # C4 Precedence:
                        # (a) physical probe disproval wins (tested during check)
                        # (b) newer UTC timestamp wins
                        # (c) tie-break on record_id
                        winner, loser = self._resolve_contradiction_pair(existing, item)
                        if winner.status == "SUPERSEDED":
                            # Both disproven: neither survives as active
                            resolved_records[winner.record_id] = winner
                            superseded_loser = ConsolidationRecord(
                                record_id=loser.record_id,
                                tier=loser.tier,
                                kind=loser.kind,
                                domain=loser.domain,
                                content=loser.content,
                                source_ref=loser.source_ref,
                                sensitivity=loser.sensitivity,
                                evidence_sha256=loser.evidence_sha256,
                                recorded_at=loser.recorded_at,
                                project_id=loser.project_id,
                                status="SUPERSEDED",
                                superseded_by="DISPROVEN_CONTRADICTION",
                                supersedes_sha256=loser.supersedes_sha256,
                            )
                            resolved_records[superseded_loser.record_id] = superseded_loser
                            result.audit_trail.append(
                                f"[RESOLVE] Contradiction (both disproven): {loser.record_id} and {winner.record_id} both SUPERSEDED"
                            )
                            deduped_group.pop(idx)
                            break
                        else:
                            superseded_loser = ConsolidationRecord(
                                record_id=loser.record_id,
                                tier=loser.tier,
                                kind=loser.kind,
                                domain=loser.domain,
                                content=loser.content,
                                source_ref=loser.source_ref,
                                sensitivity=loser.sensitivity,
                                evidence_sha256=loser.evidence_sha256,
                                recorded_at=loser.recorded_at,
                                project_id=loser.project_id,
                                status="SUPERSEDED",
                                superseded_by=winner.record_id,
                                supersedes_sha256=loser.supersedes_sha256,
                            )
                            resolved_records[superseded_loser.record_id] = superseded_loser
                            result.audit_trail.append(
                                f"[RESOLVE] Contradiction: {loser.record_id} superseded by {winner.record_id}"
                            )
                            deduped_group[idx] = winner
                            break

                    # Step 2: C3 Semantic Deduplication (exact kind already guaranteed)
                    if self._is_near_duplicate(existing, item):
                        contradiction_found = True
                        result.deduplicated_count += 1
                        # Merge without dropping assertions, newer inherits combined source_refs
                        merged = self._merge_near_duplicate_pair(existing, item)
                        deduped_group[idx] = merged
                        # Record absorbed duplicate as SUPERSEDED so SQLite state is reconciled
                        superseded_duplicate = ConsolidationRecord(
                            record_id=item.record_id,
                            tier=item.tier,
                            kind=item.kind,
                            domain=item.domain,
                            content=item.content,
                            source_ref=item.source_ref,
                            sensitivity=item.sensitivity,
                            evidence_sha256=item.evidence_sha256,
                            recorded_at=item.recorded_at,
                            project_id=item.project_id,
                            status="SUPERSEDED",
                            superseded_by=merged.record_id,
                            supersedes_sha256=item.supersedes_sha256,
                        )
                        resolved_records[superseded_duplicate.record_id] = superseded_duplicate
                        result.audit_trail.append(
                            f"[DEDUP] Merged near-duplicate: {item.record_id} into {existing.record_id}"
                        )
                        break

                if not contradiction_found:
                    deduped_group.append(item)

            for d in deduped_group:
                # C2: If invariant tier, enforce <= 500 chars constraint
                if d.tier == MemoryTier.GOLDEN_INVARIANT:
                    self._validate_golden_invariant_bound(d)
                    result.invariants_promoted += 1
                resolved_records[d.record_id] = d
                if d.status == "ACTIVE":
                    result.active_count += 1

        # Reconcile any existing records not in resolved_records
        for r_id, prev_r in all_records.items():
            if r_id not in resolved_records:
                resolved_records[r_id] = ConsolidationRecord(
                    record_id=prev_r.record_id,
                    project_id=prev_r.project_id,
                    tier=prev_r.tier,
                    kind=prev_r.kind,
                    domain=prev_r.domain,
                    content=prev_r.content,
                    source_ref=prev_r.source_ref,
                    sensitivity=prev_r.sensitivity,
                    evidence_sha256=prev_r.evidence_sha256,
                    recorded_at=prev_r.recorded_at,
                    status="SUPERSEDED",
                    superseded_by="CONSOLIDATION_RECONCILED",
                    supersedes_sha256=prev_r.supersedes_sha256,
                )

        # Phase 2: Atomic SQLite Write with Rollback Protection
        prior_records = self._load_existing_records()
        cat_p = Path(catalog_path).resolve() if catalog_path else None
        idx_p = Path(index_path).resolve() if index_path else None
        prior_catalog_bytes = cat_p.read_bytes() if (cat_p and cat_p.is_file()) else None
        prior_index_bytes = idx_p.read_bytes() if (idx_p and idx_p.is_file()) else None

        try:
            self._write_records_to_sqlite(list(resolved_records.values()), now_utc)

            # Phase 3: Derived Artifacts Regeneration (Catalog & Index)
            cat_hash = ""
            if catalog_path:
                cat_hash = self._regenerate_catalog(list(resolved_records.values()), Path(catalog_path))
                result.catalog_sha256 = cat_hash

            if index_path:
                self._regenerate_index(list(resolved_records.values()), Path(index_path))

            # Phase 4: Consistency Verification (Fail-Closed)
            sqlite_hash = self._compute_sqlite_table_sha256()
            result.sqlite_sha256 = sqlite_hash
            result.consistency_verified = self._verify_consistency(list(resolved_records.values()), catalog_path)
            if not result.consistency_verified:
                raise RuntimeError(
                    f"Fail-Closed: Store consistency verification failed (SQLite hash: {sqlite_hash}). "
                    "Store state does not match derived records."
                )
        except Exception:
            try:
                self._restore_records_to_sqlite(prior_records, now_utc)
            except Exception:
                pass

            if cat_p:
                try:
                    if prior_catalog_bytes is not None:
                        atomic_write_text(cat_p, prior_catalog_bytes.decode("utf-8"))
                    elif cat_p.is_file():
                        cat_p.unlink(missing_ok=True)
                except Exception:
                    pass

            if idx_p:
                try:
                    if prior_index_bytes is not None:
                        atomic_write_text(idx_p, prior_index_bytes.decode("utf-8"))
                    elif idx_p.is_file():
                        idx_p.unlink(missing_ok=True)
                except Exception:
                    pass
            raise

        return result

    def _load_existing_records(self) -> list[ConsolidationRecord]:
        records: list[ConsolidationRecord] = []
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT record_id, project_id, tier, kind, domain, content_json,
                       source_ref, sensitivity, evidence_sha256, recorded_at,
                       status, superseded_by, supersedes_sha256
                FROM consolidated_memory
                ORDER BY status ASC, record_id ASC
                """
            )
            for row in cursor.fetchall():
                content = json.loads(row["content_json"])
                records.append(
                    ConsolidationRecord(
                        record_id=row["record_id"],
                        project_id=row["project_id"],
                        tier=MemoryTier(row["tier"]),
                        kind=KnowledgeKind(row["kind"]),
                        domain=row["domain"],
                        content=content,
                        source_ref=row["source_ref"],
                        sensitivity=row["sensitivity"],
                        evidence_sha256=row["evidence_sha256"],
                        recorded_at=row["recorded_at"],
                        status=row["status"],
                        superseded_by=row["superseded_by"],
                        supersedes_sha256=row["supersedes_sha256"],
                    )
                )
        finally:
            conn.close()
        return records

    def _is_contradiction(self, a: ConsolidationRecord, b: ConsolidationRecord) -> bool:
        """Determines if record a and b state contradictory values for the same property."""
        # Check target_key collision
        key_a = a.content.get("target_key") or a.content.get("property") or a.content.get("target")
        key_b = b.content.get("target_key") or b.content.get("property") or b.content.get("target")
        if key_a and key_b and str(key_a).strip().lower() == str(key_b).strip().lower():
            val_a = a.content.get("value") or a.content.get("setting")
            val_b = b.content.get("value") or b.content.get("setting")
            if val_a is not None and val_b is not None and val_a != val_b:
                return True

        # Check explicit contradicts_ref
        if b.content.get("contradicts_ref") == a.record_id or a.content.get("contradicts_ref") == b.record_id:
            return True

        # Check opposing boolean statements
        stmt_a = str(a.content.get("statement", "")).lower()
        stmt_b = str(b.content.get("statement", "")).lower()
        if stmt_a and stmt_b:
            tokens_a = _tokenize_text(stmt_a)
            tokens_b = _tokenize_text(stmt_b)
            overlap = _jaccard_similarity(tokens_a, tokens_b)
            # High overlap but negation mismatch (e.g. disabled vs enabled)
            if overlap > 0.65:
                negation_words = {"not", "disabled", "disallow", "false", "deprecated", "removed"}
                has_neg_a = any(nw in tokens_a for nw in negation_words)
                has_neg_b = any(nw in tokens_b for nw in negation_words)
                if has_neg_a != has_neg_b:
                    return True

        return False

    def _resolve_contradiction_pair(
        self, existing: ConsolidationRecord, incoming: ConsolidationRecord
    ) -> tuple[ConsolidationRecord, ConsolidationRecord]:
        """Resolves contradiction returning (winner, loser)."""
        # (a) Check physical disproval tag: DISPROVEN is a dominant loser
        status_ex = str(existing.content.get("probe_status", ""))
        status_in = str(incoming.content.get("probe_status", ""))

        if status_in == "STALE_MEMORY_DISPROVEN" and status_ex == "STALE_MEMORY_DISPROVEN":
            # Neither survives as ACTIVE
            winner = ConsolidationRecord(
                record_id=incoming.record_id,
                tier=incoming.tier,
                kind=incoming.kind,
                domain=incoming.domain,
                content=incoming.content,
                source_ref=incoming.source_ref,
                sensitivity=incoming.sensitivity,
                evidence_sha256=incoming.evidence_sha256,
                recorded_at=incoming.recorded_at,
                project_id=incoming.project_id,
                status="SUPERSEDED",
                superseded_by="DISPROVEN_CONTRADICTION",
                supersedes_sha256=existing.evidence_sha256,
            )
            return winner, existing

        if status_in == "STALE_MEMORY_DISPROVEN" and status_ex != "STALE_MEMORY_DISPROVEN":
            return existing, incoming
        if status_ex == "STALE_MEMORY_DISPROVEN" and status_in != "STALE_MEMORY_DISPROVEN":
            return incoming, existing

        # VERIFIED vs non-VERIFIED: physical verification strictly dominates unverified
        if status_in == "VERIFIED" and status_ex != "VERIFIED":
            return incoming, existing
        if status_ex == "VERIFIED" and status_in != "VERIFIED":
            return existing, incoming
        if status_ex == "VERIFIED" and status_in == "VERIFIED":
            time_ex = datetime.fromisoformat(existing.recorded_at.replace("Z", "+00:00"))
            time_in = datetime.fromisoformat(incoming.recorded_at.replace("Z", "+00:00"))
            if incoming.evidence_sha256 and incoming.evidence_sha256 != existing.evidence_sha256 and time_in > time_ex:
                winner = ConsolidationRecord(
                    record_id=incoming.record_id,
                    tier=incoming.tier,
                    kind=incoming.kind,
                    domain=incoming.domain,
                    content=incoming.content,
                    source_ref=incoming.source_ref,
                    sensitivity=incoming.sensitivity,
                    evidence_sha256=incoming.evidence_sha256,
                    recorded_at=incoming.recorded_at,
                    project_id=incoming.project_id,
                    status="ACTIVE",
                    supersedes_sha256=existing.evidence_sha256,
                )
                return winner, existing
            return existing, incoming

        # (b) Newer UTC timestamp
        time_ex = datetime.fromisoformat(existing.recorded_at.replace("Z", "+00:00"))
        time_in = datetime.fromisoformat(incoming.recorded_at.replace("Z", "+00:00"))
        if time_in > time_ex:
            winner = ConsolidationRecord(
                record_id=incoming.record_id,
                tier=incoming.tier,
                kind=incoming.kind,
                domain=incoming.domain,
                content=incoming.content,
                source_ref=incoming.source_ref,
                sensitivity=incoming.sensitivity,
                evidence_sha256=incoming.evidence_sha256,
                recorded_at=incoming.recorded_at,
                project_id=incoming.project_id,
                status="ACTIVE",
                supersedes_sha256=existing.evidence_sha256,
            )
            return winner, existing
        elif time_ex > time_in:
            winner = ConsolidationRecord(
                record_id=existing.record_id,
                tier=existing.tier,
                kind=existing.kind,
                domain=existing.domain,
                content=existing.content,
                source_ref=existing.source_ref,
                sensitivity=existing.sensitivity,
                evidence_sha256=existing.evidence_sha256,
                recorded_at=existing.recorded_at,
                project_id=existing.project_id,
                status="ACTIVE",
                supersedes_sha256=incoming.evidence_sha256,
            )
            return winner, incoming

        # (c) Equal timestamps: lexicographical tie-break
        if incoming.record_id > existing.record_id:
            return incoming, existing
        return existing, incoming

    def _is_near_duplicate(self, a: ConsolidationRecord, b: ConsolidationRecord) -> bool:
        stmt_a = str(a.content.get("statement") or a.content.get("summary") or "")
        stmt_b = str(b.content.get("statement") or b.content.get("summary") or "")
        if not stmt_a or not stmt_b:
            return False
        sim = _jaccard_similarity(_tokenize_text(stmt_a), _tokenize_text(stmt_b))
        return sim >= 0.85

    def _merge_near_duplicate_pair(
        self, survivor: ConsolidationRecord, duplicate: ConsolidationRecord
    ) -> ConsolidationRecord:
        # Combine source references cleanly
        sources = set(survivor.source_ref.split(",")) | set(duplicate.source_ref.split(","))
        merged_source = ",".join(sorted(s.strip() for s in sources if s.strip()))
        return ConsolidationRecord(
            record_id=survivor.record_id,
            tier=survivor.tier,
            kind=survivor.kind,
            domain=survivor.domain,
            content=survivor.content,
            source_ref=merged_source,
            sensitivity=survivor.sensitivity,
            evidence_sha256=survivor.evidence_sha256,
            recorded_at=max(survivor.recorded_at, duplicate.recorded_at),
            project_id=survivor.project_id,
            status="ACTIVE",
            supersedes_sha256=survivor.supersedes_sha256,
        )

    def _validate_golden_invariant_bound(self, rec: ConsolidationRecord) -> None:
        stmt = str(rec.content.get("statement", ""))
        if len(stmt) > MAX_INVARIANT_BODY_CHARS:
            raise ContractError(
                f"Distilled Golden Invariant body exceeds {MAX_INVARIANT_BODY_CHARS} chars ({len(stmt)})",
                ErrorCode.INVALID_CONTRACT,
            )
        serialized = json.dumps(rec.content, ensure_ascii=True)
        if len(serialized) > MAX_INVARIANT_TOTAL_CHARS:
            raise ContractError(
                f"Distilled Golden Invariant total record exceeds {MAX_INVARIANT_TOTAL_CHARS} chars ({len(serialized)})",
                ErrorCode.INVALID_CONTRACT,
            )

    def _write_records_to_sqlite(self, records: list[ConsolidationRecord], now_utc: str) -> None:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        try:
            conn.execute("BEGIN IMMEDIATE TRANSACTION;")
            for rec in records:
                conn.execute(
                    """
                    INSERT INTO consolidated_memory (
                        record_id, project_id, tier, kind, domain, content_json,
                        source_ref, sensitivity, evidence_sha256, recorded_at,
                        status, superseded_by, supersedes_sha256, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(record_id) DO UPDATE SET
                        status = excluded.status,
                        superseded_by = excluded.superseded_by,
                        supersedes_sha256 = excluded.supersedes_sha256,
                        content_json = excluded.content_json,
                        source_ref = excluded.source_ref,
                        updated_at = excluded.updated_at;
                    """,
                    (
                        rec.record_id,
                        rec.project_id,
                        rec.tier.value,
                        rec.kind.value,
                        rec.domain,
                        json.dumps(rec.content, ensure_ascii=True),
                        rec.source_ref,
                        rec.sensitivity,
                        rec.evidence_sha256,
                        rec.recorded_at,
                        rec.status,
                        rec.superseded_by,
                        rec.supersedes_sha256,
                        now_utc,
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def _regenerate_catalog(self, records: list[ConsolidationRecord], catalog_path: Path) -> str:
        catalog_items = []
        tier_short_map = {
            MemoryTier.L1_HOT_CONTEXT: "L1",
            MemoryTier.L2_DISTILLED_DOMAIN: "L2",
            MemoryTier.L3_COLD_ARCHIVE: "L3",
            MemoryTier.GOLDEN_INVARIANT: "GOLDEN_INVARIANT",
        }
        for r in sorted(records, key=lambda x: (x.tier.value, x.domain, x.record_id)):
            short_tier = tier_short_map.get(r.tier, r.tier.value)
            catalog_items.append(
                {
                    "record_id": r.record_id,
                    "tier": short_tier,
                    "canonical_tier": r.tier.value,
                    "kind": r.kind.value,
                    "domain": r.domain,
                    "status": r.status,
                    "source_ref": r.source_ref,
                    "evidence_sha256": r.evidence_sha256,
                    "recorded_at": r.recorded_at,
                    "summary": r.content.get("summary") or r.content.get("statement") or "",
                }
            )
        payload = {
            "schema_version": "jhoc-consolidated-catalog/v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_records": len(catalog_items),
            "records": catalog_items,
        }
        text = json.dumps(payload, indent=2, ensure_ascii=True)
        atomic_write_text(catalog_path, text)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _regenerate_index(self, records: list[ConsolidationRecord], index_path: Path) -> str:
        lines = [
            "# JHOC Memory Root Index",
            "",
            "> Consolidated Ground-Truth Index. Auto-generated via LightMem Consolidator.",
            "",
            "## Active Golden Invariants",
            "",
        ]
        invariants = [r for r in records if r.tier == MemoryTier.GOLDEN_INVARIANT and r.status == "ACTIVE"]
        for inv in sorted(invariants, key=lambda x: x.record_id):
            stmt = inv.content.get("statement", "")
            lines.append(f"- **[{inv.domain}]** {stmt} (`{inv.record_id}`)")

        lines.extend(["", "## Active Domain Knowledge", ""])
        domains = [r for r in records if r.tier == MemoryTier.L2_DISTILLED_DOMAIN and r.status == "ACTIVE"]
        for dom in sorted(domains, key=lambda x: (x.domain, x.record_id)):
            summary = dom.content.get("summary") or dom.content.get("statement", "")
            lines.append(f"- **{dom.domain}**: {summary} (`{dom.record_id}`)")

        text = "\n".join(lines) + "\n"
        atomic_write_text(index_path, text)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _compute_sqlite_table_sha256(self) -> str:
        hasher = hashlib.sha256()
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        try:
            cursor = conn.execute(
                """
                SELECT record_id, tier, status, evidence_sha256
                FROM consolidated_memory
                ORDER BY record_id ASC;
                """
            )
            for row in cursor.fetchall():
                hasher.update(f"{row[0]}:{row[1]}:{row[2]}:{row[3]}".encode("utf-8"))
        finally:
            conn.close()
        return hasher.hexdigest()

    def _restore_records_to_sqlite(self, records: list[ConsolidationRecord], now_utc: str) -> None:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        try:
            conn.execute("BEGIN IMMEDIATE TRANSACTION;")
            conn.execute("DELETE FROM consolidated_memory;")
            for rec in records:
                conn.execute(
                    """
                    INSERT INTO consolidated_memory (
                        record_id, project_id, tier, kind, domain, content_json,
                        source_ref, sensitivity, evidence_sha256, recorded_at,
                        status, superseded_by, supersedes_sha256, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        rec.record_id,
                        rec.project_id,
                        rec.tier.value,
                        rec.kind.value,
                        rec.domain,
                        json.dumps(rec.content, ensure_ascii=True),
                        rec.source_ref,
                        rec.sensitivity,
                        rec.evidence_sha256,
                        rec.recorded_at,
                        rec.status,
                        rec.superseded_by,
                        rec.supersedes_sha256,
                        now_utc,
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def _verify_consistency(
        self,
        in_memory_records: list[ConsolidationRecord],
        catalog_path: str | Path | None = None,
    ) -> bool:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        try:
            cursor = conn.execute(
                """
                SELECT record_id, tier, status, evidence_sha256
                FROM consolidated_memory
                ORDER BY record_id ASC;
                """
            )
            rows = cursor.fetchall()
        finally:
            conn.close()

        if len(rows) != len(in_memory_records):
            return False

        mem_sorted = sorted(in_memory_records, key=lambda x: x.record_id)
        for row, mem in zip(rows, mem_sorted):
            if (
                row[0] != mem.record_id
                or row[1] != mem.tier.value
                or row[2] != mem.status
                or row[3] != mem.evidence_sha256
            ):
                return False

        if catalog_path:
            p = Path(catalog_path)
            if not p.is_file():
                return False
            try:
                cat_data = json.loads(p.read_text(encoding="utf-8"))
                cat_records = cat_data.get("records", [])
                if len(cat_records) != len(in_memory_records):
                    return False
                cat_ids = {r["record_id"] for r in cat_records}
                mem_ids = {m.record_id for m in in_memory_records}
                if cat_ids != mem_ids:
                    return False
            except Exception:
                return False

        return True
