from __future__ import annotations

import json
import sqlite3
from typing import Any, Callable

from jhoc.contracts.errors import ContractError, ErrorCode
from .evolution import Candidate, CandidateStatus, CanaryObservation, Forge


class SQLiteForge(Forge):
    """Durable candidate and canary history owned by Forge."""

    def __init__(self, path: str) -> None:
        super().__init__()
        self._db = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("CREATE TABLE IF NOT EXISTS jhoc_forge_candidate (candidate_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        self._db.execute("CREATE TABLE IF NOT EXISTS jhoc_forge_canary (candidate_id TEXT NOT NULL, sequence INTEGER NOT NULL, healthy INTEGER NOT NULL, score REAL NOT NULL, evidence_ref TEXT NOT NULL, PRIMARY KEY(candidate_id,sequence))")
        self._db.commit()
        for candidate_id, payload in self._db.execute("SELECT candidate_id,payload FROM jhoc_forge_candidate").fetchall():
            value = json.loads(payload)
            candidate = Candidate(
                value["change"], tuple(value["evidence_refs"]), value["status"], candidate_id,
                value.get("benchmark_ref"), value.get("approved_by"), value.get("canary_score"),
                value.get("rollback_reason"), value.get("version", "1"),
            )
            self._candidates[candidate_id] = candidate
        for candidate_id, sequence, healthy, score, evidence_ref in self._db.execute("SELECT candidate_id,sequence,healthy,score,evidence_ref FROM jhoc_forge_canary ORDER BY candidate_id,sequence").fetchall():
            self._canary_observations.setdefault(candidate_id, []).append(CanaryObservation(int(sequence), bool(healthy), float(score), evidence_ref))

    def close(self) -> None:
        with self._lock:
            self._db.close()

    @staticmethod
    def _payload(candidate: Candidate) -> str:
        return json.dumps({
            "change": candidate.change, "evidence_refs": list(candidate.evidence_refs), "status": candidate.status.value,
            "benchmark_ref": candidate.benchmark_ref, "approved_by": candidate.approved_by,
            "canary_score": candidate.canary_score, "rollback_reason": candidate.rollback_reason, "version": candidate.version,
        }, sort_keys=True, separators=(",", ":"))

    def _sync_candidate(self, candidate: Candidate) -> None:
        try:
            self._db.execute("BEGIN IMMEDIATE")
            self._db.execute("INSERT INTO jhoc_forge_candidate VALUES(?,?) ON CONFLICT(candidate_id) DO UPDATE SET payload=excluded.payload", (candidate.candidate_id, self._payload(candidate)))
            self._db.commit()
        except Exception:
            if self._db.in_transaction:
                self._db.rollback()
            raise

    def _mutate_candidate(self, operation: Callable[..., Candidate], *args: Any, **kwargs: Any) -> Candidate:
        with self._lock:
            previous_candidates = dict(self._candidates)
            previous_observations = {key: list(value) for key, value in self._canary_observations.items()}
            try:
                result = operation(*args, **kwargs)
                self._sync_candidate(result)
                return result
            except Exception:
                self._candidates = previous_candidates
                self._canary_observations = previous_observations
                raise

    def observe(self, candidate: Candidate) -> Candidate:
        return self._mutate_candidate(super().observe, candidate)

    def evaluate(self, candidate_id: str, **kwargs) -> Candidate:
        return self._mutate_candidate(super().evaluate, candidate_id, **kwargs)

    def promote(self, candidate_id: str, **kwargs) -> Candidate:
        return self._mutate_candidate(super().promote, candidate_id, **kwargs)

    def complete_canary(self, candidate_id: str, **kwargs) -> Candidate:
        return self._mutate_candidate(super().complete_canary, candidate_id, **kwargs)

    def observe_canary(self, candidate_id: str, *, healthy: bool, score: float, evidence_ref: str) -> CanaryObservation:
        with self._lock:
            candidate = self._candidates[candidate_id]
            if candidate.status != CandidateStatus.CANARY:
                raise ContractError("candidate is not in canary", ErrorCode.INVALID_TRANSITION)
            try:
                self._db.execute("BEGIN IMMEDIATE")
                row = self._db.execute("SELECT COALESCE(MAX(sequence),0) FROM jhoc_forge_canary WHERE candidate_id=?", (candidate_id,)).fetchone()
                result = CanaryObservation(int(row[0]) + 1, healthy, score, evidence_ref)
                self._db.execute("INSERT INTO jhoc_forge_canary VALUES(?,?,?,?,?)", (candidate_id, result.sequence, int(result.healthy), result.score, result.evidence_ref))
                self._db.commit()
            except Exception:
                if self._db.in_transaction:
                    self._db.rollback()
                raise
            self._canary_observations.setdefault(candidate_id, []).append(result)
            return result
