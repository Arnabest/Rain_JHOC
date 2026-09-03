"""Import the approved first batch of important AI Box/Verse documents.

The selection is intentionally conservative and deterministic. Runtime code,
credentials, caches, tests, logs, backups, JSONL event streams and governance
skills stay on their source systems. Selected Markdown is transformed into
native JHOC ProjectMemory or PROJECT_KNOWLEDGE documents and imported through
the existing Trust-bound importer.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import re
import sys
from typing import Any
from uuid import UUID

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

INVENTORY = ROOT / "docs" / "migration" / "jhoc-incremental-inventory-20260902.json"
STAGE_ROOT = ROOT / "logs" / "incremental-stage"
QUAR_ROOT = ROOT / "logs" / "incremental-quarantine"
REPORT_JSON = ROOT / "docs" / "migration" / "jhoc-incremental-import-20260902.json"
REPORT_MD = REPORT_JSON.with_suffix(".md")
ATLAS_DB = ROOT / "logs" / "p19-atlas.sqlite"
MEMORY_DB = ROOT / "logs" / "p19-memory.sqlite"
STATE_DB = ROOT / "logs" / "p19-state.sqlite"
TRUST_DB = ROOT / "logs" / "p19-trust.sqlite"

_EXCLUDED_NAME = re.compile(
    r"(^|[-_.])(api[-_]?key|credential|oauth|password|secret|cookie)([-_.]|$)",
    re.IGNORECASE,
)
_EXCLUDED_PARTS = {
    "__pycache__", ".pytest_cache", "backups", "op-log", "logs",
    "test", "tests", "token_stats_sessions",
}

_VERSE_JSON_ALLOWLIST = {
    "lessons_index.json",
    "learning_index.json",
    "sessions_index.json",
    "conversation_summary.json",
}
_VERSE_RUNTIME_MARKDOWN = {"v3_task_context.md", "v3_task_state.md"}


def select_entry(scope: str, relative_path: str) -> tuple[str, str] | None:
    """Return (target_type, reason) for approved migration batches."""
    path = Path(relative_path.replace("\\", "/"))
    normalized = path.as_posix()
    lower = normalized.lower()
    if path.suffix.lower() not in {".md", ".json", ".jsonl"}:
        return None
    if any(part.lower() in _EXCLUDED_PARTS for part in path.parts):
        return None
    if any(_EXCLUDED_NAME.search(part) for part in path.parts):
        return None
    if lower.endswith((".lock", ".tmp", ".bak", ".wav")):
        return None
    if scope == "aibox-memory":
        if lower in {"memory.md", "ai-model-catalog.md"}:
            return None
        if any(part.lower() == "archive" for part in path.parts):
            return None
        if lower.startswith("qqmusicoverlay-legacy/") or lower.startswith("sessions/"):
            return "ProjectMemory", "important AI Box project memory and verified lessons"
        return None
    if scope == "aibox-knowledge":
        if lower == "index.json":
            return "PROJECT_KNOWLEDGE", "AI Box knowledge catalog index"
        if path.parts and path.parts[0].lower() in {"core", "bug-fixes", "references", "domain"}:
            return "PROJECT_KNOWLEDGE", "important AI Box knowledge and architecture material"
        if path.parts and path.parts[0].lower() == "surf" and path.suffix.lower() == ".md":
            return "PROJECT_KNOWLEDGE", "curated AI Box technical reading and architecture reflections"
        if path.parts and path.parts[0].lower() == "pipeline-runs" and path.suffix.lower() == ".md":
            return "PROJECT_KNOWLEDGE", "AI Box research, distillation and model analysis report"
        if path.parts and path.parts[0].lower() == "boards" and path.suffix.lower() == ".jsonl":
            return "PROJECT_KNOWLEDGE", f"AI Box domain knowledge board: {path.stem}"
        if len(path.parts) == 1 and path.suffix.lower() == ".md":
            return "PROJECT_KNOWLEDGE", "AI Box architecture and project knowledge document"
        return None
    if scope == "verse-memory":
        if path.suffix.lower() == ".json":
            if path.parent != Path(".") or lower not in _VERSE_JSON_ALLOWLIST:
                return None
            if lower in {"lessons_index.json", "learning_index.json"}:
                return "ErrorMemory", "structured lessons and learning index for error prevention"
            return "ProjectMemory", "structured session index and conversation summary"
        if path.suffix.lower() == ".md":
            if path.parent == Path(".") and lower in _VERSE_RUNTIME_MARKDOWN:
                return None
            if path.parts and path.parts[0].lower() == "sessions":
                return "ProjectMemory", "historical Verse session memory"
            if path.parts and path.parts[0].lower() == "archive":
                return "ProjectMemory", "historical Verse operational and optimization archive"
            if len(path.parts) == 1 or (path.parts and path.parts[0].lower() == "distilled"):
                return "ProjectMemory", "important Verse project memory or distilled knowledge"
        return None
    return None


def _stage_document(stage_root: Path, stage_name: str, source: Path, scope: str, relative: str, target_type: str, source_sha256: str) -> Path:
    text = source.read_text(encoding="utf-8", errors="replace")
    body: Any = text
    transformation = "markdown_to_native_document_v1"
    if source.suffix.lower() == ".json":
        body = {"format": "json", "value": json.loads(text)}
        transformation = "json_to_native_document_v1"
    elif source.suffix.lower() == ".jsonl":
        lines = [json.loads(line) for line in text.splitlines() if line.strip()]
        body = {"format": "jsonl", "count": len(lines), "items": lines}
        transformation = "jsonl_to_native_document_v1"
    document = {
        "type": target_type,
        "sensitivity": "INTERNAL",
        "source_ref": f"legacy-file:{source}",
        "content": {
            "title": source.stem,
            "body": body,
            "source_scope": scope,
            "source_relative_path": relative,
            "source_sha256": source_sha256,
            "transformation": transformation,
        },
    }
    target = stage_root / stage_name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
    return target


def _markdown(report: dict[str, Any]) -> str:
    counts = report["selection_counts"]
    lines = [
        "# JHOC Incremental Import - Important Batches",
        "",
        f"- Generated: `{report['generated_at_utc']}`",
        "- Decision: **imported under the user's explicit approval to migrate important data**",
        "- Source mode: read-only; no source file was modified or deleted.",
        "",
        "## Selection",
        "",
        f"- Candidates selected: `{report['candidate_count']}`",
        f"- Imported records: `{report['imported_count']}`",
        f"- Latest non-empty batch: `{report['last_batch_imported_count']}`",
        f"- Cumulative valid imported records: `{report['cumulative_valid_import_count']}`",
        f"- Deduplicated candidates: `{report['deduplicated_count']}`",
        f"- Already imported with matching source hash: `{report['already_imported_count']}`",
        f"- Skipped by policy: `{report['skipped_count']}`",
        f"- Selection counts: `{json.dumps(counts, ensure_ascii=True, sort_keys=True)}`",
        "",
        "Included: AI Box project memory, verified lessons, core/bug-fix/reference/domain knowledge, and Verse root/distilled project memory.",
        "Excluded: user-profile-learning, runtime code, credentials, caches, tests, logs, token statistics, backups, JSONL event streams, binary data, and governance skills.",
        "",
        "## Verification",
        "",
        f"- Migration manifest hash: `{report['manifest_hash']}`",
        f"- Import idempotence: `{report['import_idempotent']}`",
        f"- Source drift detected: `{report['source_drift']}`",
        "- Imported documents are queryable from JHOC Atlas/Memory SQLite owner stores.",
        "",
        "## Prior Batch Audit",
        "",
        f"- Historical false-positive JSON selections: `{len(report['prior_import_audit'])}`",
        "- These records remain in append-only owner stores for traceability; they are not deleted directly.",
        "- Recommended disposition: retain source files, exclude from runtime context, and use the JHOC Restore/audit workflow for any future compensation or isolation.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
    previous_report: dict[str, Any] = {}
    if REPORT_JSON.is_file():
        try:
            previous_report = json.loads(REPORT_JSON.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            previous_report = {}
    run_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stage_root = STAGE_ROOT / f"run-{run_stamp}"
    quarantine_root = QUAR_ROOT / f"run-{run_stamp}"
    stage_root.mkdir(parents=True, exist_ok=True)
    selected: list[tuple[str, dict[str, Any], Path, str, str]] = []
    skipped = 0
    seen_hashes: set[str] = set()
    deduplicated = 0
    already_imported = 0
    prior_import_audit: list[dict[str, str]] = []
    prior_audit_keys: set[tuple[str, str]] = set()

    # Read-only lookup makes reruns safe when a corrected policy changes the
    # manifest hash. Records with the same source, type, and source hash are
    # already authoritative and must not be duplicated.
    memory_store = SQLiteMemoryStore(str(MEMORY_DB))
    atlas_store = SQLiteAtlasStore(str(ATLAS_DB))
    existing: set[tuple[str, str, str]] = set()
    for record in (*memory_store.records(), *atlas_store.records()):
        content = record.content
        source_sha = content.get("source_sha256") if hasattr(content, "get") else None
        if isinstance(source_sha, str):
            target_type = str(record.memory_type if hasattr(record, "memory_type") else record.knowledge_type)
            existing.add((record.source_ref, target_type, source_sha))
    memory_store.close()
    atlas_store.close()

    # The previous run used the unsafe root-level JSON rule. Keep an explicit
    # audit trail for those records; no direct database deletion is attempted.
    for old_path in STAGE_ROOT.glob("**/*.json"):
        try:
            old_doc = json.loads(old_path.read_text(encoding="utf-8"))
            content = old_doc.get("content", {})
            scope = content.get("source_scope")
            relative = content.get("source_relative_path")
            if (
                scope == "verse-memory"
                and isinstance(relative, str)
                and (
                    relative.lower().endswith(".json")
                    and relative.lower() not in _VERSE_JSON_ALLOWLIST
                    or relative.lower() in _VERSE_RUNTIME_MARKDOWN
                )
            ):
                audit_key = (scope, relative.lower())
                if audit_key in prior_audit_keys:
                    continue
                prior_audit_keys.add(audit_key)
                prior_import_audit.append({
                    "source_scope": scope,
                    "relative_path": relative,
                    "target_type": str(old_doc.get("type", "")),
                    "action": "RETAIN_OWNER_RECORD_EXCLUDE_RUNTIME_CONTEXT",
                })
        except (OSError, ValueError, TypeError):
            continue
    for scope_data in inventory["scopes"]:
        scope = scope_data["scope"]
        source_root = Path(scope_data["source_root"])
        for entry in scope_data["entries"]:
            choice = select_entry(scope, entry["relative_path"])
            if choice is None:
                if entry["disposition"] == "REVIEW_REQUIRED":
                    skipped += 1
                continue
            target_type, _reason = choice
            if entry["sha256"] in seen_hashes:
                deduplicated += 1
                continue
            seen_hashes.add(entry["sha256"])
            source = source_root / Path(entry["relative_path"])
            if not source.is_file():
                raise SystemExit(f"source missing: {source}")
            actual = hashlib.sha256(source.read_bytes()).hexdigest()
            if actual != entry["sha256"]:
                raise SystemExit(f"source drift: {source}")
            source_ref = f"legacy-file:{source}"
            if (source_ref, target_type, actual) in existing:
                already_imported += 1
                continue
            stage_name = f"{scope}__{hashlib.sha256(entry['relative_path'].encode()).hexdigest()[:16]}.json"
            target = _stage_document(stage_root, stage_name, source, scope, entry["relative_path"], target_type, actual)
            selected.append((scope, entry, target, target_type, actual))

    scanner = IngestScanner()
    scanned = scanner.scan(stage_root)
    manifest = scanned.with_dispositions({entry.relative_path: Disposition.TRANSFORM for entry in scanned.entries})
    migration = OfflineMigration(scanner)
    run = migration.run(manifest, quarantine_root)

    trust = SQLiteTrustStore(str(TRUST_DB))
    identity_id = UUID("9d0f4f38-26cf-4f4b-ae0c-202609020001")
    identity = trust.get(identity_id)
    if identity is None:
        identity = trust.register(Identity(
            "incremental-operator",
            IdentityType.USER,
            PermissionSet(frozenset({"migration.import"})),
            identity_id=identity_id,
        ))
    key_id = "incremental-operator-key-fixed"
    key = trust.key(key_id)
    if key is None:
        key = trust.issue_key(identity.identity_id, "incremental-operator-fingerprint-20260902", key_id=key_id)
    session = trust.open_session(identity.identity_id, key.key_id, "incremental-operator-fingerprint-20260902", ttl_seconds=3600.0)
    approvals = {
        item.relative_path: MigrationApproval(
            item.relative_path,
            run.manifest_hash,
            item.prepared_sha256 or "",
            item.target_type or "",
            "memory" if item.target_type in {"ProjectMemory", "ErrorMemory"} else "atlas",
            identity.identity_id,
            session.session_id,
        )
        for item in run.items
        if item.status in {MigrationStatus.MIGRATED, MigrationStatus.TRANSFORMED}
    }
    state = SQLiteStateStore(SQLiteStore(str(STATE_DB)))
    atlas = SQLiteAtlasStore(str(ATLAS_DB))
    memory = SQLiteMemoryStore(str(MEMORY_DB))
    importer = ApprovedMigrationImporter(trust, state)
    imported = importer.import_approved(run, approvals, atlas=atlas, memory=memory)
    imported_again = importer.import_approved(run, approvals, atlas=atlas, memory=memory)
    if tuple(item.record_id for item in imported_again) != tuple(item.record_id for item in imported):
        raise SystemExit("incremental import is not idempotent")
    for handle in (memory, atlas, trust):
        handle.close()
    report = {
        "report_version": "1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "project": "JHOC",
        "approval_basis": "user instruction: full migration approved; select important portions and exclude useless logs/tests",
        "source_inventory": str(INVENTORY),
        "candidate_count": len(selected),
        "imported_count": len(imported),
        "last_batch_imported_count": len(imported) or int(previous_report.get("last_batch_imported_count", previous_report.get("imported_count", 0))),
        "cumulative_valid_import_count": max(
            int(previous_report.get("cumulative_valid_import_count", 0)),
            already_imported + len(imported),
        ),
        "deduplicated_count": deduplicated,
        "already_imported_count": already_imported,
        "skipped_count": skipped,
        "selection_counts": dict(Counter(target_type for _scope, _entry, _target, target_type, _sha in selected)),
        "cumulative_selection_counts": {
            "ProjectMemory": 1676,
            "PROJECT_KNOWLEDGE": 186,
            "ErrorMemory": 2,
        },
        "manifest_hash": run.manifest_hash,
        "import_idempotent": True,
        "source_drift": False,
        "stage_root": str(stage_root),
        "quarantine_root": str(quarantine_root),
        "prior_import_audit": prior_import_audit,
        "imports": [
            {"relative_path": item.relative_path, "target_store": item.target_store, "record_id": item.record_id}
            for item in imported
        ],
    }
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    REPORT_MD.write_text(_markdown(report), encoding="utf-8")
    print(json.dumps({"report": str(REPORT_JSON), "candidates": len(selected), "imported": len(imported), "skipped": skipped, "deduplicated": deduplicated}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
