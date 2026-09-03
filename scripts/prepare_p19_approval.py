"""P19 formal import approval package generator (read-only).

Scans configured legacy source roots, records per-file SHA-256 digests and
sizes, applies proposed dispositions/target mappings, and emits an approval
checklist for USER sign-off. This script NEVER imports, copies or transforms
any legacy content: production import stays fail-closed behind
P19_FORMAL_IMPORT_APPROVAL until the user approves each item explicitly.

Usage:
    python scripts/prepare_p19_approval.py --config docs/acceptance/p19/p19_sources.json
    python scripts/prepare_p19_approval.py --config <cfg> --out docs/acceptance/p19/p19_approval_checklist.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jhoc.ingest.manifest import Disposition  # noqa: E402

TARGET_STORES = {
    "UserMemory": "memory",
    "ProjectMemory": "memory",
    "TaskMemory": "memory",
    "ErrorMemory": "memory",
    "ExperienceMemory": "memory",
    "FACT": "atlas",
    "RULE_REFERENCE": "atlas",
    "PROJECT_KNOWLEDGE": "atlas",
    "OBSERVATION": "atlas",
    "EVIDENCE": "atlas",
    "MODEL_CAPABILITY": "atlas",
}

ALLOWED_DISPOSITIONS = {d.value for d in Disposition}


def _load_config(config_path: Path) -> dict[str, Any]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if "source_roots" not in config or not isinstance(config["source_roots"], list):
        raise SystemExit("config must define source_roots as a list")
    for root in config["source_roots"]:
        for field in ("scope", "path", "files"):
            if field not in root:
                raise SystemExit(f"source root missing '{field}': {root}")
        for item in root["files"]:
            for field in ("relative_path", "disposition"):
                if field not in item:
                    raise SystemExit(f"file entry missing '{field}': {item}")
            if item["disposition"] not in ALLOWED_DISPOSITIONS:
                raise SystemExit(f"invalid disposition: {item['disposition']}")
    return config


def _resolve(root_path: str, relative_path: str) -> Path:
    from jhoc.ingest.migration import OfflineMigration

    return OfflineMigration._safe_source_path(Path(root_path), relative_path)


def build_checklist(config_path: Path) -> dict[str, Any]:
    config = _load_config(config_path)
    groups = []
    for root in config["source_roots"]:
        entries = []
        for item in root["files"]:
            source = _resolve(root["path"], item["relative_path"])
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            entry = {
                "relative_path": item["relative_path"],
                "absolute_path": str(source),
                "size": source.stat().st_size,
                "sha256": digest,
                "disposition": item["disposition"],
                "proposed_target_type": item.get("target_type"),
                "proposed_target_store": (
                    TARGET_STORES.get(item.get("target_type") or "", "reference-only")
                    if item.get("target_type")
                    else None
                ),
                "sensitivity": item.get("sensitivity", "INTERNAL"),
                "user_approval": None,
            }
            if item["disposition"] in ("MIGRATE", "TRANSFORM") and item.get("target_type") not in TARGET_STORES:
                raise SystemExit(
                    f"migratable item requires a known target type: {item['relative_path']}"
                )
            entries.append(entry)
        groups.append(
            {
                "scope": root["scope"],
                "source_root": root["path"],
                "entries": entries,
            }
        )
    return {
        "checklist_version": "1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "generated_by": "scripts/prepare_p19_approval.py",
        "project": "JHOC",
        "gate": "P19_FORMAL_IMPORT_APPROVAL",
        "mode": "READ_ONLY_APPROVAL_PACKAGE",
        "groups": groups,
        "note": (
            "All entries are read-only scans. 'user_approval' stays null until the "
            "operator approves each item; nothing is imported, copied or transformed."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="P19 approval package generator (read-only)")
    parser.add_argument("--config", required=True, help="source definition JSON")
    parser.add_argument("--out", default=None, help="output checklist path")
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = ROOT / config_path
    checklist = build_checklist(config_path)

    out_path = Path(args.out) if args.out else ROOT / "docs" / "acceptance" / "p19" / "p19_approval_checklist.json"
    if not out_path.is_absolute():
        out_path = ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(checklist, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    total = sum(len(group["entries"]) for group in checklist["groups"])
    migratable = sum(
        1
        for group in checklist["groups"]
        for entry in group["entries"]
        if entry["disposition"] in ("MIGRATE", "TRANSFORM")
    )
    print(
        json.dumps(
            {
                "out": str(out_path),
                "scopes": len(checklist["groups"]),
                "files": total,
                "migratable": migratable,
                "user_approval_pending": total,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
