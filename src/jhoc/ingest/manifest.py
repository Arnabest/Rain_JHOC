from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from pathlib import Path


class Disposition(StrEnum):
    MIGRATE = "MIGRATE"
    TRANSFORM = "TRANSFORM"
    REFERENCE_ONLY = "REFERENCE_ONLY"
    ARCHIVE = "ARCHIVE"
    QUARANTINE = "QUARANTINE"
    REJECT = "REJECT"
    DUPLICATE = "DUPLICATE"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True, slots=True)
class MigrationEntry:
    relative_path: str
    sha256: str
    size: int
    disposition: Disposition = Disposition.QUARANTINE


@dataclass(frozen=True, slots=True)
class MigrationManifest:
    source_root: str
    entries: tuple[MigrationEntry, ...]
    source_version: str = "1"

    @property
    def source_hash(self) -> str:
        payload = {
            "source_root": self.source_root,
            "source_version": self.source_version,
            "entries": [
                {"relative_path": entry.relative_path, "sha256": entry.sha256, "size": entry.size}
                for entry in self.entries
            ],
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    @property
    def manifest_hash(self) -> str:
        payload = {
            "source_hash": self.source_hash,
            "entries": [{"relative_path": entry.relative_path, "disposition": entry.disposition.value} for entry in self.entries],
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def with_dispositions(self, dispositions: dict[str, Disposition]) -> "MigrationManifest":
        """Return a reviewed manifest with explicit disposition per listed source."""
        known = {entry.relative_path for entry in self.entries}
        unknown = set(dispositions) - known
        if unknown:
            raise ValueError(f"unknown migration paths: {sorted(unknown)}")
        entries = tuple(
            MigrationEntry(entry.relative_path, entry.sha256, entry.size, dispositions.get(entry.relative_path, entry.disposition))
            for entry in self.entries
        )
        return MigrationManifest(self.source_root, entries, self.source_version)

    def dispositions_complete(self) -> bool:
        return all(
            isinstance(entry.disposition, Disposition) and entry.disposition != Disposition.QUARANTINE
            for entry in self.entries
        )


class IngestScanner:
    """Read-only scanner; it never writes or imports source runtime code."""

    def scan(self, source_root: str | Path) -> MigrationManifest:
        root = Path(source_root).resolve()
        entries = []
        for path in sorted(item for item in root.rglob("*") if item.is_file() and ".git" not in item.parts):
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            entries.append(MigrationEntry(path.relative_to(root).as_posix(), digest, path.stat().st_size))
        return MigrationManifest(str(root), tuple(entries))

    def verify(self, manifest: MigrationManifest) -> bool:
        """Re-scan a source and compare content/shape without modifying it."""
        current = self.scan(manifest.source_root)
        return current.source_hash == manifest.source_hash
