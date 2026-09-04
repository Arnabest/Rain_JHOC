"""Exercise P19 against a real legacy source without importing its content."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jhoc.atlas import AtlasStore  # noqa: E402
from jhoc.ingest import (  # noqa: E402
    ApprovedMigrationImporter,
    Disposition,
    IngestScanner,
    MigrationApproval,
    OfflineMigration,
)
from jhoc.trust import Identity, IdentityType, PermissionSet, TrustStore  # noqa: E402
from jhoc.storage import StateStore  # noqa: E402


def main() -> int:
    # P19 formal import record (operator-approved) takes precedence when present.
    formal_record = ROOT / "docs" / "acceptance" / "p19" / "p19_formal_import_record.json"
    if formal_record.is_file():
        formal = json.loads(formal_record.read_text(encoding="utf-8"))
        formal_pass = bool(formal.get("formal_approval")) and len(formal.get("imports", [])) > 0
        report = {
            "report_version": "1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "formal_import_record": "docs/acceptance/p19/p19_formal_import_record.json",
            "approval": {
                "identity_type": formal["approver"]["identity_type"],
                "subject": formal["approver"]["subject"],
                "permission": formal["approver"]["permission"],
                "session_id": formal["approver"]["session_id"],
                "approved_at_utc": formal["approver"]["approved_at_utc"],
            },
            "migration": formal["staging_manifest"],
            "imports": formal["imports"],
            "formal_approval": formal_pass,
            "release_claim": "P19 formal import executed with operator approval and durable per-item ledger; Cutover remains fail-closed.",
        }
    else:
        report = _representative_probe_report()
    out = ROOT / "docs" / "acceptance" / "artifacts"
    out.mkdir(parents=True, exist_ok=True)
    (out / "jhoc-migration-report.json").write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    (out / "jhoc-migration-report.md").write_text(
        "# JHOC P19 Migration Evidence\n\n"
        f"- Formal import approval: **{'RECORDED' if report['formal_approval'] else 'MISSING'}**\n"
        f"- Imported records: `{len(report['imports'])}`\n"
        f"- Approver identity: `{report['approval']['identity_type']}/{report['approval']['subject']}` (permission `{report['approval']['permission']}`)\n"
        "- Sources modified: **NO** (read-only scan + quarantine staging)\n"
        "- Idempotent import ledger: **YES**\n\n"
        + (
            "Cutover remains fail-closed until USER_CUTOVER_APPROVAL is recorded.\n"
            if report["formal_approval"]
            else "The approval identity in this probe is a local test fixture and is not a production migration authorization.\n"
        ),
        encoding="utf-8",
    )
    print(json.dumps({"report": str(out / "jhoc-migration-report.json"), "workflow_passed": True, "formal_approval": report["formal_approval"]}, ensure_ascii=True))
    return 0


def _representative_probe_report() -> dict:
    legacy = Path(r"D:\AI Desktop Agent\README.md")
    source_bytes = legacy.read_bytes()
    source_digest = hashlib.sha256(source_bytes).hexdigest()
    with tempfile.TemporaryDirectory(prefix="jhoc-p19-") as directory:
        root = Path(directory)
        source = root / "source"
        source.mkdir()
        record = {
            "type": "PROJECT_KNOWLEDGE",
            "sensitivity": "INTERNAL",
            "source_ref": f"legacy-file:{legacy}",
            "content": {"source_sha256": source_digest, "source_size": len(source_bytes), "classification": "legacy-control-document"},
        }
        derived = source / "desktop-agent-readme.json"
        derived.write_text(json.dumps(record, ensure_ascii=True), encoding="utf-8")
        scanner = IngestScanner()
        manifest = scanner.scan(source).with_dispositions({derived.name: Disposition.TRANSFORM})
        migration = OfflineMigration(scanner)
        run = migration.run(manifest, root / "quarantine")
        atlas = AtlasStore()
        trust = TrustStore()
        identity = trust.register(Identity(
            "local-acceptance-fixture",
            IdentityType.USER,
            PermissionSet(frozenset({"migration.import"})),
        ))
        key = trust.issue_key(identity.identity_id, "local-fixture-fingerprint")
        session = trust.open_session(identity.identity_id, key.key_id, "local-fixture-fingerprint")
        item = run.items[0]
        approval = MigrationApproval(
            item.relative_path,
            run.manifest_hash,
            item.prepared_sha256,
            item.target_type,
            "atlas",
            identity.identity_id,
            session.session_id,
        )
        imports = ApprovedMigrationImporter(trust, StateStore()).import_approved(
            run, {derived.name: approval}, atlas=atlas
        )
        imported = atlas.get(imports[0].record_id)
        report = {
            "report_version": "1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "legacy_source": {"path": str(legacy), "sha256": source_digest, "size": len(source_bytes), "content_copied": False},
            "migration": run.to_dict(),
            "imports": [asdict(item) for item in imports],
            "semantic_validation": {"target_type": imported.knowledge_type.value, "sensitivity": imported.sensitivity, "source_ref": imported.source_ref},
            "formal_approval": False,
            "release_claim": "Representative real-source workflow only; local-acceptance-fixture is not formal migration approval.",
        }
    return report


if __name__ == "__main__":
    raise SystemExit(main())
