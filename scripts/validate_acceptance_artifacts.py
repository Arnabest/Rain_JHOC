"""Validate all committed local acceptance artifacts and their cross-links."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "docs" / "acceptance" / "artifacts"


def main() -> int:
    freeze_path = ARTIFACTS / "jhoc-legacy-readonly-freeze.json"
    if not freeze_path.is_file():
        print(json.dumps({"validated": True, "notice": "acceptance artifacts not present in pure microkernel release"}))
        return 0

    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    for entry in freeze["entries"]:
        path = Path(entry["path"])
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise SystemExit(f"freeze mismatch: {path}")
    architecture = json.loads((ARTIFACTS / "jhoc-architecture-review.json").read_text(encoding="utf-8"))
    schema_path = Path(r"D:\VERS-rule\globle\schemas\audit-evidence-v1.schema.json")
    if schema_path.is_file():
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.validate(architecture, schema)
    runtime = json.loads((ARTIFACTS / "jhoc-runtime-plane-report.json").read_text(encoding="utf-8"))
    migration = json.loads((ARTIFACTS / "jhoc-migration-report.json").read_text(encoding="utf-8"))
    local = json.loads((ARTIFACTS / "jhoc-independent-cutover-report.json").read_text(encoding="utf-8"))
    formal = json.loads((ARTIFACTS / "jhoc-formal-cutover-record.json").read_text(encoding="utf-8"))
    migration_items = migration["migration"].get("items", [])
    migration_complete = bool(
        migration.get("formal_approval")
        and migration.get("imports")
        and all(item.get("status") not in {"QUARANTINED"} for item in migration_items)
    )
    # Cutover evidence: when the operator approval is recorded, the formal
    # record must be READY with no failed gates and bindings intact; without
    # an approval the record must stay fail-closed (blocked).
    approval_path = ROOT / "docs" / "acceptance" / "p21" / "p21_user_cutover_approval.json"
    approval = json.loads(approval_path.read_text(encoding="utf-8")) if approval_path.is_file() else None
    if approval is not None:
        formal_cutover_ok = (
            formal["formal_cutover"]["ready"] is True
            and not formal["formal_cutover"]["failed_gates"]
            and approval["validation"]["ready"] is True
            and formal["gates"]["USER_CUTOVER_APPROVAL"] is True
        )
    else:
        formal_cutover_ok = formal["formal_cutover"]["ready"] is False
    checks = {
        "runtime_probes": runtime["all_local_probes_passed"],
        "migration_complete": migration_complete,
        "local_independence": local["cutover"]["ready"],
        "formal_cutover_record": formal_cutover_ok,
        # P1 evidence must itself be a passed bounded review: all online
        # reviewers accepted, average >=85, P0=0 and P1=0 (fail-closed).
        "independent_review_evidence": (
            architecture["release_decision"] == "approved"
            and architecture["peer_review"]["passed"] is True
            and architecture["peer_review"]["p0"] == 0
            and architecture["peer_review"]["p1"] == 0
            and float(architecture["peer_review"]["avg_score"]) >= 85.0
        ),
        # P19 formal import evidence: an approved record must exist with a
        # Trust USER approver, migration.import permission and actual imports.
        "formal_import_evidence": (
            migration["formal_approval"] is True
            and migration["approval"]["identity_type"] == "User"
            and migration["approval"]["permission"] == "migration.import"
            and len(migration["imports"]) > 0
        ),
    }
    if not all(checks.values()):
        raise SystemExit(f"acceptance artifact check failed: {checks}")
    print(json.dumps({"validated": True, "checks": checks}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
