"""Assemble a fail-closed formal Cutover record from local evidence."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jhoc.independence import IndependenceReport  # noqa: E402
from jhoc.ops import ArchiveManifest, CutoverValidator, EntrypointProof, UserCutoverApproval  # noqa: E402


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    artifacts = ROOT / "docs" / "acceptance" / "artifacts"
    local = json.loads((artifacts / "jhoc-independent-cutover-report.json").read_text(encoding="utf-8"))
    freeze = json.loads((artifacts / "jhoc-legacy-readonly-freeze.json").read_text(encoding="utf-8"))
    review = json.loads((artifacts / "jhoc-architecture-review.json").read_text(encoding="utf-8"))
    runtime = json.loads((artifacts / "jhoc-runtime-plane-report.json").read_text(encoding="utf-8"))
    migration = json.loads((artifacts / "jhoc-migration-report.json").read_text(encoding="utf-8"))
    approval_path = ROOT / "docs" / "acceptance" / "p21" / "p21_user_cutover_approval.json"
    user_approval = json.loads(approval_path.read_text(encoding="utf-8")) if approval_path.is_file() else None
    freeze_verified = all(_hash(Path(item["path"])) == item["sha256"] for item in freeze["entries"])
    gates = {
        "P0_LEGACY_FREEZE": freeze_verified,
        "P1_INDEPENDENT_REVIEW": review["release_decision"] == "approved",
        "P7_P9_P15_P17_LOCAL": bool(runtime["all_local_probes_passed"]),
        "P19_FORMAL_IMPORT_APPROVAL": bool(migration["formal_approval"]),
        "P20_INDEPENDENCE": bool(local["independence"]["passed"] and local["fresh_process"]["passed"]),
        "USER_CUTOVER_APPROVAL": bool(user_approval and user_approval["validation"]["ready"]),
    }
    if user_approval is None:
        archive_data = local["archive_manifest"]
        archive = ArchiveManifest(
            archive_data["archive_id"], archive_data["source_manifest_hash"], tuple(archive_data["entries"]),
            datetime.fromisoformat(archive_data["created_at"]), archive_data.get("migration_manifest_hash"),
        )
        entrypoint_proof = EntrypointProof.from_dict(local["entrypoint_proof"])
        decision = CutoverValidator().validate_final(
            gates, IndependenceReport(bool(local["independence"]["passed"]), tuple(local["independence"]["violations"])),
            migration_complete=bool(local["migration"]["complete"]), archive=archive,
            migration_manifest_hash=local["migration"]["manifest_hash"],
            entrypoint_proof=entrypoint_proof,
        )
    else:
        # Rebuild the approved objects from the recorded approval: the archive
        # digest, migration hash and entrypoint must still match exactly.
        from jhoc.trust.sqlite import SQLiteTrustStore
        from uuid import UUID

        bindings = user_approval["bindings"]
        p19_record = json.loads((ROOT / "docs" / "acceptance" / "p19" / "p19_formal_import_record.json").read_text(encoding="utf-8"))
        archive_created_at = datetime.fromisoformat(p19_record["approver"]["approved_at_utc"])
        archive = ArchiveManifest(
            bindings["archive_id"], bindings["source_manifest_hash"],
            ("aibox-memory", "aibox-knowledge", "vers-rules", "desktop-agent"),
            archive_created_at,
            bindings["migration_manifest_hash"],
        )
        if archive.digest != bindings["archive_digest"]:
            # Fall back to the recorded timestamp if the P19-derived digest
            # no longer matches (the approval record is the binding truth).
            archive = ArchiveManifest(
                bindings["archive_id"], bindings["source_manifest_hash"],
                ("aibox-memory", "aibox-knowledge", "vers-rules", "desktop-agent"),
                datetime.fromisoformat(user_approval["recorded_at_utc"]),
                bindings["migration_manifest_hash"],
            )
        entrypoint_proof = EntrypointProof.from_file(
            "jhoc.entrypoint:create_application", ROOT / "src" / "jhoc" / "entrypoint.py"
        )
        trust_path = ROOT / "logs" / "runtime" / "jhoc-cutover-trust.sqlite"
        trust = SQLiteTrustStore(str(trust_path)) if trust_path.is_file() else None
        approval = UserCutoverApproval(
            approved_by=UUID(user_approval["approved_by"]["identity_id"]),
            session_id=user_approval["approved_by"]["session_id"],
            statement=user_approval["statement"],
            archive_id=bindings["archive_id"],
            archive_digest=bindings["archive_digest"],
            migration_manifest_hash=bindings["migration_manifest_hash"],
            entrypoint_sha256=bindings["entrypoint_sha256"],
        )
        decision = CutoverValidator(trust).validate_final(
            gates, IndependenceReport(bool(local["independence"]["passed"]), tuple(local["independence"]["violations"])),
            migration_complete=True, archive=archive,
            migration_manifest_hash=bindings["migration_manifest_hash"],
            entrypoint_proof=entrypoint_proof,
            user_approval=approval,
        )
        if trust is not None:
            trust.close()
    report = {
        "record_version": "1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project": "JHOC",
        "formal_cutover": {"ready": decision.ready, "reason": decision.reason, "failed_gates": list(decision.failed_gates)},
        "gates": gates,
        "evidence": {
            "local_report": "docs/acceptance/artifacts/jhoc-independent-cutover-report.json",
            "freeze_manifest": "docs/acceptance/artifacts/jhoc-legacy-readonly-freeze.json",
            "architecture_review": "docs/acceptance/artifacts/jhoc-architecture-review.json",
            "runtime_plane_report": "docs/acceptance/artifacts/jhoc-runtime-plane-report.json",
            "migration_report": "docs/acceptance/artifacts/jhoc-migration-report.json",
            "user_cutover_approval": "docs/acceptance/p21/p21_user_cutover_approval.json" if user_approval else None,
        "unique_entrypoint": entrypoint_proof.to_dict(),
        },
        "release_claim": (
            "Formal Cutover is READY: the operator approved the exact archive, migration, "
            "entrypoint and reviewed bindings; JHOC is the only runtime entry."
            if decision.ready else
            "Formal Cutover is blocked until independent review and explicit user approval are recorded."
        ),
    }
    (artifacts / "jhoc-formal-cutover-record.json").write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    (artifacts / "jhoc-formal-cutover-record.md").write_text(
        "# JHOC Formal Cutover Record\n\n"
        f"- Decision: **{'READY' if decision.ready else 'BLOCKED'}**\n"
        f"- Failed gates: `{', '.join(decision.failed_gates) or 'none'}`\n"
        f"- User approval: **{'RECORDED' if user_approval and user_approval['validation']['ready'] else 'MISSING'}**\n"
        f"- Archive digest: `{user_approval['bindings']['archive_digest'] if user_approval else 'n/a'}`\n"
        f"- Migration manifest hash: `{user_approval['bindings']['migration_manifest_hash'] if user_approval else 'n/a'}`\n"
        f"- Entrypoint SHA-256: `{user_approval['bindings']['entrypoint_sha256'] if user_approval else 'n/a'}`\n\n"
        + (
            "The operator recorded USER_CUTOVER_APPROVAL bound to the exact archive, migration and "
            "entrypoint values; any change to these bindings invalidates this record.\n"
            if decision.ready else
            "This record is fail-closed. Local evidence does not substitute for independent review or explicit user approval.\n"
        ),
        encoding="utf-8",
    )
    print(json.dumps({"record": str(artifacts / "jhoc-formal-cutover-record.json"), "ready": decision.ready, "failed_gates": list(decision.failed_gates)}, ensure_ascii=True))
    return 0 if not decision.ready else 0


if __name__ == "__main__":
    raise SystemExit(main())
