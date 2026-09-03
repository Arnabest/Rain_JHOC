"""Offline, fail-closed migration preparation for a reviewed source manifest."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any, Mapping

from .manifest import Disposition, IngestScanner, MigrationManifest


class MigrationStatus(StrEnum):
    MIGRATED = "MIGRATED"
    TRANSFORMED = "TRANSFORMED"
    REFERENCED = "REFERENCED"
    ARCHIVED = "ARCHIVED"
    QUARANTINED = "QUARANTINED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class MigrationItem:
    relative_path: str
    disposition: Disposition
    status: MigrationStatus
    target_type: str | None = None
    target_ref: str | None = None
    prepared_sha256: str | None = None
    semantic_valid: bool = False
    error: str | None = None


@dataclass(frozen=True, slots=True)
class MigrationRun:
    source_hash: str
    manifest_hash: str
    quarantine_root: str
    items: tuple[MigrationItem, ...]

    @property
    def complete(self) -> bool:
        return all(item.status != MigrationStatus.QUARANTINED for item in self.items)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_hash": self.source_hash,
            "manifest_hash": self.manifest_hash,
            "quarantine_root": self.quarantine_root,
            "complete": self.complete,
            "items": [
                {key: value.value if isinstance(value, StrEnum) else value for key, value in asdict(item).items()}
                for item in self.items
            ],
        }


class OfflineMigration:
    """Prepare migration artifacts without importing legacy runtime state.

    Source files are copied one at a time below ``quarantine_root``. JSON
    documents selected for migration must expose ``type``, ``sensitivity``,
    ``source_ref`` and mapping-valued ``content``; semantic type values are
    intentionally whitelisted instead of inferred from arbitrary input.
    """

    _KNOWN_TYPES = {
        "FACT", "RULE_REFERENCE", "PROJECT_KNOWLEDGE", "USER_PREFERENCE",
        "TASK_EXPERIENCE", "ERROR_PATTERN", "OBSERVATION", "HYPOTHESIS",
        "PROCEDURE", "EVIDENCE", "COMMUNITY_CONCLUSION", "MODEL_CAPABILITY", "UserMemory",
        "ProjectMemory", "TaskMemory", "ErrorMemory", "ExperienceMemory",
    }

    def __init__(self, scanner: IngestScanner | None = None) -> None:
        self.scanner = scanner or IngestScanner()

    @staticmethod
    def _safe_source_path(root: Path, relative_path: str) -> Path:
        try:
            root = Path(root).resolve()
            raw = Path(relative_path)
            if raw.is_absolute():
                raise ValueError(f"migration path escapes source root: {relative_path}")
            lexical = root / raw
            relative = lexical.relative_to(root)
            cursor = root
            for part in relative.parts:
                cursor /= part
                if cursor.is_symlink():
                    raise ValueError(f"migration path cannot use symlink: {relative_path}")
            candidate = lexical.resolve()
        except (OSError, RuntimeError) as exc:
            raise ValueError(f"migration path cannot be resolved: {relative_path}") from exc
        if candidate == root or root not in candidate.parents:
            raise ValueError(f"migration path escapes source root: {relative_path}")
        return candidate

    @classmethod
    def _validate_document(cls, path: Path) -> tuple[str, str | None, dict[str, Any] | None]:
        try:
            payload = path.read_bytes()
        except OSError as exc:
            return "", f"invalid JSON document: {exc.__class__.__name__}", None
        return cls._validate_document_bytes(payload)

    @classmethod
    def _validate_document_bytes(cls, payload: bytes) -> tuple[str, str | None, dict[str, Any] | None]:
        try:
            document = json.loads(payload.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            return "", f"invalid JSON document: {exc.__class__.__name__}", None
        if not isinstance(document, Mapping):
            return "", "document must be an object", None
        required = ("type", "sensitivity", "source_ref", "content")
        if any(key not in document for key in required):
            return "", "missing required fields", None
        target_type = str(document["type"])
        if target_type not in cls._KNOWN_TYPES:
            return "", "unsupported target type", None
        if not isinstance(document["content"], Mapping) or not str(document["sensitivity"]).strip() or not str(document["source_ref"]).strip():
            return "", "invalid sensitivity, source_ref or content", None
        normalized = {
            "type": target_type,
            "sensitivity": str(document["sensitivity"]).strip().upper(),
            "source_ref": str(document["source_ref"]).strip(),
            "content": dict(document["content"]),
        }
        return target_type, None, normalized

    def run(self, manifest: MigrationManifest, quarantine_root: str | Path) -> MigrationRun:
        if not manifest.dispositions_complete():
            raise ValueError("migration requires a disposition for every manifest entry")
        if not self.scanner.verify(manifest):
            raise ValueError("source changed after manifest creation")
        source_root = Path(manifest.source_root).resolve()
        quarantine = Path(quarantine_root).resolve()
        quarantine.mkdir(parents=True, exist_ok=True)
        items: list[MigrationItem] = []
        for entry in manifest.entries:
            source = self._safe_source_path(source_root, entry.relative_path)
            if hashlib.sha256(source.read_bytes()).hexdigest() != entry.sha256:
                raise ValueError(f"source hash mismatch: {entry.relative_path}")
            if entry.disposition == Disposition.REJECT:
                items.append(MigrationItem(entry.relative_path, entry.disposition, MigrationStatus.REJECTED))
                continue
            target = self._safe_source_path(quarantine, entry.relative_path) if entry.relative_path else quarantine
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            if entry.disposition in (Disposition.ARCHIVE, Disposition.REFERENCE_ONLY):
                status = MigrationStatus.ARCHIVED if entry.disposition == Disposition.ARCHIVE else MigrationStatus.REFERENCED
                items.append(MigrationItem(entry.relative_path, entry.disposition, status, target_ref=target.relative_to(quarantine).as_posix()))
                continue
            if entry.disposition == Disposition.QUARANTINE:
                items.append(MigrationItem(entry.relative_path, entry.disposition, MigrationStatus.QUARANTINED, target_ref=target.relative_to(quarantine).as_posix(), error="explicit disposition required"))
                continue
            target_type, error, normalized = self._validate_document(target)
            if error:
                items.append(MigrationItem(entry.relative_path, entry.disposition, MigrationStatus.QUARANTINED, error=error))
                continue
            if entry.disposition == Disposition.TRANSFORM and normalized is not None:
                target.write_text(json.dumps(normalized, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
            status = MigrationStatus.MIGRATED if entry.disposition == Disposition.MIGRATE else MigrationStatus.TRANSFORMED
            items.append(MigrationItem(
                entry.relative_path,
                entry.disposition,
                status,
                target_type=target_type,
                target_ref=target.relative_to(quarantine).as_posix(),
                prepared_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
                semantic_valid=True,
            ))
        return MigrationRun(manifest.source_hash, manifest.manifest_hash, str(quarantine), tuple(items))
