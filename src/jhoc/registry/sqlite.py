from __future__ import annotations

import json
import sqlite3
from threading import RLock

from jhoc.contracts import PluginManifest
from jhoc.contracts.errors import ContractError, ErrorCode

from .registry import CapabilityRecord, CapabilityRegistry, VerificationStatus


class SQLiteCapabilityRegistry(CapabilityRegistry):
    """SQLite-backed capability metadata with cross-instance updates."""

    def __init__(self, path: str) -> None:
        super().__init__()
        self._db = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS jhoc_capability_registry ("
            "capability_id TEXT NOT NULL, version TEXT NOT NULL, payload TEXT NOT NULL, "
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

    def register(self, record: CapabilityRecord) -> None:
        payload = _encode(record)
        with self._lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                self._db.execute(
                    "INSERT INTO jhoc_capability_registry(capability_id,version,payload) VALUES(?,?,?)",
                    (record.capability_id, record.version, payload),
                )
                self._db.commit()
            except sqlite3.IntegrityError as error:
                if self._db.in_transaction:
                    self._db.rollback()
                raise ContractError("capability version already registered", ErrorCode.IDEMPOTENCY_CONFLICT) from error
            except Exception:
                if self._db.in_transaction:
                    self._db.rollback()
                raise

    def verify(self, capability_id: str, version: str, *, health: str = "HEALTHY") -> CapabilityRecord:
        return self._set_status(capability_id, version, VerificationStatus.VERIFIED, health)

    def revoke(self, capability_id: str, version: str) -> CapabilityRecord:
        return self._set_status(capability_id, version, VerificationStatus.REVOKED, "REVOKED")

    def get(self, capability_id: str, version: str) -> CapabilityRecord | None:
        with self._lock:
            row = self._db.execute(
                "SELECT payload FROM jhoc_capability_registry WHERE capability_id=? AND version=?",
                (capability_id, version),
            ).fetchone()
        return _decode(row[0]) if row else None

    def _set_status(
        self,
        capability_id: str,
        version: str,
        status: VerificationStatus,
        health: str,
    ) -> CapabilityRecord:
        with self._lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                row = self._db.execute(
                    "SELECT payload FROM jhoc_capability_registry WHERE capability_id=? AND version=?",
                    (capability_id, version),
                ).fetchone()
                if row is None:
                    raise ContractError("capability not found")
                current = _decode(row[0])
                updated = CapabilityRecord(
                    current.capability_id,
                    current.version,
                    current.manifest,
                    current.input_schema_ref,
                    current.output_schema_ref,
                    status,
                    health,
                )
                self._db.execute(
                    "UPDATE jhoc_capability_registry SET payload=? WHERE capability_id=? AND version=?",
                    (_encode(updated), capability_id, version),
                )
                self._db.commit()
                return updated
            except Exception:
                if self._db.in_transaction:
                    self._db.rollback()
                raise


def _encode(record: CapabilityRecord) -> str:
    return json.dumps(
        {
            "capability_id": record.capability_id,
            "version": record.version,
            "manifest": record.manifest.to_dict(),
            "input_schema_ref": record.input_schema_ref,
            "output_schema_ref": record.output_schema_ref,
            "verification_status": record.verification_status.value,
            "health": record.health,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def _decode(payload: str) -> CapabilityRecord:
    value = json.loads(payload)
    manifest_value = value["manifest"]
    manifest = PluginManifest(
        manifest_value["plugin_id"],
        manifest_value["name"],
        manifest_value["version"],
        manifest_value["protocol_version"],
        manifest_value["plugin_type"],
        tuple(manifest_value["capabilities"]),
        tuple(manifest_value["dependencies"]),
        manifest_value["permissions"],
        tuple(manifest_value["side_effects"]),
        manifest_value["resource_requirements"],
        manifest_value["license"],
        manifest_value["verification_status"],
        bool(manifest_value["shelf_eligible"]),
        bool(manifest_value["runtime_selectable"]),
        bool(manifest_value["mutable_by_agent"]),
        manifest_value["schema_version"],
    )
    return CapabilityRecord(
        value["capability_id"],
        value["version"],
        manifest,
        value["input_schema_ref"],
        value["output_schema_ref"],
        value["verification_status"],
        value["health"],
    )
