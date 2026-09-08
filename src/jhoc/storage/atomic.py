"""JHOC Atomic File Storage & Temporary File Lifecycle Protection.

Enforces crash-safe persistence for non-database state (JSON/YAML/Markdown)
via same-directory temporary file writes, explicit fsync, and atomic os.replace.
Guarantees exemption from EXDEV cross-device errors and includes orphan GC.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import time
from typing import Any
from uuid import uuid4


def atomic_write_bytes(target_path: Path | str, data: bytes) -> Path:
    """Atomically write binary data to target path using a same-directory temp file."""
    dest = Path(target_path).resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Same directory temp file to guarantee same filesystem/volume (no EXDEV)
    nonce = uuid4().hex[:8]
    temp_path = dest.parent / f"{dest.name}.tmp.{os.getpid()}.{nonce}"

    try:
        with open(temp_path, "wb") as f:
            f.write(data)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass  # fsync may be unsupported on some virtual filesystems

        # Atomic replacement on POSIX and Windows MoveFileEx
        # Bounded backoff retry on Windows PermissionError (transient sharing violations from AV / readers)
        max_attempts = 8
        for attempt in range(max_attempts):
            try:
                os.replace(temp_path, dest)
                break
            except PermissionError:
                if attempt == max_attempts - 1:
                    raise
                time.sleep(0.02 * (1.5 ** attempt))
        return dest
    except Exception:
        if temp_path.is_file():
            try:
                temp_path.unlink()
            except OSError:
                pass
        raise


def atomic_write_text(
    target_path: Path | str,
    content: str,
    *,
    encoding: str = "utf-8",
) -> Path:
    """Atomically write text data to target path using strict encoding."""
    data = content.encode(encoding)
    return atomic_write_bytes(target_path, data)


def atomic_write_json(
    target_path: Path | str,
    data: Any,
    *,
    indent: int = 2,
    ensure_ascii: bool = False,
) -> Path:
    """Atomically write JSON data with canonical formatting."""
    content = json.dumps(data, indent=indent, sort_keys=True, ensure_ascii=ensure_ascii)
    return atomic_write_text(target_path, content + "\n")


def cleanup_orphan_temps(
    directory: Path | str,
    *,
    max_age_seconds: float = 3600.0,
) -> int:
    """Remove abandoned .tmp.<pid>.<nonce> files created by dead processes."""
    dir_path = Path(directory)
    if not dir_path.is_dir():
        return 0

    removed_count = 0
    cutoff = time.time() - max_age_seconds

    for item in dir_path.glob("*.tmp.*"):
        if item.is_file():
            try:
                if item.stat().st_mtime < cutoff:
                    item.unlink()
                    removed_count += 1
            except OSError:
                pass

    return removed_count
