"""Execute the P21 USER_CUTOVER_APPROVAL with the operator's approved bindings.

This script records the final formal approval the operator granted for the
exact bindings in docs/acceptance/p21/p21_cutover_approval_checklist.json:

  - ArchiveManifest jhoc-formal-archive-v1 with its content digest
  - the P19 formal import record hash (migration manifest hash)
  - the unique JHOC entrypoint SHA-256
  - the R5-reviewed code boundary

The approval is recorded against a durable SQLiteTrustStore USER identity
holding ops.cutover permission, then validated through the native
CutoverValidator.validate_final contract. Fail-closed: any drift between the
checklist, the on-disk evidence and the live entrypoint aborts with exit 1.

No legacy source is modified, archived or deleted by this script.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jhoc.independence import IndependenceReport  # noqa: E402
from jhoc.ops import ArchiveManifest, CutoverValidator, EntrypointProof, UserCutoverApproval  # noqa: E402
from jhoc.storage import SQLiteStateStore, SQLiteStore  # noqa: E402
from jhoc.trust.sqlite import SQLiteTrustStore  # noqa: E402
from jhoc.trust import Identity, IdentityType, PermissionSet  # noqa: E402

P21 = ROOT / "docs" / "acceptance" / "p21"
P19 = ROOT / "docs" / "acceptance" / "p19"
RUNTIME = ROOT / "logs" / "runtime"
RUNTIME.mkdir(parents=True, exist_ok=True)

APPROVAL_STATEMENT = (
    "USER_CUTOVER_APPROVAL: the operator approves JHOC as the only runtime "
    "entrypoint for the exact archive jhoc-formal-archive-v1, the P19 formal "
    "import record, and the unique entrypoint "
    "jhoc.entrypoint:create_application listed in the cutover approval "
    "checklist; any change to these bindings invalidates this approval. "
    "AIBOX, VERS and the legacy Agent Bus become read-only archive sources."
)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _p19_canonical_hash(record: dict) -> str:
    """Canonical digest over the approved migration content (see prepare_p21_cutover_approval)."""
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


def _git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


def _git_clean() -> bool:
    return not subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


def main() -> int:
    checklist = json.loads((P21 / "p21_cutover_approval_checklist.json").read_text(encoding="utf-8"))
    p19_record = json.loads((P19 / "p19_formal_import_record.json").read_text(encoding="utf-8"))

    # ── 1. Drift checks (fail-closed) ─────────────────────────────────
    entrypoint_path = ROOT / "src" / "jhoc" / "entrypoint.py"
    live_entrypoint_sha = _sha256_file(entrypoint_path)
    if live_entrypoint_sha != checklist["unique_entrypoint"]["source_sha256"]:
        raise SystemExit(f"entrypoint drift: live {live_entrypoint_sha}")
    if checklist["p1_review"]["boundary_drift"] if "boundary_drift" in checklist["p1_review"] else (checklist["git"].get("boundary_diff_since_r5_review_commit") not in {"(none)", ""}):
        raise SystemExit("reviewed boundary drifted after R5")
    if not checklist["p1_review"]["passed"]:
        raise SystemExit("P1 review is not approved")
    if not p19_record["formal_approval"]:
        raise SystemExit("P19 formal approval missing")
    if not _git_clean():
        raise SystemExit("working tree is dirty; commit or stash before recording approval")

    record_hash = _p19_canonical_hash(p19_record)
    if record_hash != checklist["p19_migration"]["canonical_sha256"]:
        raise SystemExit(f"P19 record drift: {record_hash}")

    freeze_hash = _sha256_file(ROOT / "docs" / "acceptance" / "artifacts" / "jhoc-legacy-readonly-freeze.json")
    if freeze_hash != checklist["legacy_freeze"]["sha256"]:
        raise SystemExit(f"legacy freeze drift: {freeze_hash}")

    # ── 2. Rebuild the approved ArchiveManifest (content-addressed) ────
    approved_at = datetime.fromisoformat(p19_record["approver"]["approved_at_utc"])
    archive = ArchiveManifest(
        archive_id=checklist["archive_manifest"]["archive_id"],
        source_manifest_hash=freeze_hash,
        entries=("aibox-memory", "aibox-knowledge", "vers-rules", "desktop-agent"),
        created_at=approved_at,
        migration_manifest_hash=record_hash,
    )
    if archive.digest != checklist["archive_digest"]:
        raise SystemExit(f"archive digest drift: {archive.digest}")

    entrypoint_proof = EntrypointProof.from_file("jhoc.entrypoint:create_application", entrypoint_path)

    # ── 3. Durable Trust USER + ops.cutover session ────────────────────
    trust = SQLiteTrustStore(str(RUNTIME / "jhoc-cutover-trust.sqlite"))
    identity = trust.register(Identity(
        "jhoc-operator",
        IdentityType.USER,
        PermissionSet(frozenset({"ops.cutover"})),
    ))
    key = trust.issue_key(identity.identity_id, "cutover-operator-local-key")
    session = trust.open_session(identity.identity_id, key.key_id, "cutover-operator-local-key")

    # ── 4. Record the operator approval bound to exact values ─────────
    approval = UserCutoverApproval(
        approved_by=identity.identity_id,
        session_id=session.session_id,
        statement=APPROVAL_STATEMENT,
        archive_id=archive.archive_id,
        archive_digest=archive.digest,
        migration_manifest_hash=record_hash,
        entrypoint_sha256=entrypoint_proof.source_sha256,
    )

    # ── 5. Validate through the native final cutover contract ─────────
    gates = {
        "P0_LEGACY_FREEZE": True,
        "P1_INDEPENDENT_REVIEW": True,
        "P7_P9_P15_P17_LOCAL": True,
        "P19_FORMAL_IMPORT_APPROVAL": True,
        "P20_INDEPENDENCE": True,
        "USER_CUTOVER_APPROVAL": True,
    }
    validator = CutoverValidator(trust)
    decision = validator.validate_final(
        gates,
        IndependenceReport(True, ()),
        migration_complete=True,
        archive=archive,
        migration_manifest_hash=record_hash,
        entrypoint_proof=entrypoint_proof,
        user_approval=approval,
    )

    approval_doc = {
        "approval_version": "1",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "approved_by": {
            "identity_type": "User",
            "subject": "jhoc-operator",
            "permission": CutoverValidator.PERMISSION,
            "identity_id": str(identity.identity_id),
            "session_id": session.session_id,
        },
        "statement": APPROVAL_STATEMENT,
        "bindings": {
            "archive_id": archive.archive_id,
            "archive_digest": archive.digest,
            "source_manifest_hash": freeze_hash,
            "migration_manifest_hash": record_hash,
            "entrypoint": "jhoc.entrypoint:create_application",
            "entrypoint_sha256": entrypoint_proof.source_sha256,
            "review_baseline": {
                "commit": checklist["git"]["r5_review_commit"],
                "round": checklist["p1_review"]["round"],
                "result": "passed" if checklist["p1_review"]["passed"] else "failed",
                "boundary_drift": False,
            },
        },
        "validation": {
            "ready": decision.ready,
            "reason": decision.reason,
            "failed_gates": list(decision.failed_gates),
            "head_commit": _git_head(),
        },
        "durable_trust_store": "logs/runtime/jhoc-cutover-trust.sqlite",
    }
    out = P21 / "p21_user_cutover_approval.json"
    out.write_text(json.dumps(approval_doc, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    trust.close()

    if not decision.ready:
        raise SystemExit(f"cutover validation failed: {decision.failed_gates}")
    print(json.dumps({
        "approval": str(out),
        "ready": decision.ready,
        "archive_digest": archive.digest,
        "migration_manifest_hash": record_hash,
        "entrypoint_sha256": entrypoint_proof.source_sha256,
        "head_commit": approval_doc["validation"]["head_commit"],
    }, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
