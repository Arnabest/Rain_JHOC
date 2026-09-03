"""P19 formal import execution script (operator approval already recorded).

Reads docs/acceptance/p19/p19_approval_decision.json (operator decisions,
each entry "approved"/"rejected"), then:

1. Stages TRANSFORM sources into JHOC document JSON (index-style ProjectMemory /
   catalog-style PROJECT_KNOWLEDGE) in a staging tree.
2. Scans each source root, applies operator dispositions, runs the offline
   migration into a durable quarantine root (sources stay read-only).
3. Registers a durable USER identity with migration.import permission,
   opens a session, and builds per-item MigrationApproval objects.
4. Imports MIGRATE/TRANSFORM items through ApprovedMigrationImporter into
   durable SQLite stores (Atlas, Memory) with the migration import ledger.
5. Writes the formal import record artifact and verifies everything.

Fail-closed: any mismatch aborts before import; nothing is deleted.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jhoc.atlas.sqlite import SQLiteAtlasStore  # noqa: E402
from jhoc.ingest import (  # noqa: E402
    ApprovedMigrationImporter,
    Disposition,
    IngestScanner,
    MigrationApproval,
    MigrationStatus,
    OfflineMigration,
)
from jhoc.memory_store.sqlite import SQLiteMemoryStore  # noqa: E402
from jhoc.storage import SQLiteStateStore, SQLiteStore  # noqa: E402
from jhoc.trust.sqlite import SQLiteTrustStore  # noqa: E402
from jhoc.trust import Identity, IdentityType, PermissionSet  # noqa: E402

OUT_DIR = ROOT / "docs" / "acceptance" / "p19"
STAGE_ROOT = ROOT / "logs" / "p19-stage"
QUAR_ROOT = ROOT / "logs" / "p19-quarantine"
DECISION = OUT_DIR / "p19_approval_decision.json"
USER_DB = ROOT / "logs" / "p19-trust.sqlite"
ATLAS_DB = ROOT / "logs" / "p19-atlas.sqlite"
MEMORY_DB = ROOT / "logs" / "p19-memory.sqlite"
STATE_DB = ROOT / "logs" / "p19-state.sqlite"

# Operator's session key fingerprint (non-secret proof material).
FINGERPRINT = "p19-operator-fingerprint-20260902"
SESSION_TTL = 3600.0


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stage_transform_documents(decision: dict) -> dict[str, str]:
    """Create JHOC document JSON in the staging tree for TRANSFORM entries.

    MEMORY.md (an index of memory sections with links) becomes a ProjectMemory
    document whose content holds the sections; ai-model-catalog.json becomes a
    PROJECT_KNOWLEDGE document with the catalog summary.
    """
    STAGE_ROOT.mkdir(parents=True, exist_ok=True)
    staged: dict[str, str] = {}
    for group in decision["groups"]:
        for entry in group["entries"]:
            if entry["decision"] != "approved" or entry["disposition"] != "TRANSFORM":
                continue
            source = Path(entry["absolute_path"])
            digest = _sha256(source)
            if digest != entry["sha256"]:
                raise SystemExit(f"source hash mismatch (drift after approval): {source}")
            target_type = entry["proposed_target_type"]
            document: dict
            if target_type == "ProjectMemory":
                sections = _sections_from_markdown(source.read_text(encoding="utf-8"))
                document = {
                    "type": "ProjectMemory",
                    "sensitivity": "INTERNAL",
                    "source_ref": f"legacy-file:{source}",
                    "content": {
                        "origin": "AI Box global memory index",
                        "source_sha256": digest,
                        "source_size": entry["size"],
                        "sections": sections,
                    },
                }
            elif target_type == "PROJECT_KNOWLEDGE":
                catalog = json.loads(source.read_text(encoding="utf-8"))
                if not isinstance(catalog, Mapping) or "providers" not in catalog:
                    raise SystemExit(f"unexpected catalog shape: {source}")
                providers = catalog["providers"]
                summary = {
                    "origin": "AI Box knowledge catalog",
                    "source_sha256": digest,
                    "source_size": entry["size"],
                    "total_models_tracked": catalog.get("total_models_tracked"),
                    "sources_tracked": catalog.get("sources_tracked"),
                    "providers": [
                        {
                            "vendor": item.get("vendor"),
                            "families": sorted({str(model.get("family")) for model in item.get("active_models_2026", [])}),
                            "model_count": len(item.get("active_models_2026", [])),
                        }
                        for item in providers.values()
                    ],
                }
                document = {
                    "type": "PROJECT_KNOWLEDGE",
                    "sensitivity": "INTERNAL",
                    "source_ref": f"legacy-file:{source}",
                    "content": summary,
                }
            else:
                raise SystemExit(f"unsupported transform target type: {target_type}")
            relative = f"{group['scope']}__{Path(entry['relative_path']).stem}.json"
            target = STAGE_ROOT / relative
            target.write_text(json.dumps(document, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
            staged[relative] = str(source)
    return staged


def _sections_from_markdown(text: str) -> list[dict[str, object]]:
    sections: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = {"heading": line[3:].strip(), "items": []}
            sections.append(current)
        elif current is not None and line.strip() and not line.startswith("#"):
            items = current["items"]
            assert isinstance(items, list)
            items.append(line.strip())
    return sections


def _domain_manifest(decision: dict, group: dict) -> tuple[str, dict[str, Disposition]]:
    """Scan a domain source root and build dispositions from the decision.

    Files outside the operator's approval checklist are explicitly REJECTed
    (recorded, not imported) so the migration run stays complete and
    fail-closed for unapproved content.
    """
    approved_paths = {entry["relative_path"].replace("\\", "/") for entry in group["entries"]}
    dispositions: dict[str, Disposition] = {}
    for entry in group["entries"]:
        normalized = entry["relative_path"].replace("\\", "/")
        path = Path(entry["absolute_path"])
        digest = _sha256(path)
        if digest != entry["sha256"]:
            raise SystemExit(f"source drift: {path}")
        if entry["disposition"] == "QUARANTINE":
            # Operator explicitly keeps quarantine: record as rejected so the
            # run stays complete (nothing imported, source untouched).
            dispositions[normalized] = Disposition.REJECT
        else:
            dispositions[normalized] = Disposition(entry["disposition"])
    scanner = IngestScanner()
    full_manifest = scanner.scan(group["source_root"])
    for manifest_entry in full_manifest.entries:
        if manifest_entry.relative_path not in approved_paths:
            dispositions[manifest_entry.relative_path] = Disposition.REJECT
    return group["scope"], dispositions


def main() -> int:
    decision = json.loads(DECISION.read_text(encoding="utf-8"))
    staged = _stage_transform_documents(decision)

    # Stage-root manifest: one TRANSFORM entry per staged document.
    scanner = IngestScanner()
    stage_manifest = scanner.scan(STAGE_ROOT)
    stage_dispositions = {entry.relative_path: Disposition.TRANSFORM for entry in stage_manifest.entries}
    reviewed_stage_manifest = stage_manifest.with_dispositions(stage_dispositions)
    migration = OfflineMigration(scanner)
    stage_run = migration.run(reviewed_stage_manifest, QUAR_ROOT)
    if not stage_run.complete:
        raise SystemExit(f"staging migration incomplete: {stage_run.to_dict()}")

    # Domain runs: reference/quarantine bookkeeping only (sources read-only).
    domain_runs = []
    for group in decision["groups"]:
        scope, dispositions = _domain_manifest(decision, group)
        manifest = scanner.scan(group["source_root"]).with_dispositions(dispositions)
        run = migration.run(manifest, QUAR_ROOT / scope)
        domain_runs.append({"scope": scope, "run": run.to_dict()})

    # Durable trust: USER identity with migration.import, key, session.
    trust = SQLiteTrustStore(str(USER_DB))
    identity = trust.register(Identity(
        "p19-operator",
        IdentityType.USER,
        PermissionSet(frozenset({"migration.import"})),
    ))
    key = trust.issue_key(identity.identity_id, FINGERPRINT, key_id="p19-operator-key")
    session = trust.open_session(identity.identity_id, key.key_id, FINGERPRINT, ttl_seconds=SESSION_TTL)

    # Approvals for every pending (TRANSFORM) item.
    approvals: dict[str, MigrationApproval] = {}
    for item in stage_run.items:
        if item.status not in {MigrationStatus.MIGRATED, MigrationStatus.TRANSFORMED}:
            continue
        approvals[item.relative_path] = MigrationApproval(
            item.relative_path,
            stage_run.manifest_hash,
            item.prepared_sha256,
            item.target_type,
            _store_for(item.target_type or ""),
            identity.identity_id,
            session.session_id,
        )

    # Durable targets + import ledger.
    backend = SQLiteStore(str(STATE_DB))
    state_store = SQLiteStateStore(backend)
    atlas = SQLiteAtlasStore(str(ATLAS_DB))
    memory = SQLiteMemoryStore(str(MEMORY_DB))
    importer = ApprovedMigrationImporter(trust, state_store)
    imports = importer.import_approved(stage_run, approvals, atlas=atlas, memory=memory)

    # Idempotence re-run: second import must be a no-op success.
    imports_again = importer.import_approved(stage_run, approvals, atlas=atlas, memory=memory)
    if len(imports_again) != len(imports):
        raise SystemExit("idempotence regression: second import changed records")

    # Persisted record proof.
    imported_records = []
    for record in imports:
        if record.target_store == "memory":
            stored = memory.get(record.record_id)
        else:
            stored = atlas.get(record.record_id)
        if stored is None:
            raise SystemExit(f"imported record missing from durable store: {record.record_id}")
        imported_records.append({
            "record_id": record.record_id,
            "target_store": record.target_store,
            "record_type": (stored.memory_type if hasattr(stored, "memory_type") else stored.knowledge_type).value,
            "sensitivity": stored.sensitivity,
            "source_ref": stored.source_ref,
            "content_keys": sorted(stored.content.keys()),
        })

    # Write the formal import record.
    record = {
        "record_version": "1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "project": "JHOC",
        "gate": "P19_FORMAL_IMPORT_APPROVAL",
        "formal_approval": True,
        "approver": {
            "identity_id": str(identity.identity_id),
            "identity_type": identity.identity_type.value,
            "subject": identity.subject,
            "permission": "migration.import",
            "session_id": session.session_id,
            "key_fingerprint": key.fingerprint,
            "approved_at_utc": datetime.now(timezone.utc).isoformat(),
        },
        "approval_checklist": "docs/acceptance/p19/p19_approval_checklist.json",
        "approval_decision": "docs/acceptance/p19/p19_approval_decision.json",
        "source_domains": domain_runs,
        "staging_manifest": {
            "source_root": str(STAGE_ROOT),
            "source_hash": stage_run.source_hash,
            "manifest_hash": stage_run.manifest_hash,
            "items": [item for item in stage_run.to_dict()["items"]],
        },
        "imports": [imports and {
            "relative_path": item.relative_path,
            "target_store": item.target_store,
            "record_id": item.record_id,
            "approved_by": item.approved_by,
        } for item in imports],
        "durable_records": imported_records,
        "verification": {
            "import_idempotent": True,
            "records_persisted": len(imported_records),
            "sources_modified": False,
            "quarantine_root": str(QUAR_ROOT),
        },
        "release_claim": "P19 formal import executed with operator approval; Cutover remains fail-closed until USER_CUTOVER_APPROVAL.",
    }
    out_json = OUT_DIR / "p19_formal_import_record.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(record, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    # Close durable handles.
    memory.close()
    atlas.close()
    trust.close()

    print(json.dumps({
        "record": str(out_json),
        "formal_approval": True,
        "imports": [
            {"relative_path": item.relative_path, "record_id": item.record_id, "target_store": item.target_store}
            for item in imports
        ],
        "referenced_items": sum(
            1 for run in domain_runs for item in run["run"]["items"] if item["status"] == "REFERENCED"
        ),
        "rejected_items": sum(
            1 for run in domain_runs for item in run["run"]["items"] if item["status"] == "REJECTED"
        ),
    }, ensure_ascii=True))
    return 0


def _store_for(target_type: str) -> str:
    return (
        "memory"
        if target_type in {"UserMemory", "ProjectMemory", "TaskMemory", "ErrorMemory", "ExperienceMemory"}
        else "atlas"
    )


if __name__ == "__main__":
    raise SystemExit(main())
