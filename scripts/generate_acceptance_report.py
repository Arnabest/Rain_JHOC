"""Generate reproducible P20/P21 local acceptance artifacts."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUT = ROOT / "docs" / "acceptance" / "artifacts"
sys.path.insert(0, str(SRC))

from jhoc.independence import check_source  # noqa: E402
from jhoc.ingest import Disposition, IngestScanner, OfflineMigration  # noqa: E402
from jhoc.ops import ArchiveManifest, CutoverValidator, EntrypointProof  # noqa: E402


def _fresh_process() -> dict[str, object]:
    env = {key: value for key, value in os.environ.items() if all(token not in key.upper() for token in ("AIBOX", "VERS", "AGENT_BUS"))}
    forbidden = tuple(str(path).lower() for path in (Path(r"D:\AI Box"), Path(r"D:\VERS-rule"), Path(r"D:\AI Desktop Agent")))
    code = (
        f"import sys; sys.path.insert(0, {str(SRC)!r}); forbidden={forbidden!r}\n"
        "def audit(event,args):\n"
        "  if event == 'open' and args and any(str(args[0]).lower().startswith(item) for item in forbidden): raise PermissionError('legacy path denied')\n"
        "  if event.startswith('socket.'): raise PermissionError('network denied')\n"
        "sys.addaudithook(audit)\n"
        "from jhoc.entrypoint import create_application\n"
        "app=create_application(); health=app.start(); print(health.running, health.legacy_runtime_connected); app.stop()"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
    return {
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
        "passed": result.returncode == 0 and result.stdout.strip() == "True False",
        "isolation": {"legacy_paths": list(forbidden), "network": "DENIED_BY_AUDIT_HOOK"},
    }


def main() -> int:
    source_report = check_source(SRC)
    fresh = _fresh_process()
    source_manifest = IngestScanner().scan(SRC)
    reviewed_manifest = source_manifest.with_dispositions({entry.relative_path: Disposition.REFERENCE_ONLY for entry in source_manifest.entries})
    with tempfile.TemporaryDirectory(prefix="jhoc-migration-") as quarantine:
        migration = OfflineMigration().run(reviewed_manifest, quarantine)
    archive = ArchiveManifest(
        "jhoc-local-archive-v1", source_manifest.source_hash,
        ("runtime-state", "proof", "relay-delivery"), migration_manifest_hash=reviewed_manifest.manifest_hash,
    )
    entrypoint_proof = EntrypointProof.from_file(
        "jhoc.entrypoint:create_application", SRC / "jhoc" / "entrypoint.py"
    )
    cutover = CutoverValidator().validate_prerequisites(
        {"P0-P19": True}, source_report,
        migration_complete=migration.complete,
        archive=archive if source_report.passed and fresh["passed"] else None,
        migration_manifest_hash=reviewed_manifest.manifest_hash,
        entrypoint_proof=entrypoint_proof,
    )
    report = {
        "report_version": "1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project": "JHOC",
        "source_root": str(ROOT),
        "independence": {"passed": source_report.passed, "violations": list(source_report.violations)},
        "fresh_process": fresh,
        "migration": migration.to_dict(),
        "archive_manifest": archive.to_dict(),
        "entrypoint_proof": entrypoint_proof.to_dict(),
        "unique_entrypoint_proof": entrypoint_proof.entrypoint,
        "cutover": {"ready": cutover.ready, "reason": cutover.reason, "failed_gates": list(cutover.failed_gates)},
        "release_claim": "P20/P21 local evidence only; full V5 release remains gated by the acceptance matrix.",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    json_path = OUT / "jhoc-independent-cutover-report.json"
    md_path = OUT / "jhoc-independent-cutover-report.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    md_path.write_text(
        "# JHOC Independent Runtime And Cutover Report\n\n"
        f"- Generated: `{report['generated_at']}`\n"
        f"- Independence scan: **{'PASS' if source_report.passed else 'FAIL'}**\n"
        f"- Fresh process with legacy environment removed: **{'PASS' if fresh['passed'] else 'FAIL'}**\n"
        f"- Offline migration: **{'PASS' if migration.complete else 'BLOCKED'}** ({len(migration.items)} items; manifest `{migration.manifest_hash}`)\n"
        f"- Local Archive Manifest: `{archive.archive_id}`\n"
        f"- Unique entrypoint proof: `{report['unique_entrypoint_proof']}`\n"
        f"- P20/P21 local decision: **{'READY' if cutover.ready else 'BLOCKED'}**\n\n"
        "This artifact is limited to local independence and cutover prerequisites. It does not claim full V5 completion.\n",
        encoding="utf-8",
    )
    print(json.dumps({"json": str(json_path), "markdown": str(md_path), "cutover_ready": cutover.ready}, ensure_ascii=True))
    return 0 if cutover.ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
