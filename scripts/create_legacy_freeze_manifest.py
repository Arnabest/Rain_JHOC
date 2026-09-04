"""Create/verify a read-only hash manifest for selected legacy control files."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
TARGETS = (
    ("desktop-agent", Path(r"D:\AI Desktop Agent\README.md")),
    ("desktop-agent", Path(r"D:\AI Desktop Agent\PROJECT_RULES.md")),
    ("desktop-agent", Path(r"D:\AI Desktop Agent\memory\MEMORY.md")),
    ("aibox", Path(r"D:\AI Box\README.md")),
    ("aibox", Path(r"D:\AI Box\global\universal-working-rules.md")),
    ("aibox", Path(r"D:\AI Box\global\universal-error-log.md")),
    ("aibox", Path(r"D:\AI Box\memory\MEMORY.md")),
)


def _entry(scope: str, path: Path) -> dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(path)
    data = path.read_bytes()
    return {"scope": scope, "path": str(path), "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def build_manifest() -> dict[str, object]:
    entries = [_entry(scope, path) for scope, path in TARGETS]
    return {
        "manifest_version": "1",
        "project": "JHOC",
        "freeze_mode": "READ_ONLY_HASH_ONLY",
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "entries": entries,
        "provenance": "Selected legacy control-plane files only; no runtime databases, credentials, user-learning data or source copies.",
    }


def verify(manifest: dict[str, object]) -> tuple[bool, list[str]]:
    errors = []
    for entry in manifest.get("entries", []):
        path = Path(str(entry["path"]))
        if not path.is_file():
            errors.append(f"missing:{path}")
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != entry["sha256"]:
            errors.append(f"changed:{path}")
    return not errors, errors


def main() -> int:
    out = ROOT / "docs" / "acceptance" / "artifacts"
    out.mkdir(parents=True, exist_ok=True)
    path = out / "jhoc-legacy-readonly-freeze.json"
    report = build_manifest()
    path.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    ok, errors = verify(report)
    md = out / "jhoc-legacy-readonly-freeze.md"
    md.write_text(
        "# JHOC Legacy Read-Only Freeze Proof\n\n"
        f"- Frozen: `{report['frozen_at_utc']}`\n"
        f"- Verification: **{'PASS' if ok else 'FAIL'}**\n"
        f"- Files: `{len(report['entries'])}`\n\n"
        "This is a hash-only, read-only freeze manifest. It does not copy or modify legacy runtime data and excludes credentials and user-learning data.\n",
        encoding="utf-8",
    )
    print(json.dumps({"manifest": str(path), "verified": ok, "errors": errors}, ensure_ascii=True))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
