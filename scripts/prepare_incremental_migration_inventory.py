"""Create a read-only inventory for the next JHOC migration batch.

This tool only records file metadata. It never copies, transforms, imports,
deletes, or changes AI Box/Verse source files. The privacy-protected
``user-profile-learning`` tree is excluded without enumeration.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.execute_incremental_import import select_entry

DEFAULT_OUTPUT = ROOT / "docs" / "migration" / "jhoc-incremental-inventory-20260902.json"


class InventoryError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _classify(scope: str, relative: str) -> tuple[str, str]:
    """Return disposition and rationale; no category implies auto-import."""
    normalized = relative.replace("\\", "/")
    lower = normalized.lower()

    # 1. Already selected and imported into JHOC native stores
    sel = select_entry(scope, relative)
    if sel is not None:
        return "ALREADY_IMPORTED", f"imported into JHOC {sel[0]}: {sel[1]}"

    # 2. P19 initial formal imports
    if scope == "aibox-memory" and normalized == "MEMORY.md":
        return "ALREADY_IMPORTED", "P19 transformed import exists in JHOC Memory"
    if scope == "aibox-knowledge" and normalized == "ai-model-catalog.json":
        return "ALREADY_IMPORTED", "P19 transformed import exists in JHOC Atlas"

    # 3. Explicit quarantine
    if scope == "aibox-memory" and lower == "quantum_phase_memory.json":
        return "EXPLICIT_QUARANTINE", "P19 classified quantum phase memory as quarantine pending separate review"

    # 4. Runtime residue, locks, pycache, temporary files
    if any(part in {"__pycache__", ".pytest_cache"} for part in lower.split("/")) or lower.endswith((".pyc", ".pyo")):
        return "EXCLUDED_RUNTIME_CACHE", "interpreter cache is runtime residue, not migration data"
    if lower.rsplit("/", 1)[-1] in {"lock", "current", "singletonlock"} or lower.endswith(".lock"):
        return "EXCLUDED_RUNTIME_CACHE", "process lock/marker is runtime residue, not migration data"
    if scope == "verse-data":
        if lower.startswith("browser_profile/") or lower.endswith((".wav", ".events.jsonl")):
            return "EXCLUDED_RUNTIME_CACHE", "browser profile/cache/audio/event stream is runtime residue, not migration data"
        return "REFERENCE_ONLY_RETAIN_SOURCE", "historical verse-data remains reference only outside runtime"

    # 5. Reference-only retained sources (V5 immutable constraints)
    if scope in {"aibox-intercom", "aibox-op-log", "aibox-global", "aibox-skills", "verse-skills"}:
        return "REFERENCE_ONLY_RETAIN_SOURCE", "historical skill, intercom, audit log or rule source remains outside runtime ownership per V5 constraint"
    if scope == "verse-memory":
        if lower == "backups" or lower.startswith("backups/"):
            return "REFERENCE_ONLY_RETAIN_SOURCE", "backup snapshots remain recovery sources until separately approved"
        return "REFERENCE_ONLY_RETAIN_SOURCE", "legacy Verse scripts, conversation states and payloads remain reference only"
    if scope == "aibox-memory":
        return "REFERENCE_ONLY_RETAIN_SOURCE", "legacy token statistics and archive records remain reference only"
    if scope == "aibox-knowledge":
        return "REFERENCE_ONLY_RETAIN_SOURCE", "historical memetic experiments and candidate ledgers remain reference only"

    return "REVIEW_REQUIRED", "requires a new per-item disposition and operator approval"


def _scan(scope: str, source_root: Path) -> dict[str, Any]:
    root = source_root.resolve()
    if not root.is_dir():
        return {
            "scope": scope,
            "source_root": str(root),
            "status": "ABSENT",
            "file_count": 0,
            "total_bytes": 0,
            "disposition_counts": {},
            "entries": [],
        }
    entries: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file() and ".git" not in item.parts):
        relative = path.relative_to(root).as_posix()
        try:
            size = path.stat().st_size
            disposition, rationale = _classify(scope, relative)
            # Cache/lock entries are intentionally not read; they are not
            # candidate migration data and may be held open by the runtime.
            digest = None if disposition == "EXCLUDED_RUNTIME_CACHE" else _sha256(path)
        except (OSError, RuntimeError) as exc:
            errors.append({"relative_path": relative, "error": type(exc).__name__})
            continue
        entries.append({
            "relative_path": relative,
            "size": size,
            "sha256": digest,
            "disposition": disposition,
            "rationale": rationale,
        })
    counts = Counter(entry["disposition"] for entry in entries)
    return {
        "scope": scope,
        "source_root": str(root),
        "status": "SCANNED",
        "file_count": len(entries),
        "total_bytes": sum(entry["size"] for entry in entries),
        "disposition_counts": dict(sorted(counts.items())),
        "error_count": len(errors),
        "errors": errors,
        "entries": entries,
    }


def build_inventory() -> dict[str, Any]:
    roots = [
        ("aibox-memory", Path(r"D:\AI Box\memory")),
        ("aibox-knowledge", Path(r"D:\AI Box\knowledge")),
        ("aibox-intercom", Path(r"D:\AI Box\intercom")),
        ("aibox-op-log", Path(r"D:\AI Box\op-log")),
        ("aibox-global", Path(r"D:\AI Box\global")),
        ("aibox-skills", Path(r"D:\AI Box\skills")),
        ("verse-memory", Path(r"D:\AI Desktop Agent\memory")),
        ("verse-data", Path(r"D:\AI Desktop Agent\data")),
        ("verse-skills", Path(r"D:\AI Desktop Agent\skills")),
    ]
    scopes = [_scan(scope, root) for scope, root in roots]
    return {
        "schema_version": "jhoc.migration-inventory.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "project": "JHOC",
        "mode": "READ_ONLY_METADATA_ONLY",
        "privacy_exclusions": [
            {
                "path": r"D:\AI Box\user-profile-learning",
                "reason": "Ironclad Privacy: local perception/profile learning data is not enumerated or summarized",
            },
            {
                "path": r"D:\AI Desktop Agent\app",
                "reason": "Verse runtime code is not migration data and must not be copied into JHOC",
            },
            {
                "path": r"D:\AI Box\intercom\*.json",
                "reason": "intercom state and task history remain historical source data until separately approved",
            },
        ],
        "scopes": scopes,
        "next_gate": "Create a new per-item migration approval manifest for entries marked REVIEW_REQUIRED; this inventory is not an import approval.",
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# JHOC Incremental Migration Inventory",
        "",
        f"- Generated: `{report['generated_at_utc']}`",
        "- Mode: **read-only metadata-only**",
        "- This report is an inventory, not an import approval.",
        "",
        "## Scope Summary",
        "",
        "| Scope | Status | Files | Bytes | Disposition counts |",
        "|---|---|---:|---:|---|",
    ]
    for item in report["scopes"]:
        counts = ", ".join(f"{key}={value}" for key, value in item["disposition_counts"].items()) or "-"
        lines.append(f"| `{item['scope']}` | {item['status']} | {item['file_count']} | {item['total_bytes']} | {counts} |")
    lines.extend([
        "",
        "## Required Boundary",
        "",
        "Entries marked `REVIEW_REQUIRED` need a separate disposition, semantic validation, Trust-bound operator approval, and owner-store reconciliation before import.",
        "",
        "The `user-profile-learning` directory, Verse runtime code, credentials, and intercom state are excluded from this scan and remain on their source systems.",
        "",
        "## Next Action",
        "",
        report["next_gate"],
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = build_inventory()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    markdown = output.with_suffix(".md")
    markdown.write_text(_markdown(report), encoding="utf-8")
    summary = {
        "report": str(output),
        "markdown": str(markdown),
        "scopes": len(report["scopes"]),
        "files_scanned": sum(item["file_count"] for item in report["scopes"]),
        "review_required": sum(item["disposition_counts"].get("REVIEW_REQUIRED", 0) for item in report["scopes"]),
        "privacy_exclusions": len(report["privacy_exclusions"]),
    }
    print(json.dumps(summary, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
