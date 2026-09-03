"""Assemble the exact binding values for USER_CUTOVER_APPROVAL (read-only).

This package computes every value the final cutover approval must bind to:
- current git HEAD commit / tree hash
- unique entrypoint proof (SHA-256)
- P19 formal import record canonical hash (migration manifest hash)
- legacy readonly freeze manifest hash
- R5 independent review binding
- ArchiveManifest (with digest) covering the legacy source scopes

It writes a checklist JSON only. No approval is recorded here.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jhoc.ops import ArchiveManifest, EntrypointProof  # noqa: E402

P19_RECORD = ROOT / "docs" / "acceptance" / "p19" / "p19_formal_import_record.json"
FREEZE = ROOT / "docs" / "acceptance" / "artifacts" / "jhoc-legacy-readonly-freeze.json"
R5_SUMMARY = ROOT / "docs" / "acceptance" / "evidence" / "jhoc-p1-boundary-r5" / "review_r5_summary.json"
R5_REVIEW_COMMIT = "15a5986"
OUT_DIR = ROOT / "docs" / "acceptance" / "p21"
OUT_JSON = OUT_DIR / "p21_cutover_approval_checklist.json"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise SystemExit(f"git failed: {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout.strip()


def _p19_canonical_hash(record: dict) -> str:
    """Canonical digest over the approved migration content.

    Covers the approval identity, the staged manifest and the actual imports,
    so any change to the imported set invalidates the cutover binding.
    """
    payload = {
        "formal_approval": record.get("formal_approval"),
        "staging_manifest": record.get("staging_manifest"),
        "imports": record.get("imports"),
        "approver": {
            "identity_type": record["approver"].get("identity_type"),
            "subject": record["approver"].get("subject"),
            "permission": record["approver"].get("permission"),
            "approved_at_utc": record["approver"].get("approved_at_utc"),
        },
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def main() -> int:
    if not P19_RECORD.is_file():
        raise SystemExit("P19 formal import record is missing; cutover cannot be prepared")
    p19 = json.loads(P19_RECORD.read_text(encoding="utf-8"))
    if not p19.get("formal_approval"):
        raise SystemExit("P19 formal approval is not recorded; cutover cannot be prepared")

    record_hash = _p19_canonical_hash(p19)
    freeze_hash = _sha256_file(FREEZE)
    entrypoint = EntrypointProof.from_file(
        "jhoc.entrypoint:create_application", ROOT / "src" / "jhoc" / "entrypoint.py"
    )

    r5 = json.loads(R5_SUMMARY.read_text(encoding="utf-8"))
    review_ok = bool(r5.get("passed")) and r5.get("total_p0") == 0 and r5.get("total_p1") == 0

    head = _git("rev-parse", "HEAD")
    tree = _git("rev-parse", "HEAD^{tree}")
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    dirty = _git("status", "--porcelain")
    boundary_drift = _git("diff", "--stat", R5_REVIEW_COMMIT, "HEAD", "--", "src", "tests")

    # Fixed archive id: the checklist is regenerated after each commit, but
    # the archive identity must stay stable so the approval binds to a
    # content-addressed object, not a generation timestamp.
    # created_at is pinned to the operator's P19 approval time (content-bound,
    # not generation-bound) so the digest is reproducible.
    approved_at = datetime.fromisoformat(p19["approver"]["approved_at_utc"])
    archive = ArchiveManifest(
        archive_id="jhoc-formal-archive-v1",
        source_manifest_hash=freeze_hash,
        entries=("aibox-memory", "aibox-knowledge", "vers-rules", "desktop-agent"),
        created_at=approved_at,
        migration_manifest_hash=record_hash,
    )

    checklist = {
        "checklist_version": "1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "project": "JHOC",
        "gate": "USER_CUTOVER_APPROVAL",
        "mode": "READ_ONLY_APPROVAL_PACKAGE",
        "git": {
            "branch": branch,
            "head_commit": head,
            "tree_hash": tree,
            "working_tree_clean": not dirty,
            "boundary_diff_since_r5_review_commit": boundary_drift or "(none)",
            "r5_review_commit": R5_REVIEW_COMMIT,
        },
        "unique_entrypoint": entrypoint.to_dict(),
        "p19_migration": {
            "record_path": "docs/acceptance/p19/p19_formal_import_record.json",
            "canonical_sha256": record_hash,
            "imports": p19.get("imports", []),
            "referenced_items": p19.get("referenced_items"),
            "rejected_items": p19.get("rejected_items"),
        },
        "legacy_freeze": {
            "manifest_path": "docs/acceptance/artifacts/jhoc-legacy-readonly-freeze.json",
            "sha256": freeze_hash,
        },
        "p1_review": {
            "round": r5.get("round"),
            "summary_path": "docs/acceptance/evidence/jhoc-p1-boundary-r5/review_r5_summary.json",
            "passed": r5.get("passed"),
            "avg_score": r5.get("avg_score"),
            "total_p0": r5.get("total_p0"),
            "total_p1": r5.get("total_p1"),
            "online_models": r5.get("online_models"),
            "acceptance_ok": review_ok,
        },
        "archive_manifest": archive.to_dict(),
        "archive_digest": archive.digest,
        "approval_requirements": {
            "approver": "Trust USER identity holding permission ops.cutover",
            "binding_fields": {
                "archive_id": archive.archive_id,
                "archive_digest": archive.digest,
                "migration_manifest_hash": record_hash,
                "entrypoint_sha256": entrypoint.source_sha256,
            },
            "approval_version": "1",
            "semantics": [
                "JHOC becomes the only runtime entry (the unique entrypoint below).",
                "Legacy AIBOX / VERS / Agent Bus sources become read-only archives; no runtime dependency is introduced.",
                "The exact archive manifest, migration record, entrypoint and reviewed tree in this package are the approved objects.",
                "Recording the approval closes the last formal release gate (fail-closed until then).",
            ],
        },
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(checklist, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "out": str(OUT_JSON),
                "archive_id": archive.archive_id,
                "archive_digest": archive.digest,
                "migration_manifest_hash": record_hash,
                "entrypoint_sha256": entrypoint.source_sha256,
                "head_commit": head,
                "review_ok": review_ok,
                "working_tree_clean": not dirty,
                "boundary_drift": bool(boundary_drift),
            },
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
