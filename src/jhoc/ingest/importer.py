"""Explicit P19 adapter that imports reviewed quarantine records into owner stores."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from threading import RLock
from typing import Any, Mapping
from uuid import UUID

from jhoc.trust import IdentityType, TrustStore
from jhoc.storage import StateStore

from .manifest import Disposition
from .migration import MigrationItem, MigrationRun, MigrationStatus, OfflineMigration


@dataclass(frozen=True, slots=True)
class ImportedRecord:
    relative_path: str
    target_store: str
    record_id: str
    approved_by: str


@dataclass(frozen=True, slots=True)
class MigrationApproval:
    relative_path: str
    manifest_hash: str
    prepared_sha256: str
    target_type: str
    target_store: str
    approved_by: UUID
    session_id: str
    approved_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.relative_path,
                self.manifest_hash,
                self.prepared_sha256,
                self.target_type,
                self.target_store,
                self.session_id,
            )
        ):
            raise ValueError("migration approval fields are required")
        if self.target_store not in {"atlas", "memory"}:
            raise ValueError("migration approval target store is invalid")
        if len(self.prepared_sha256) != 64 or any(char not in "0123456789abcdef" for char in self.prepared_sha256):
            raise ValueError("migration approval requires a lowercase SHA-256 digest")
        if self.approved_at.tzinfo is None or self.approved_at.utcoffset() is None:
            raise ValueError("migration approval time must be timezone-aware")


class ApprovedMigrationImporter:
    """Apply per-item operator approvals through Atlas and Memory owner APIs."""

    PERMISSION = "migration.import"
    LEDGER_OWNER = "migration_import"

    def __init__(self, trust: TrustStore, state_store: StateStore) -> None:
        self.trust = trust
        self.state_store = state_store
        self._lock = RLock()

    def import_approved(
        self,
        run: MigrationRun,
        approvals: Mapping[str, MigrationApproval],
        *,
        atlas: Any | None = None,
        memory: Any | None = None,
    ) -> tuple[ImportedRecord, ...]:
        if not run.complete:
            raise ValueError("cannot import an incomplete migration run")
        pending = [item for item in run.items if item.disposition in {Disposition.MIGRATE, Disposition.TRANSFORM}]
        missing = [
            item.relative_path
            for item in pending
            if not isinstance(approvals.get(item.relative_path), MigrationApproval)
        ]
        if missing:
            raise ValueError(f"explicit approval required: {sorted(missing)}")
        if any(self._target_store(item.target_type or "") == "memory" for item in pending) and memory is None:
            raise ValueError("memory target is required for memory records")
        if any(self._target_store(item.target_type or "") == "atlas" for item in pending) and atlas is None:
            raise ValueError("atlas target is required for knowledge records")
        prepared: list[tuple[MigrationItem, dict[str, Any], str, str, str]] = []
        quarantine = Path(run.quarantine_root).resolve()
        for item in pending:
            if (
                item.status not in {MigrationStatus.MIGRATED, MigrationStatus.TRANSFORMED}
                or not item.target_ref
                or not item.target_type
                or not item.prepared_sha256
            ):
                raise ValueError(f"item is not importable: {item.relative_path}")
            approval = approvals[item.relative_path]
            target_store = self._target_store(item.target_type)
            expected_approval = (
                item.relative_path,
                run.manifest_hash,
                item.prepared_sha256,
                item.target_type,
                target_store,
            )
            actual_approval = (
                approval.relative_path,
                approval.manifest_hash,
                approval.prepared_sha256,
                approval.target_type,
                approval.target_store,
            )
            if actual_approval != expected_approval:
                raise ValueError(f"approval does not match prepared item: {item.relative_path}")
            identity = self.trust.get(approval.approved_by)
            if (
                identity is None
                or identity.identity_type != IdentityType.USER
                or not self.trust.authorize(
                    approval.approved_by,
                    self.PERMISSION,
                    session_id=approval.session_id,
                )
            ):
                raise ValueError(f"authorized user approval required: {item.relative_path}")
            path = OfflineMigration._safe_source_path(quarantine, item.target_ref)
            payload = path.read_bytes()
            if hashlib.sha256(payload).hexdigest() != item.prepared_sha256:
                raise ValueError(f"prepared content hash mismatch: {item.relative_path}")
            target_type, error, document = OfflineMigration._validate_document_bytes(payload)
            if error or document is None or target_type != item.target_type:
                raise ValueError(f"quarantine validation failed: {item.relative_path}")
            record_id = "migration:" + hashlib.sha256(
                f"{run.manifest_hash}:{item.relative_path}:{item.prepared_sha256}".encode()
            ).hexdigest()[:32]
            prepared.append((item, document, record_id, identity.subject, target_store))
        imported: list[ImportedRecord] = []
        for item, document, record_id, approved_by, target_store in prepared:
            if target_store == "memory":
                from jhoc.memory_store import MemoryRecord

                record = MemoryRecord(
                    document["content"],
                    item.target_type,
                    document["source_ref"],
                    document["sensitivity"],
                    record_id,
                )
                self._commit_item(
                    run,
                    item,
                    record_id,
                    approved_by,
                    target_store,
                    target=memory,
                    record=record,
                    write=lambda: memory.write(record, approved=True),
                )
            else:
                from jhoc.atlas import KnowledgeRecord

                record = KnowledgeRecord(
                    document["content"],
                    item.target_type,
                    document["source_ref"],
                    document["sensitivity"],
                    record_id=record_id,
                )
                self._commit_item(
                    run,
                    item,
                    record_id,
                    approved_by,
                    target_store,
                    target=atlas,
                    record=record,
                    write=lambda: atlas.ingest(record),
                )
            imported.append(ImportedRecord(item.relative_path, target_store, record_id, approved_by))
        return tuple(imported)

    def _commit_item(
        self,
        run: MigrationRun,
        item: MigrationItem,
        record_id: str,
        approved_by: str,
        target_store: str,
        *,
        target: Any,
        record: Any,
        write: Any,
    ) -> None:
        key = f"{run.manifest_hash}:{item.relative_path}"
        expected = {
            "manifest_hash": run.manifest_hash,
            "relative_path": item.relative_path,
            "prepared_sha256": item.prepared_sha256,
            "target_store": target_store,
            "record_id": record_id,
            "approved_by": approved_by,
        }
        with self._lock:
            ledger = self.state_store.get(self.LEDGER_OWNER, key)
            if ledger is None:
                prepared = dict(expected, status="PREPARED")
                ledger = self.state_store.put(
                    self.LEDGER_OWNER, key, prepared, expected_version=0
                )
            else:
                actual = {name: ledger.value.get(name) for name in expected}
                if actual != expected:
                    raise ValueError(f"migration import ledger conflict: {item.relative_path}")
                if ledger.value.get("status") not in {"PREPARED", "COMPLETED"}:
                    raise ValueError(f"migration import ledger state is invalid: {item.relative_path}")
            existing = target.get(record_id)
            if existing is not None and existing != record:
                raise ValueError(f"target record conflict: {item.relative_path}")
            if ledger.value.get("status") == "COMPLETED":
                if existing is None:
                    raise ValueError(f"completed import target is missing: {item.relative_path}")
                return
            if existing is None:
                write()
            self.state_store.put(
                self.LEDGER_OWNER,
                key,
                dict(expected, status="COMPLETED"),
                expected_version=ledger.version,
            )

    @staticmethod
    def _target_store(target_type: str) -> str:
        return (
            "memory"
            if target_type in {"UserMemory", "ProjectMemory", "TaskMemory", "ErrorMemory", "ExperienceMemory"}
            else "atlas"
        )
