from __future__ import annotations

import sqlite3
from threading import RLock

from jhoc.contracts.errors import ContractError, ErrorCode
from jhoc.registry import CapabilityRecord, VerificationStatus

from .shelf import Shelf, ShelfEntry


class SQLiteShelf(Shelf):
    """Durable shelf availability view owned separately from Registry."""

    def __init__(self, path: str) -> None:
        super().__init__()
        self._db = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS jhoc_shelf ("
            "capability_id TEXT NOT NULL, version TEXT NOT NULL, health TEXT NOT NULL, "
            "PRIMARY KEY(capability_id,version))"
        )
        self._db.commit()
        self._lock = RLock()
        self._closed = False

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._db.close()
                self._closed = True

    def admit(self, record: CapabilityRecord) -> ShelfEntry:
        if record.verification_status != VerificationStatus.VERIFIED or not record.manifest.shelf_eligible:
            raise ContractError("only verified shelf-eligible capabilities may be admitted", ErrorCode.POLICY_DENIED)
        entry = ShelfEntry(record.capability_id, record.version, record.health)
        with self._lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                self._db.execute(
                    "INSERT INTO jhoc_shelf(capability_id,version,health) VALUES(?,?,?) "
                    "ON CONFLICT(capability_id,version) DO UPDATE SET health=excluded.health",
                    (entry.capability_id, entry.version, entry.health),
                )
                self._db.commit()
            except Exception:
                if self._db.in_transaction:
                    self._db.rollback()
                raise
        return entry

    def remove(self, capability_id: str, version: str) -> None:
        with self._lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                self._db.execute(
                    "DELETE FROM jhoc_shelf WHERE capability_id=? AND version=?",
                    (capability_id, version),
                )
                self._db.commit()
            except Exception:
                if self._db.in_transaction:
                    self._db.rollback()
                raise

    def get(self, capability_id: str, version: str) -> ShelfEntry | None:
        with self._lock:
            row = self._db.execute(
                "SELECT health FROM jhoc_shelf WHERE capability_id=? AND version=?",
                (capability_id, version),
            ).fetchone()
        return ShelfEntry(capability_id, version, row[0]) if row else None

    def entries(self) -> tuple[ShelfEntry, ...]:
        with self._lock:
            rows = self._db.execute(
                "SELECT capability_id,version,health FROM jhoc_shelf ORDER BY capability_id,version"
            ).fetchall()
        return tuple(ShelfEntry(*row) for row in rows)
