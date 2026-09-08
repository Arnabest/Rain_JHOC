from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import sqlite3
from threading import RLock
from typing import Any, Mapping

from jhoc.contracts.errors import ContractError, ErrorCode


def _json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    except (TypeError, ValueError) as exc:
        raise ContractError("value is not serializable") from exc


class SQLiteStore:
    """Durable local stores sharing one SQLite file but isolated by table ownership."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS jhoc_state (
                owner TEXT NOT NULL, key TEXT NOT NULL, version INTEGER NOT NULL,
                value TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY(owner, key)
            );
            CREATE TABLE IF NOT EXISTS jhoc_events (
                event_id TEXT PRIMARY KEY, payload TEXT NOT NULL, occurred_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS jhoc_artifacts (
                artifact_id TEXT PRIMARY KEY, owner TEXT NOT NULL, content_type TEXT NOT NULL,
                size INTEGER NOT NULL, sha256 TEXT NOT NULL, data BLOB NOT NULL
            );
            CREATE TABLE IF NOT EXISTS jhoc_artifact_blobs (
                artifact_id TEXT PRIMARY KEY, size INTEGER NOT NULL, sha256 TEXT NOT NULL, data BLOB NOT NULL
            );
            CREATE TABLE IF NOT EXISTS jhoc_artifact_refs (
                artifact_id TEXT NOT NULL, owner TEXT NOT NULL, content_type TEXT NOT NULL,
                PRIMARY KEY(artifact_id, owner),
                FOREIGN KEY(artifact_id) REFERENCES jhoc_artifact_blobs(artifact_id)
            );
            """
        )
        self._connection.execute(
            "INSERT OR IGNORE INTO jhoc_artifact_blobs(artifact_id,size,sha256,data) "
            "SELECT artifact_id,size,sha256,data FROM jhoc_artifacts"
        )
        self._connection.execute(
            "INSERT OR IGNORE INTO jhoc_artifact_refs(artifact_id,owner,content_type) "
            "SELECT artifact_id,owner,content_type FROM jhoc_artifacts"
        )
        self._connection.commit()
        self._lock = RLock()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def state_get(self, owner: str, key: str) -> VersionedValue | None:
        self._require(owner, key)
        with self._lock:
            row = self._connection.execute("SELECT version, value, updated_at FROM jhoc_state WHERE owner=? AND key=?", (owner, key)).fetchone()
        if row is None:
            return None
        return VersionedValue(owner, key, row[0], json.loads(row[1]), datetime.fromisoformat(row[2]))

    def state_put(self, owner: str, key: str, value: Any, *, expected_version: int | None = None) -> VersionedValue:
        self._require(owner, key)
        encoded = _json(value)
        now = datetime.now(timezone.utc)
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                row = self._connection.execute("SELECT version FROM jhoc_state WHERE owner=? AND key=?", (owner, key)).fetchone()
                current_version = row[0] if row else 0
                if expected_version is not None and expected_version != current_version:
                    self._connection.rollback()
                    raise ContractError("state version mismatch", ErrorCode.STALE_STATE)
                new_version = current_version + 1
                self._connection.execute(
                    "INSERT INTO jhoc_state(owner,key,version,value,updated_at) VALUES(?,?,?,?,?) "
                    "ON CONFLICT(owner,key) DO UPDATE SET version=excluded.version,value=excluded.value,updated_at=excluded.updated_at",
                    (owner, key, new_version, encoded, now.isoformat()),
                )
                self._connection.commit()
            except Exception:
                if self._connection.in_transaction:
                    self._connection.rollback()
                raise
        return VersionedValue(owner, key, new_version, deepcopy(value), now)

    def state_delete(self, owner: str, key: str, *, expected_version: int | None = None) -> None:
        self._require(owner, key)
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                row = self._connection.execute("SELECT version FROM jhoc_state WHERE owner=? AND key=?", (owner, key)).fetchone()
                if row is None:
                    self._connection.commit()
                    return
                if expected_version is not None and expected_version != row[0]:
                    raise ContractError("state version mismatch", ErrorCode.STALE_STATE)
                self._connection.execute("DELETE FROM jhoc_state WHERE owner=? AND key=?", (owner, key))
                self._connection.commit()
            except Exception:
                if self._connection.in_transaction:
                    self._connection.rollback()
                raise

    def event_append(self, event_id: str, event: Mapping[str, Any]) -> bool:
        if not event_id.strip() or not isinstance(event, Mapping):
            raise ContractError("event_id and event are required")
        encoded = _json(event)
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                row = self._connection.execute("SELECT payload FROM jhoc_events WHERE event_id=?", (event_id,)).fetchone()
                if row is not None:
                    if row[0] != encoded:
                        raise ContractError("event ID reused with different payload", ErrorCode.IDEMPOTENCY_CONFLICT)
                    self._connection.commit()
                    return False
                self._connection.execute("INSERT INTO jhoc_events(event_id,payload,occurred_at) VALUES(?,?,?)", (event_id, encoded, datetime.now(timezone.utc).isoformat()))
                self._connection.commit()
                return True
            except Exception:
                if self._connection.in_transaction:
                    self._connection.rollback()
                raise

    def event_read(self, event_id: str) -> Mapping[str, Any] | None:
        if not event_id.strip():
            raise ContractError("event_id is required")
        with self._lock:
            row = self._connection.execute("SELECT payload FROM jhoc_events WHERE event_id=?", (event_id,)).fetchone()
        return deepcopy(json.loads(row[0])) if row else None

    def artifact_put(self, owner: str, data: bytes, *, content_type: str) -> ArtifactRef:
        if not owner.strip() or not isinstance(data, bytes) or not content_type.strip():
            raise ContractError("artifact owner and bytes are required")
        digest = hashlib.sha256(data).hexdigest()
        artifact_id = f"sha256:{digest}"
        reference = ArtifactRef(artifact_id, owner, content_type, len(data), digest)
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                self._connection.execute(
                    "INSERT OR IGNORE INTO jhoc_artifact_blobs(artifact_id,size,sha256,data) VALUES(?,?,?,?)",
                    (artifact_id, len(data), digest, data),
                )
                self._connection.execute(
                    "INSERT INTO jhoc_artifact_refs(artifact_id,owner,content_type) VALUES(?,?,?) "
                    "ON CONFLICT(artifact_id,owner) DO UPDATE SET content_type=excluded.content_type",
                    (artifact_id, owner, content_type),
                )
                self._connection.commit()
            except Exception:
                if self._connection.in_transaction:
                    self._connection.rollback()
                raise
        return reference

    def artifact_get(self, reference: ArtifactRef, *, owner: str) -> bytes:
        if owner != reference.owner:
            raise ContractError("artifact owner mismatch", ErrorCode.POLICY_DENIED)
        with self._lock:
            row = self._connection.execute(
                "SELECT b.data FROM jhoc_artifact_blobs b JOIN jhoc_artifact_refs r ON r.artifact_id=b.artifact_id "
                "WHERE b.artifact_id=? AND r.owner=?",
                (reference.artifact_id, owner),
            ).fetchone()
        if row is None:
            raise ContractError("artifact not found")
        return bytes(row[0])

    @staticmethod
    def _require(owner: str, key: str) -> None:
        if not owner.strip() or not key.strip():
            raise ContractError("owner and key are required")


# Imports are placed after SQLiteStore to keep the public storage types canonical.
from .stores import ArtifactRef, VersionedValue  # noqa: E402


class SQLiteStateStore:
    def __init__(self, backend: SQLiteStore) -> None:
        self.backend = backend

    def get(self, owner: str, key: str) -> VersionedValue | None:
        return self.backend.state_get(owner, key)

    def put(self, owner: str, key: str, value: Any, *, expected_version: int | None = None) -> VersionedValue:
        return self.backend.state_put(owner, key, value, expected_version=expected_version)

    def delete(self, owner: str, key: str, *, expected_version: int | None = None) -> None:
        self.backend.state_delete(owner, key, expected_version=expected_version)


class SQLiteEventStore:
    def __init__(self, backend: SQLiteStore) -> None:
        self.backend = backend

    def append(self, event_id: str, event: Mapping[str, Any]) -> bool:
        return self.backend.event_append(event_id, event)

    def read(self, event_id: str) -> Mapping[str, Any] | None:
        return self.backend.event_read(event_id)


class SQLiteArtifactStore:
    def __init__(self, backend: SQLiteStore) -> None:
        self.backend = backend

    def put(self, owner: str, data: bytes, *, content_type: str = "application/octet-stream") -> ArtifactRef:
        return self.backend.artifact_put(owner, data, content_type=content_type)

    def get(self, reference: ArtifactRef, *, owner: str) -> bytes:
        return self.backend.artifact_get(reference, owner=owner)
