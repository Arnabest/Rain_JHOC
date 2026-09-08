from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from uuid import UUID

from jhoc.independence import IndependenceReport
from jhoc.trust import IdentityType, TrustStore


@dataclass(frozen=True, slots=True)
class CutoverDecision:
    ready: bool
    reason: str
    failed_gates: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ArchiveManifest:
    archive_id: str
    source_manifest_hash: str
    entries: tuple[str, ...]
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    migration_manifest_hash: str | None = None

    def __post_init__(self) -> None:
        if not self.archive_id.strip() or not self.source_manifest_hash.strip() or not self.entries:
            raise ValueError("archive manifest requires id, source hash and entries")
        if any(not entry.strip() for entry in self.entries):
            raise ValueError("archive entries cannot be empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "archive_id": self.archive_id,
            "source_manifest_hash": self.source_manifest_hash,
            "entries": list(self.entries),
            "created_at": self.created_at.isoformat(),
            "migration_manifest_hash": self.migration_manifest_hash,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.to_json().encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class EntrypointProof:
    entrypoint: str
    source_path: str
    source_sha256: str
    verified_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not self.entrypoint.strip() or not self.source_path.strip():
            raise ValueError("entrypoint proof requires entrypoint and source path")
        if len(self.source_sha256) != 64 or any(char not in "0123456789abcdef" for char in self.source_sha256):
            raise ValueError("entrypoint proof requires a lowercase SHA-256 digest")
        if self.verified_at.tzinfo is None or self.verified_at.utcoffset() is None:
            raise ValueError("entrypoint proof time must be timezone-aware")

    @classmethod
    def from_file(cls, entrypoint: str, source_path: str | Path) -> "EntrypointProof":
        path = Path(source_path).resolve()
        return cls(entrypoint, str(path), hashlib.sha256(path.read_bytes()).hexdigest())

    def verify(self) -> bool:
        try:
            return hashlib.sha256(Path(self.source_path).resolve().read_bytes()).hexdigest() == self.source_sha256
        except OSError:
            return False

    def to_dict(self) -> dict[str, str]:
        return {
            "entrypoint": self.entrypoint,
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "verified_at": self.verified_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, value: dict[str, str]) -> "EntrypointProof":
        return cls(
            value["entrypoint"],
            value["source_path"],
            value["source_sha256"],
            datetime.fromisoformat(value["verified_at"]),
        )


@dataclass(frozen=True, slots=True)
class UserCutoverApproval:
    approved_by: UUID
    session_id: str
    statement: str
    archive_id: str
    archive_digest: str
    migration_manifest_hash: str
    entrypoint_sha256: str
    approval_version: str = "1"
    approved_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.session_id,
                self.statement,
                self.archive_id,
                self.archive_digest,
                self.migration_manifest_hash,
                self.entrypoint_sha256,
                self.approval_version,
            )
        ):
            raise ValueError("user Cutover approval fields are required")
        if self.approved_at.tzinfo is None or self.approved_at.utcoffset() is None:
            raise ValueError("user Cutover approval time must be timezone-aware")


class CutoverValidator:
    PERMISSION = "ops.cutover"

    def __init__(
        self,
        trust: TrustStore | None = None,
        *,
        required_entrypoint: str = "jhoc.entrypoint:create_application",
        required_source_path: str | Path | None = None,
    ) -> None:
        self.trust = trust
        self.required_entrypoint = required_entrypoint
        self.required_source_path = Path(
            required_source_path or Path(__file__).resolve().parents[1] / "entrypoint.py"
        ).resolve()

    def validate(self, gates: dict[str, bool], independence: IndependenceReport, *, migration_complete: bool) -> CutoverDecision:
        failed = tuple(name for name, passed in gates.items() if not passed)
        if not independence.passed:
            failed += ("INDEPENDENCE",)
        if not migration_complete:
            failed += ("MIGRATION",)
        if failed:
            return CutoverDecision(False, "cutover blocked until all gates pass", failed)
        return CutoverDecision(True, "all cutover gates passed", ())

    def validate_prerequisites(
        self,
        gates: dict[str, bool],
        independence: IndependenceReport,
        *,
        migration_complete: bool,
        archive: ArchiveManifest | None,
        migration_manifest_hash: str | None = None,
        entrypoint_proof: EntrypointProof | None = None,
    ) -> CutoverDecision:
        decision = self.validate(gates, independence, migration_complete=migration_complete)
        failed = list(decision.failed_gates)
        if archive is None:
            failed.append("ARCHIVE_MANIFEST")
        if migration_manifest_hash is None or not migration_manifest_hash.strip():
            failed.append("MIGRATION_MANIFEST_HASH")
        elif archive is not None and archive.migration_manifest_hash != migration_manifest_hash:
            failed.append("ARCHIVE_MANIFEST_HASH")
        if (
            entrypoint_proof is None
            or entrypoint_proof.entrypoint != self.required_entrypoint
            or Path(entrypoint_proof.source_path).resolve() != self.required_source_path
            or not entrypoint_proof.verify()
        ):
            failed.append("UNIQUE_ENTRYPOINT")
        if failed:
            reason = "final cutover requires verified archive manifest" if failed == ["ARCHIVE_MANIFEST"] else "final cutover blocked by required gates"
            return CutoverDecision(False, reason, tuple(dict.fromkeys(failed)))
        return CutoverDecision(True, "all cutover prerequisites and archive evidence passed", ())

    def validate_final(
        self,
        gates: dict[str, bool],
        independence: IndependenceReport,
        *,
        migration_complete: bool,
        archive: ArchiveManifest | None,
        migration_manifest_hash: str | None = None,
        entrypoint_proof: EntrypointProof | None = None,
        user_approval: UserCutoverApproval | None = None,
    ) -> CutoverDecision:
        decision = self.validate_prerequisites(
            gates,
            independence,
            migration_complete=migration_complete,
            archive=archive,
            migration_manifest_hash=migration_manifest_hash,
            entrypoint_proof=entrypoint_proof,
        )
        failed = list(decision.failed_gates)
        if not self._valid_user_approval(
            user_approval,
            archive=archive,
            migration_manifest_hash=migration_manifest_hash,
            entrypoint_proof=entrypoint_proof,
        ):
            failed.append("USER_CUTOVER_APPROVAL")
        if failed:
            return CutoverDecision(
                False,
                "final cutover blocked by required gates",
                tuple(dict.fromkeys(failed)),
            )
        return CutoverDecision(True, "all final cutover gates and explicit user approval passed", ())

    def _valid_user_approval(
        self,
        approval: UserCutoverApproval | None,
        *,
        archive: ArchiveManifest | None,
        migration_manifest_hash: str | None,
        entrypoint_proof: EntrypointProof | None,
    ) -> bool:
        if self.trust is None or approval is None or archive is None or entrypoint_proof is None:
            return False
        identity = self.trust.get(approval.approved_by)
        if identity is None or identity.identity_type != IdentityType.USER:
            return False
        if not self.trust.authorize(
            approval.approved_by,
            self.PERMISSION,
            session_id=approval.session_id,
        ):
            return False
        return (
            approval.archive_id == archive.archive_id
            and approval.archive_digest == archive.digest
            and approval.migration_manifest_hash == migration_manifest_hash
            and approval.entrypoint_sha256 == entrypoint_proof.source_sha256
        )
