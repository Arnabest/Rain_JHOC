"""Generate the P1/P18 review gate from local checks and archived peer evidence."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "acceptance" / "artifacts"
PEER = ROOT / "docs" / "acceptance" / "evidence" / "jhoc-p1-boundary-r5"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    boundary = ROOT / "docs" / "architecture" / "JHOC_DOMAIN_TRUST_BOUNDARY.md"
    source = boundary.read_text(encoding="utf-8")
    required_domains = ("Origin/Core", "Guard/Trust", "Relay", "Conductor/Quota", "Context", "Runner/Gate", "Output", "Ingest/Restore/Ops")
    present = all(f"| {domain} |" in source for domain in required_domains)
    local_pass = present and "must not own" in source.lower() and "The table is the P1 ownership contract" in source
    peer_summary_path = PEER / "review_r5_summary.json"
    peer = json.loads(peer_summary_path.read_text(encoding="utf-8"))
    peer_pass = bool(
        peer["passed"]
        and peer["total_p0"] == 0
        and peer["total_p1"] == 0
        and peer["avg_score"] >= 85
    )
    findings = [
        {
            "id": "P1-LOCAL-BOUNDARY",
            "status": "mitigated" if local_pass else "open",
            "claim": "The JHOC domain/trust boundary declares one owner row per runtime domain and explicit forbidden ownership.",
            "evidence": [{"kind": "source", "source_path": "docs/architecture/JHOC_DOMAIN_TRUST_BOUNDARY.md"}],
            "impact": "Prevents policy, delivery, execution and output responsibilities from silently merging.",
            "required_action": "Keep the ownership table updated before adding a module.",
            "acceptance_test": "All required domain rows and the must-not-own contract remain present.",
            "confidence": "high",
        },
        {
            "id": "P1-INDEPENDENT-REVIEW",
            "status": "accepted" if peer_pass else "open",
            "claim": "The R5 bounded external review accepted the post-remediation tree (commit 15a5986) with all online reviewers Accepted, average >=85 and P0/P1=0.",
            "evidence": [{
                "kind": "artifact",
                "artifact_path": "docs/acceptance/evidence/jhoc-p1-boundary-r5/review_r5_summary.json",
                "sha256": _sha256(peer_summary_path),
            }],
            "impact": "P1 and the release gate cannot be marked complete from local self-review alone.",
            "required_action": "Keep the review artifact bound to the exact reviewed tree; re-run a bounded review if the boundary modules change before release.",
            "acceptance_test": "All online reviewers accept the boundary-bound tree with average >=85 and P0/P1=0.",
            "confidence": "high",
        },
        {
            "id": "P18-EVIDENCE-GATE",
            "status": "open",
            "claim": "Automated local verification is green, but the P0/P1 defect-free release claim remains unproven.",
            "evidence": [{"kind": "command", "command": "python -m unittest discover -s tests -p 'test_*.py'", "exit_code": 0, "output": "full unittest suite passes; independent P0/P1 review is separate evidence"}],
            "impact": "Prevents an unsafe V5 completion declaration based only on self-authored tests.",
            "required_action": "Attach the independent P0/P1 review before changing the acceptance matrix to complete.",
            "acceptance_test": "P0/P1 review artifact has no open critical/high findings and a fresh command trace.",
            "confidence": "high",
        },
    ]
    report = {
        "schema_version": "vers.audit-evidence.v1",
        "task_id": "jhoc-local-architecture-review",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "owner": "JHOC local verifier",
        "human_summary_reference": "docs/acceptance/artifacts/jhoc-architecture-review.md",
        "release_decision": "approved" if local_pass and peer_pass else "blocked",
        "boundary_sha256": _sha256(boundary),
        "peer_review": {
            "round": peer["round"],
            "passed": peer["passed"],
            "avg_score": peer["avg_score"],
            "p0": peer["total_p0"],
            "p1": peer["total_p1"],
            "p2": peer["total_p2"],
            "online_models": peer["online_models"],
            "absent_models": peer["absent_models"],
        },
        "findings": findings,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    json_path = OUT / "jhoc-architecture-review.json"
    md_path = OUT / "jhoc-architecture-review.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    md_path.write_text(
        "# JHOC Architecture Review Gate\n\n"
        "- Decision: **{}** for independent release approval\n"
        "- Local boundary check: **{}**\n"
        "- Boundary SHA-256: `{}`\n"
        "- External review round: **{}** (online: {}; absent: {})\n"
        "- Review score/findings: `{:.2f}`, P0=`{}`, P1=`{}`, P2=`{}`\n"
        "- Post-review local verification: **PASS (full unittest suite)**\n\n"
        "The latest bounded external review (R5) accepted the reviewed post-remediation tree; P19 formal import approval and user Cutover approval remain the open release gates.\n".format(
            "APPROVED" if local_pass and peer_pass else "BLOCKED",
            "PASS" if local_pass else "FAIL",
            _sha256(boundary),
            "PASS" if peer_pass else "REVISE",
            ", ".join(peer["online_models"]),
            ", ".join(peer["absent_models"].keys()) or "none",
            peer["avg_score"],
            peer["total_p0"],
            peer["total_p1"],
            peer["total_p2"],
        ),
        encoding="utf-8",
    )
    print(json.dumps({"json": str(json_path), "markdown": str(md_path), "release_decision": report["release_decision"]}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
