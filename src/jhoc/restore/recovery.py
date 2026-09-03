from __future__ import annotations

from dataclasses import dataclass
from contextlib import closing
from enum import StrEnum
import hashlib
from pathlib import Path
import sqlite3

from jhoc.config import RuntimeMode


class RecoveryStage(StrEnum):
    IDENTITY = "IDENTITY"
    POLICY = "POLICY"
    STORAGE = "STORAGE"
    CAPABILITIES = "CAPABILITIES"
    MEMORY_GRAPH = "MEMORY_GRAPH"
    EVIDENCE_AUDIT = "EVIDENCE_AUDIT"
    BACKGROUND = "BACKGROUND"


@dataclass(frozen=True, slots=True)
class RestoreManifest:
    snapshot_id: str
    stages: tuple[RecoveryStage, ...]


@dataclass(frozen=True, slots=True)
class DatabaseSnapshot:
    snapshot_id: str
    path: str
    sha256: str
    size: int


@dataclass(frozen=True, slots=True)
class RecoveryAudit:
    operation_id: str
    operation: str
    status: str
    snapshot_id: str | None
    mode: str | None
    stages: tuple[RecoveryStage, ...] = ()
    error: str | None = None


class RecoveryManager:
    ORDER = tuple(RecoveryStage)

    def restore(self, manifest: RestoreManifest, *, mode: RuntimeMode) -> tuple[RecoveryStage, ...]:
        operation_id = f"restore:{manifest.snapshot_id}:{id(manifest)}"
        if mode == RuntimeMode.EMERGENCY_SAFE_MODE:
            stages = tuple(stage for stage in self.ORDER if stage in manifest.stages and stage in {RecoveryStage.IDENTITY, RecoveryStage.POLICY, RecoveryStage.STORAGE})
        else:
            stages = tuple(stage for stage in self.ORDER if stage in manifest.stages)
        self._record_audit(RecoveryAudit(operation_id, "restore", "COMPLETED", manifest.snapshot_id, mode.value, stages))
        return stages

    def __init__(self) -> None:
        self._audits: list[RecoveryAudit] = []

    def snapshot_database(self, source: str | Path, destination_dir: str | Path, *, snapshot_id: str) -> DatabaseSnapshot:
        source_path = Path(source).resolve()
        destination = Path(destination_dir).resolve()
        if not snapshot_id.strip() or not source_path.is_file():
            raise ValueError("snapshot_id and source database are required")
        destination.mkdir(parents=True, exist_ok=True)
        snapshot_path = destination / f"{snapshot_id}.sqlite3"
        if snapshot_path.exists():
            raise FileExistsError(f"snapshot already exists: {snapshot_path}")
        try:
            with closing(sqlite3.connect(source_path)) as source_db, closing(sqlite3.connect(snapshot_path)) as snapshot_db:
                source_db.backup(snapshot_db)
        except Exception as exc:
            self._record_audit(RecoveryAudit(f"snapshot:{snapshot_id}", "snapshot", "FAILED", snapshot_id, None, error=exc.__class__.__name__))
            raise
        digest = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
        self._record_audit(RecoveryAudit(f"snapshot:{snapshot_id}", "snapshot", "COMPLETED", snapshot_id, None))
        return DatabaseSnapshot(snapshot_id, str(snapshot_path), digest, snapshot_path.stat().st_size)

    def verify_snapshot(self, snapshot: DatabaseSnapshot) -> bool:
        path = Path(snapshot.path)
        if not path.is_file() or path.stat().st_size != snapshot.size:
            return False
        return hashlib.sha256(path.read_bytes()).hexdigest() == snapshot.sha256

    def restore_database(self, snapshot: DatabaseSnapshot, target: str | Path) -> Path:
        operation_id = f"restore-db:{snapshot.snapshot_id}:{Path(target).name}"
        try:
            if not self.verify_snapshot(snapshot):
                raise ValueError("snapshot integrity verification failed")
            target_path = Path(target).resolve()
            if target_path.exists():
                raise FileExistsError(f"restore target already exists: {target_path}")
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(snapshot.path)) as snapshot_db, closing(sqlite3.connect(target_path)) as target_db:
                snapshot_db.backup(target_db)
        except Exception as exc:
            self._record_audit(RecoveryAudit(operation_id, "restore_database", "FAILED", snapshot.snapshot_id, None, error=exc.__class__.__name__))
            raise
        self._record_audit(RecoveryAudit(operation_id, "restore_database", "COMPLETED", snapshot.snapshot_id, None))
        return target_path

    def audit_records(self) -> tuple[RecoveryAudit, ...]:
        return tuple(self._audits)

    def _record_audit(self, audit: RecoveryAudit) -> None:
        self._audits.append(audit)
