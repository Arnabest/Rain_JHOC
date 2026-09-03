from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from threading import RLock
from uuid import UUID, uuid4

from jhoc.contracts.errors import ContractError, ErrorCode


class IdentityType(StrEnum):
    USER = "User"
    AGENT = "Agent"
    MODEL = "Model"
    PLUGIN = "Plugin"
    WORKER = "Worker"
    SERVICE = "Service"


class KeyStatus(StrEnum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


@dataclass(frozen=True, slots=True)
class PermissionSet:
    """Explicit allow-list; an empty set is intentional default deny."""

    allowed: frozenset[str] = frozenset()

    def allows(self, permission: str) -> bool:
        return permission in self.allowed


@dataclass(frozen=True, slots=True)
class Identity:
    subject: str
    identity_type: IdentityType
    permissions: PermissionSet = field(default_factory=PermissionSet)
    identity_id: UUID = field(default_factory=uuid4)
    active: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "identity_type", IdentityType(self.identity_type))
        if not self.subject.strip():
            raise ContractError("identity subject is required")
        if not isinstance(self.identity_id, UUID):
            try:
                object.__setattr__(self, "identity_id", UUID(str(self.identity_id)))
            except (ValueError, TypeError) as exc:
                raise ContractError("identity_id must be a UUID") from exc


@dataclass(frozen=True, slots=True)
class KeyMetadata:
    """Non-secret key metadata; the key material never enters JHOC state."""

    key_id: str
    identity_id: UUID
    fingerprint: str
    version: int = 1
    status: KeyStatus = KeyStatus.ACTIVE
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", KeyStatus(self.status))
        if not isinstance(self.identity_id, UUID):
            try:
                object.__setattr__(self, "identity_id", UUID(str(self.identity_id)))
            except (ValueError, TypeError) as exc:
                raise ContractError("key identity_id must be a UUID") from exc
        if not self.key_id.strip() or not self.fingerprint.strip() or self.version < 1:
            raise ContractError("key metadata is invalid")


@dataclass(frozen=True, slots=True)
class Session:
    """An identity-bound, expiring session; it carries no credential material."""

    session_id: str
    identity_id: UUID
    key_id: str
    expires_at: datetime
    active: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.identity_id, UUID):
            try:
                object.__setattr__(self, "identity_id", UUID(str(self.identity_id)))
            except (ValueError, TypeError) as exc:
                raise ContractError("session identity_id must be a UUID") from exc
        if not self.session_id.strip() or not self.key_id.strip():
            raise ContractError("session identity and key are required")


@dataclass(frozen=True, slots=True)
class Delegation:
    delegation_id: str
    delegator_id: UUID
    delegatee_id: UUID
    permissions: frozenset[str]
    expires_at: datetime
    active: bool = True

    def __post_init__(self) -> None:
        for field_name in ("delegator_id", "delegatee_id"):
            value = getattr(self, field_name)
            if not isinstance(value, UUID):
                try:
                    object.__setattr__(self, field_name, UUID(str(value)))
                except (ValueError, TypeError) as exc:
                    raise ContractError(f"delegation {field_name} must be a UUID") from exc
        if not self.delegation_id.strip() or not self.permissions or any(not permission.strip() for permission in self.permissions):
            raise ContractError("delegation metadata is invalid")


@dataclass(frozen=True, slots=True)
class TrustEvent:
    event: str
    identity_id: UUID | None
    session_id: str | None
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class TrustStore:
    """Process-local trust registry; only key fingerprints and session metadata are stored."""

    def __init__(self) -> None:
        self._identities: dict[UUID, Identity] = {}
        self._keys: dict[str, KeyMetadata] = {}
        self._sessions: dict[str, Session] = {}
        self._delegations: dict[str, Delegation] = {}
        self._events: list[TrustEvent] = []
        self._lock = RLock()

    def register(self, identity: Identity) -> Identity:
        with self._lock:
            if identity.identity_id in self._identities:
                raise ContractError("identity already registered", ErrorCode.INVALID_CONTRACT)
            self._identities[identity.identity_id] = identity
            return identity

    def revoke(self, identity_id: UUID | str) -> None:
        with self._lock:
            key = self._identity_key(identity_id)
            identity = self._identities.get(key)
            if identity is None:
                raise ContractError("identity not found", ErrorCode.INVALID_CONTRACT)
            self._identities[identity.identity_id] = Identity(
                subject=identity.subject,
                identity_type=identity.identity_type,
                permissions=identity.permissions,
                identity_id=identity.identity_id,
                active=False,
            )
            for key_id, metadata in tuple(self._keys.items()):
                if metadata.identity_id == key:
                    self._keys[key_id] = replace(metadata, status=KeyStatus.REVOKED)
            for session_id, session in tuple(self._sessions.items()):
                if session.identity_id == key:
                    self._sessions[session_id] = replace(session, active=False)
            for delegation_id, delegation in tuple(self._delegations.items()):
                if delegation.delegator_id == key or delegation.delegatee_id == key:
                    self._delegations[delegation_id] = replace(delegation, active=False)

    def get(self, identity_id: UUID | str) -> Identity | None:
        key = self._identity_key(identity_id)
        with self._lock:
            return self._identities.get(key)

    def issue_key(self, identity_id: UUID | str, fingerprint: str, *, key_id: str | None = None) -> KeyMetadata:
        with self._lock:
            identity_key = self._identity_key(identity_id)
            identity = self._identities.get(identity_key)
            if identity is None or not identity.active:
                raise ContractError("active identity is required for key issuance", ErrorCode.POLICY_DENIED)
            metadata = KeyMetadata(key_id or f"key:{uuid4()}", identity_key, fingerprint)
            if metadata.key_id in self._keys:
                raise ContractError("key already exists", ErrorCode.IDEMPOTENCY_CONFLICT)
            self._keys[metadata.key_id] = metadata
            return metadata

    def rotate_key(self, identity_id: UUID | str, fingerprint: str, *, key_id: str | None = None) -> KeyMetadata:
        with self._lock:
            identity_key = self._identity_key(identity_id)
            identity = self._identities.get(identity_key)
            if identity is None or not identity.active:
                raise ContractError("active identity is required for key rotation", ErrorCode.POLICY_DENIED)
            new_key_id = key_id or f"key:{uuid4()}"
            if new_key_id in self._keys:
                raise ContractError("key already exists", ErrorCode.IDEMPOTENCY_CONFLICT)
            active = [metadata for metadata in self._keys.values() if metadata.identity_id == identity_key and metadata.status == KeyStatus.ACTIVE]
            for metadata in active:
                self._revoke_key_unlocked(metadata.key_id)
            version = max((metadata.version for metadata in self._keys.values() if metadata.identity_id == identity_key), default=0) + 1
            metadata = KeyMetadata(new_key_id, identity_key, fingerprint, version=version)
            self._keys[metadata.key_id] = metadata
            return metadata

    def revoke_key(self, key_id: str) -> None:
        with self._lock:
            self._revoke_key_unlocked(key_id)

    def authenticate(self, identity_id: UUID | str, key_id: str, fingerprint: str) -> bool:
        with self._lock:
            identity_key = self._identity_key(identity_id)
            return self._authenticate_unlocked(identity_key, key_id, fingerprint)

    def open_session(self, identity_id: UUID | str, key_id: str, fingerprint: str, *, ttl_seconds: float = 3600.0) -> Session:
        if ttl_seconds <= 0:
            raise ContractError("session TTL must be positive")
        with self._lock:
            identity_key = self._identity_key(identity_id)
            if not self._authenticate_unlocked(identity_key, key_id, fingerprint):
                raise ContractError("authentication failed", ErrorCode.POLICY_DENIED)
            session = Session(f"session:{uuid4()}", identity_key, key_id, datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds))
            self._sessions[session.session_id] = session
            return session

    def close_session(self, session_id: str) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise ContractError("session not found", ErrorCode.INVALID_CONTRACT)
            self._sessions[session_id] = replace(session, active=False)

    def delegate(self, delegator_id: UUID | str, delegatee_id: UUID | str, permissions: frozenset[str], *, ttl_seconds: float = 3600.0) -> Delegation:
        if ttl_seconds <= 0 or not permissions:
            raise ContractError("delegation TTL and permissions are required")
        with self._lock:
            delegator_key = self._identity_key(delegator_id)
            delegatee_key = self._identity_key(delegatee_id)
            delegator = self._identities.get(delegator_key)
            delegatee = self._identities.get(delegatee_key)
            if not delegator or not delegator.active or not delegatee or not delegatee.active:
                raise ContractError("active identities are required for delegation", ErrorCode.POLICY_DENIED)
            if any(not delegator.permissions.allows(permission) for permission in permissions):
                raise ContractError("delegator cannot grant an unheld permission", ErrorCode.POLICY_DENIED)
            delegation = Delegation(f"delegation:{uuid4()}", delegator_key, delegatee_key, frozenset(permissions), datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds))
            self._delegations[delegation.delegation_id] = delegation
            return delegation

    def authorize(self, identity_id: UUID | str, permission: str, *, session_id: str | None = None) -> bool:
        with self._lock:
            identity_key = self._identity_key(identity_id)
            identity = self._identities.get(identity_key)
            if not identity or not identity.active or not permission.strip():
                return False
            if session_id is not None:
                session = self._sessions.get(session_id)
                if session is None or not session.active or session.identity_id != identity_key:
                    self._events.append(TrustEvent("IMPERSONATION_OR_SESSION_DENIED", identity_key, session_id))
                    return False
                if session.expires_at <= datetime.now(timezone.utc):
                    self._sessions[session_id] = replace(session, active=False)
                    self._events.append(TrustEvent("SESSION_EXPIRED", identity_key, session_id))
                    return False
            if identity.permissions.allows(permission):
                return True
            now = datetime.now(timezone.utc)
            return any(
                item.active and item.delegatee_id == identity_key and item.expires_at > now and permission in item.permissions
                for item in self._delegations.values()
            )

    def key(self, key_id: str) -> KeyMetadata | None:
        with self._lock:
            return self._keys.get(key_id)

    def events(self) -> tuple[TrustEvent, ...]:
        with self._lock:
            return tuple(self._events)

    @staticmethod
    def _identity_key(identity_id: UUID | str) -> UUID:
        try:
            return identity_id if isinstance(identity_id, UUID) else UUID(str(identity_id))
        except (ValueError, TypeError) as exc:
            raise ContractError("identity_id must be a UUID") from exc

    def _revoke_key_unlocked(self, key_id: str) -> None:
        metadata = self._keys.get(key_id)
        if metadata is None:
            raise ContractError("key not found", ErrorCode.INVALID_CONTRACT)
        self._keys[key_id] = replace(metadata, status=KeyStatus.REVOKED)
        for session_id, session in tuple(self._sessions.items()):
            if session.key_id == key_id:
                self._sessions[session_id] = replace(session, active=False)

    def _authenticate_unlocked(self, identity_id: UUID, key_id: str, fingerprint: str) -> bool:
        metadata = self._keys.get(key_id)
        valid = bool(
            self._identities.get(identity_id)
            and self._identities[identity_id].active
            and metadata
            and metadata.identity_id == identity_id
            and metadata.status == KeyStatus.ACTIVE
            and metadata.fingerprint == fingerprint
        )
        if not valid:
            self._events.append(TrustEvent("AUTHENTICATION_DENIED", identity_id, None))
        return valid
