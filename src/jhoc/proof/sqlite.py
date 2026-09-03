from __future__ import annotations

from datetime import datetime, timezone
import json
import sqlite3
from threading import RLock
from typing import Callable

from jhoc.contracts.errors import ContractError, ErrorCode
from .store import EvidencePackage, GateAcceptanceReceipt, GateAcceptanceState


class SQLiteProofStore:
    """Durable evidence store with content-addressed records."""

    def __init__(self, path: str) -> None:
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.execute("CREATE TABLE IF NOT EXISTS jhoc_evidence (digest TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS jhoc_gate_acceptance ("
            "digest TEXT PRIMARY KEY, task_id TEXT NOT NULL, work_id TEXT NOT NULL, accepted_at TEXT NOT NULL, "
            "state TEXT NOT NULL DEFAULT 'ACCEPTED', "
            "FOREIGN KEY(digest) REFERENCES jhoc_evidence(digest))"
        )
        columns = {row[1] for row in self._db.execute("PRAGMA table_info(jhoc_gate_acceptance)")}
        if "state" not in columns:
            self._db.execute(
                "ALTER TABLE jhoc_gate_acceptance ADD COLUMN state TEXT NOT NULL DEFAULT 'ACCEPTED'"
            )
        self._db.commit()
        self._lock = RLock()
        self._gate_writer_bound = False

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def record_evidence(self, package: EvidencePackage) -> str:
        digest = package.digest
        payload = self._encode(package)
        with self._lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                row = self._db.execute("SELECT payload FROM jhoc_evidence WHERE digest=?", (digest,)).fetchone()
                if row is not None:
                    if row[0] != payload:
                        raise ContractError("evidence digest collision", ErrorCode.IDEMPOTENCY_CONFLICT)
                    self._db.commit()
                    return digest
                self._db.execute("INSERT INTO jhoc_evidence(digest,payload) VALUES(?,?)", (digest, payload))
                self._db.commit()
            except Exception:
                if self._db.in_transaction:
                    self._db.rollback()
                raise
        return digest

    def evidence(self, digest: str) -> EvidencePackage | None:
        with self._lock:
            row = self._db.execute("SELECT payload FROM jhoc_evidence WHERE digest=?", (digest,)).fetchone()
        if row is None:
            return None
        value = json.loads(row[0])
        return EvidencePackage(
            value["task_id"], value["work_id"], value["policy_ref"], value["capability_version"],
            value["expected"], value["execution"], value["verification"], value["side_effect_state"], tuple(value["evidence_refs"]),
        )

    def _bind_gate_writer(
        self,
    ) -> tuple[Callable[[EvidencePackage], str], Callable[[str], None], Callable[[str], None]]:
        with self._lock:
            if self._gate_writer_bound:
                raise ContractError("ProofStore already has a Gate writer", ErrorCode.POLICY_DENIED)
            self._gate_writer_bound = True

        def prepare(package: EvidencePackage) -> str:
            digest = package.digest
            payload = self._encode(package)
            accepted_at = datetime.now(timezone.utc)
            with self._lock:
                try:
                    self._db.execute("BEGIN IMMEDIATE")
                    evidence_row = self._db.execute(
                        "SELECT payload FROM jhoc_evidence WHERE digest=?", (digest,)
                    ).fetchone()
                    if evidence_row is not None and evidence_row[0] != payload:
                        raise ContractError("evidence digest collision", ErrorCode.IDEMPOTENCY_CONFLICT)
                    row = self._db.execute(
                        "SELECT task_id,work_id FROM jhoc_gate_acceptance WHERE digest=?", (digest,)
                    ).fetchone()
                    if row is not None:
                        if row != (package.task_id, package.work_id):
                            raise ContractError("Gate acceptance conflict", ErrorCode.IDEMPOTENCY_CONFLICT)
                        self._db.commit()
                        return digest
                    if evidence_row is None:
                        self._db.execute(
                            "INSERT INTO jhoc_evidence(digest,payload) VALUES(?,?)", (digest, payload)
                        )
                    self._db.execute(
                        "INSERT INTO jhoc_gate_acceptance(digest,task_id,work_id,accepted_at,state) VALUES(?,?,?,?,?)",
                        (
                            digest,
                            package.task_id,
                            package.work_id,
                            accepted_at.isoformat(),
                            GateAcceptanceState.PENDING.value,
                        ),
                    )
                    self._db.commit()
                except Exception:
                    if self._db.in_transaction:
                        self._db.rollback()
                    raise
            return digest

        def finalize(digest: str) -> None:
            with self._lock:
                try:
                    self._db.execute("BEGIN IMMEDIATE")
                    row = self._db.execute(
                        "SELECT state FROM jhoc_gate_acceptance WHERE digest=?", (digest,)
                    ).fetchone()
                    if row is None:
                        raise ContractError("pending Gate acceptance not found", ErrorCode.INVALID_CONTRACT)
                    if row[0] != GateAcceptanceState.ACCEPTED.value:
                        self._db.execute(
                            "UPDATE jhoc_gate_acceptance SET state=?,accepted_at=? WHERE digest=?",
                            (GateAcceptanceState.ACCEPTED.value, datetime.now(timezone.utc).isoformat(), digest),
                        )
                    self._db.commit()
                except Exception:
                    if self._db.in_transaction:
                        self._db.rollback()
                    raise

        def abort(digest: str) -> None:
            with self._lock:
                try:
                    self._db.execute("BEGIN IMMEDIATE")
                    self._db.execute(
                        "DELETE FROM jhoc_gate_acceptance WHERE digest=? AND state=?",
                        (digest, GateAcceptanceState.PENDING.value),
                    )
                    self._db.commit()
                except Exception:
                    if self._db.in_transaction:
                        self._db.rollback()
                    raise

        return prepare, finalize, abort

    def acceptance(self, digest: str) -> GateAcceptanceReceipt | None:
        with self._lock:
            row = self._db.execute(
                "SELECT task_id,work_id,accepted_at,state FROM jhoc_gate_acceptance WHERE digest=? AND state=?",
                (digest, GateAcceptanceState.ACCEPTED.value),
            ).fetchone()
        return (
            GateAcceptanceReceipt(
                digest, row[0], row[1], datetime.fromisoformat(row[2]), GateAcceptanceState(row[3])
            )
            if row is not None
            else None
        )

    def pending_acceptance(self, digest: str) -> GateAcceptanceReceipt | None:
        with self._lock:
            row = self._db.execute(
                "SELECT task_id,work_id,accepted_at,state FROM jhoc_gate_acceptance WHERE digest=? AND state=?",
                (digest, GateAcceptanceState.PENDING.value),
            ).fetchone()
        return (
            GateAcceptanceReceipt(
                digest, row[0], row[1], datetime.fromisoformat(row[2]), GateAcceptanceState(row[3])
            )
            if row is not None
            else None
        )

    @staticmethod
    def _encode(package: EvidencePackage) -> str:
        # Mirror EvidencePackage.digest: the same canonical encoding must produce
        # the same digest in-memory and persisted, so non-JSON values (datetime,
        # UUID, ...) resolve through default=str in both stores.
        return json.dumps({
            "task_id": package.task_id, "work_id": package.work_id, "policy_ref": package.policy_ref,
            "capability_version": package.capability_version, "expected": package.expected,
            "execution": package.execution, "verification": package.verification,
            "side_effect_state": package.side_effect_state, "evidence_refs": list(package.evidence_refs),
        }, sort_keys=True, separators=(",", ":"), default=str)
