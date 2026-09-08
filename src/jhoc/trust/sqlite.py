from __future__ import annotations

from datetime import datetime
import json
import sqlite3
from typing import Any, Callable, TypeVar
from uuid import UUID

from jhoc.contracts.errors import ContractError, ErrorCode

from .identity import (
    Delegation,
    Identity,
    IdentityType,
    KeyMetadata,
    KeyStatus,
    PermissionSet,
    Session,
    TrustEvent,
    TrustStore,
)


_T = TypeVar("_T")
_Snapshot = tuple[
    dict[UUID, Identity],
    dict[str, KeyMetadata],
    dict[str, Session],
    dict[str, Delegation],
    list[TrustEvent],
]


class SQLiteTrustStore(TrustStore):
    """Durable non-secret trust metadata with optimistic writer fencing."""

    def __init__(self, path: str) -> None:
        super().__init__()
        self._db = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self._closed = False
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS jhoc_trust_meta (
                singleton INTEGER PRIMARY KEY CHECK(singleton = 1), revision INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS jhoc_trust_identity (
                identity_id TEXT PRIMARY KEY, subject TEXT NOT NULL, identity_type TEXT NOT NULL,
                permissions TEXT NOT NULL, active INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS jhoc_trust_key (
                key_id TEXT PRIMARY KEY, identity_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
                version INTEGER NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
                FOREIGN KEY(identity_id) REFERENCES jhoc_trust_identity(identity_id)
            );
            CREATE TABLE IF NOT EXISTS jhoc_trust_session (
                session_id TEXT PRIMARY KEY, identity_id TEXT NOT NULL, key_id TEXT NOT NULL,
                expires_at TEXT NOT NULL, active INTEGER NOT NULL,
                FOREIGN KEY(identity_id) REFERENCES jhoc_trust_identity(identity_id),
                FOREIGN KEY(key_id) REFERENCES jhoc_trust_key(key_id)
            );
            CREATE TABLE IF NOT EXISTS jhoc_trust_delegation (
                delegation_id TEXT PRIMARY KEY, delegator_id TEXT NOT NULL, delegatee_id TEXT NOT NULL,
                permissions TEXT NOT NULL, expires_at TEXT NOT NULL, active INTEGER NOT NULL,
                FOREIGN KEY(delegator_id) REFERENCES jhoc_trust_identity(identity_id),
                FOREIGN KEY(delegatee_id) REFERENCES jhoc_trust_identity(identity_id)
            );
            CREATE TABLE IF NOT EXISTS jhoc_trust_event (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT, event TEXT NOT NULL,
                identity_id TEXT, session_id TEXT, occurred_at TEXT NOT NULL
            );
            """
        )
        self._db.execute("INSERT OR IGNORE INTO jhoc_trust_meta(singleton,revision) VALUES(1,0)")
        self._db.commit()
        self._load()

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._db.close()
                self._closed = True

    def register(self, identity: Identity) -> Identity:
        return self._mutate(lambda: super(SQLiteTrustStore, self).register(identity))

    def revoke(self, identity_id: UUID | str) -> None:
        self._mutate(lambda: super(SQLiteTrustStore, self).revoke(identity_id))

    def issue_key(self, identity_id: UUID | str, fingerprint: str, *, key_id: str | None = None) -> KeyMetadata:
        return self._mutate(lambda: super(SQLiteTrustStore, self).issue_key(identity_id, fingerprint, key_id=key_id))

    def rotate_key(self, identity_id: UUID | str, fingerprint: str, *, key_id: str | None = None) -> KeyMetadata:
        return self._mutate(lambda: super(SQLiteTrustStore, self).rotate_key(identity_id, fingerprint, key_id=key_id))

    def revoke_key(self, key_id: str) -> None:
        self._mutate(lambda: super(SQLiteTrustStore, self).revoke_key(key_id))

    def authenticate(self, identity_id: UUID | str, key_id: str, fingerprint: str) -> bool:
        self._refresh_if_stale()
        return self._mutate(lambda: super(SQLiteTrustStore, self).authenticate(identity_id, key_id, fingerprint))

    def open_session(
        self,
        identity_id: UUID | str,
        key_id: str,
        fingerprint: str,
        *,
        ttl_seconds: float = 3600.0,
    ) -> Session:
        self._refresh_if_stale()
        return self._mutate(
            lambda: super(SQLiteTrustStore, self).open_session(
                identity_id, key_id, fingerprint, ttl_seconds=ttl_seconds
            ),
            persist_on_error=True,
        )

    def close_session(self, session_id: str) -> None:
        self._mutate(lambda: super(SQLiteTrustStore, self).close_session(session_id))

    def delegate(
        self,
        delegator_id: UUID | str,
        delegatee_id: UUID | str,
        permissions: frozenset[str],
        *,
        ttl_seconds: float = 3600.0,
    ) -> Delegation:
        return self._mutate(
            lambda: super(SQLiteTrustStore, self).delegate(
                delegator_id, delegatee_id, permissions, ttl_seconds=ttl_seconds
            )
        )

    def authorize(self, identity_id: UUID | str, permission: str, *, session_id: str | None = None) -> bool:
        self._refresh_if_stale()
        return self._mutate(
            lambda: super(SQLiteTrustStore, self).authorize(identity_id, permission, session_id=session_id)
        )

    def get(self, identity_id: UUID | str) -> Identity | None:
        self._refresh_if_stale()
        return super().get(identity_id)

    def key(self, key_id: str) -> KeyMetadata | None:
        self._refresh_if_stale()
        return super().key(key_id)

    def events(self) -> tuple[TrustEvent, ...]:
        self._refresh_if_stale()
        return super().events()

    def _snapshot(self) -> _Snapshot:
        return (
            dict(self._identities),
            dict(self._keys),
            dict(self._sessions),
            dict(self._delegations),
            list(self._events),
        )

    def _restore(self, snapshot: _Snapshot) -> None:
        self._identities, self._keys, self._sessions, self._delegations, self._events = snapshot

    def _mutate(self, operation: Callable[[], _T], *, persist_on_error: bool = False) -> _T:
        with self._lock:
            if self._closed:
                raise ContractError("trust store is closed", ErrorCode.INVALID_CONTRACT)
            snapshot = self._snapshot()
            try:
                result = operation()
                if self._snapshot() != snapshot:
                    self._persist()
                return result
            except Exception as error:
                if persist_on_error and self._snapshot() != snapshot:
                    try:
                        self._persist()
                    except Exception as persist_error:
                        self._restore(snapshot)
                        self._reload_after_stale(persist_error)
                        raise
                else:
                    self._restore(snapshot)
                    self._reload_after_stale(error)
                raise

    def _reload_after_stale(self, error: Exception) -> None:
        if isinstance(error, ContractError) and error.code == ErrorCode.STALE_STATE:
            self._load()

    def _load(self) -> None:
        with self._lock:
            rows = None
            revision = 0
            for _ in range(5):
                before = int(
                    self._db.execute(
                        "SELECT revision FROM jhoc_trust_meta WHERE singleton=1"
                    ).fetchone()[0]
                )
                candidate = (
                    self._db.execute(
                        "SELECT identity_id,subject,identity_type,permissions,active FROM jhoc_trust_identity"
                    ).fetchall(),
                    self._db.execute(
                        "SELECT key_id,identity_id,fingerprint,version,status,created_at FROM jhoc_trust_key"
                    ).fetchall(),
                    self._db.execute(
                        "SELECT session_id,identity_id,key_id,expires_at,active FROM jhoc_trust_session"
                    ).fetchall(),
                    self._db.execute(
                        "SELECT delegation_id,delegator_id,delegatee_id,permissions,expires_at,active "
                        "FROM jhoc_trust_delegation"
                    ).fetchall(),
                    self._db.execute(
                        "SELECT event,identity_id,session_id,occurred_at "
                        "FROM jhoc_trust_event ORDER BY sequence"
                    ).fetchall(),
                )
                after = int(
                    self._db.execute(
                        "SELECT revision FROM jhoc_trust_meta WHERE singleton=1"
                    ).fetchone()[0]
                )
                if before == after:
                    rows = candidate
                    revision = after
                    break
            if rows is None:
                raise ContractError("trust metadata changed continuously during refresh", ErrorCode.STALE_STATE)

            identities: dict[UUID, Identity] = {}
            keys: dict[str, KeyMetadata] = {}
            sessions: dict[str, Session] = {}
            delegations: dict[str, Delegation] = {}
            events: list[TrustEvent] = []
            for row in rows[0]:
                identity = Identity(
                    row[1], IdentityType(row[2]), PermissionSet(frozenset(json.loads(row[3]))), UUID(row[0]), bool(row[4])
                )
                identities[identity.identity_id] = identity
            for row in rows[1]:
                key = KeyMetadata(row[0], UUID(row[1]), row[2], int(row[3]), KeyStatus(row[4]), datetime.fromisoformat(row[5]))
                keys[key.key_id] = key
            for row in rows[2]:
                session = Session(row[0], UUID(row[1]), row[2], datetime.fromisoformat(row[3]), bool(row[4]))
                sessions[session.session_id] = session
            for row in rows[3]:
                delegation = Delegation(
                    row[0], UUID(row[1]), UUID(row[2]), frozenset(json.loads(row[3])), datetime.fromisoformat(row[4]), bool(row[5])
                )
                delegations[delegation.delegation_id] = delegation
            for row in rows[4]:
                events.append(
                    TrustEvent(row[0], UUID(row[1]) if row[1] else None, row[2], datetime.fromisoformat(row[3]))
                )
            self._identities = identities
            self._keys = keys
            self._sessions = sessions
            self._delegations = delegations
            self._events = events
            self._revision = revision

    def _refresh_if_stale(self) -> None:
        with self._lock:
            if self._closed:
                raise ContractError("trust store is closed", ErrorCode.INVALID_CONTRACT)
            current = int(
                self._db.execute("SELECT revision FROM jhoc_trust_meta WHERE singleton=1").fetchone()[0]
            )
            if current != self._revision:
                self._load()

    def _persist(self) -> None:
        try:
            self._db.execute("BEGIN IMMEDIATE")
            current = int(
                self._db.execute("SELECT revision FROM jhoc_trust_meta WHERE singleton=1").fetchone()[0]
            )
            if current != self._revision:
                raise ContractError("trust metadata changed by another writer", ErrorCode.STALE_STATE)
            for table in (
                "jhoc_trust_event",
                "jhoc_trust_session",
                "jhoc_trust_delegation",
                "jhoc_trust_key",
                "jhoc_trust_identity",
            ):
                self._db.execute(f"DELETE FROM {table}")
            self._db.executemany(
                "INSERT INTO jhoc_trust_identity VALUES(?,?,?,?,?)",
                [
                    (str(item.identity_id), item.subject, item.identity_type.value, _json(sorted(item.permissions.allowed)), int(item.active))
                    for item in self._identities.values()
                ],
            )
            self._db.executemany(
                "INSERT INTO jhoc_trust_key VALUES(?,?,?,?,?,?)",
                [
                    (item.key_id, str(item.identity_id), item.fingerprint, item.version, item.status.value, item.created_at.isoformat())
                    for item in self._keys.values()
                ],
            )
            self._db.executemany(
                "INSERT INTO jhoc_trust_session VALUES(?,?,?,?,?)",
                [
                    (item.session_id, str(item.identity_id), item.key_id, item.expires_at.isoformat(), int(item.active))
                    for item in self._sessions.values()
                ],
            )
            self._db.executemany(
                "INSERT INTO jhoc_trust_delegation VALUES(?,?,?,?,?,?)",
                [
                    (
                        item.delegation_id,
                        str(item.delegator_id),
                        str(item.delegatee_id),
                        _json(sorted(item.permissions)),
                        item.expires_at.isoformat(),
                        int(item.active),
                    )
                    for item in self._delegations.values()
                ],
            )
            self._db.executemany(
                "INSERT INTO jhoc_trust_event(event,identity_id,session_id,occurred_at) VALUES(?,?,?,?)",
                [
                    (
                        item.event,
                        str(item.identity_id) if item.identity_id else None,
                        item.session_id,
                        item.occurred_at.isoformat(),
                    )
                    for item in self._events
                ],
            )
            new_revision = self._revision + 1
            self._db.execute("UPDATE jhoc_trust_meta SET revision=? WHERE singleton=1", (new_revision,))
            self._db.commit()
            self._revision = new_revision
        except Exception:
            if self._db.in_transaction:
                self._db.rollback()
            raise


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
