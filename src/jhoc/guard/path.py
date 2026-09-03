from __future__ import annotations

from enum import StrEnum
import os
from pathlib import Path

from jhoc.contracts.errors import ContractError, ErrorCode


class PathAccessMode(StrEnum):
    READ = "READ"
    WRITE = "WRITE"
    DELETE = "DELETE"
    EXECUTE = "EXECUTE"


class PathGuard:
    """Bidirectional filesystem access guard with workspace scoping and sensitive asset blocking."""

    SENSITIVE_DIR_NAMES = frozenset({
        ".ssh",
        ".aws",
        ".dsh",
        ".gnupg",
        ".azure",
        ".config/gcloud",
    })

    SENSITIVE_FILE_NAMES = frozenset({
        "id_rsa",
        "id_ed25519",
        "id_ecdsa",
        "id_dsa",
        "known_hosts",
        "authorized_keys",
        ".env",
        ".env.local",
        ".env.production",
        ".env.staging",
        ".credentials.yaml",
        ".credentials.json",
        "credentials.yaml",
        "credentials.json",
        "shadow",
        "master.passwd",
        "sam",
        "system",
    })

    GOVERNANCE_FILE_NAMES = frozenset({
        "hooks.json",
        "jhoc_hook_gate.py",
        "jhoc_stop_guard.py",
        "jhoc_pre_inject.py",
        "jhoc_approve.py",
        "jhoc_log_stats.py",
        "jhoc_shougong.py",
        "jhoc_kaigong.py",
        "agents.md",
        "inbox.db",
        "p19-hub.sqlite",
        "p19-memory.sqlite",
        "p19-blackbox.jsonl",
    })

    GOVERNANCE_DIR_PATTERNS = (
        ("src", "jhoc"),
    )

    SENSITIVE_EXTENSIONS = frozenset({
        ".pem",
        ".key",
        ".p12",
        ".pfx",
        ".kdbx",
    })

    @classmethod
    def is_governance_asset(cls, path: str | Path) -> bool:
        """Determines if a target path points to a core governance code or state ledger asset."""
        target = Path(path).resolve()
        name_lower = target.name.lower()
        if name_lower in cls.GOVERNANCE_FILE_NAMES:
            return True
        if name_lower.startswith("jhoc_") and target.suffix.lower() == ".py":
            return True

        parts_lower = [p.lower() for p in target.parts]
        for pat in cls.GOVERNANCE_DIR_PATTERNS:
            pat_lower = [p.lower() for p in pat]
            for i in range(len(parts_lower) - len(pat_lower) + 1):
                if parts_lower[i : i + len(pat_lower)] == pat_lower:
                    return True
        return False

    @classmethod
    def is_sensitive(cls, path: str | Path) -> bool:
        """Determines if a target path points to known sensitive credentials or system assets."""
        target = Path(path)
        name_lower = target.name.lower()

        if name_lower in cls.SENSITIVE_FILE_NAMES:
            return True

        if target.suffix.lower() in cls.SENSITIVE_EXTENSIONS:
            return True

        # Check path parts against sensitive directories
        for part in target.parts:
            part_lower = part.lower()
            if part_lower in cls.SENSITIVE_DIR_NAMES:
                return True

        return False

    @classmethod
    def evaluate(
        cls,
        path: str | Path,
        workspace_root: str | Path,
        mode: PathAccessMode | str = PathAccessMode.READ,
    ) -> Path:
        """Evaluates path safety against workspace containment, governance protection, and sensitive asset blacklists."""
        if not str(path).strip() or not str(workspace_root).strip():
            raise ContractError("path and workspace_root must not be empty", ErrorCode.POLICY_DENIED)

        resolved_root = Path(workspace_root).expanduser().resolve()
        resolved_target = Path(path).expanduser().resolve()
        mode_val = PathAccessMode(mode) if isinstance(mode, PathAccessMode) else PathAccessMode(str(mode).upper())

        # 1. Hard check: Sensitive credential assets are universally blocked regardless of mode
        if cls.is_sensitive(resolved_target):
            raise ContractError(
                f"access to sensitive asset denied: {resolved_target.name}",
                ErrorCode.POLICY_DENIED,
            )

        # 1.1 Governance immutability: Core governance code and state ledgers cannot be modified via agent write
        if mode_val == PathAccessMode.WRITE and cls.is_governance_asset(resolved_target):
            raise ContractError(
                f"modification of core governance asset denied: {resolved_target.name}",
                ErrorCode.POLICY_DENIED,
            )

        # 2. Workspace containment check
        # For READ mode, allow reading from shared trusted mother core (JHOC_ROOT)
        try:
            resolved_target.relative_to(resolved_root)
        except ValueError as exc:
            if mode_val == PathAccessMode.READ:
                jhoc_root = Path(__file__).resolve().parent.parent.parent.parent
                try:
                    resolved_target.relative_to(jhoc_root)
                    return resolved_target
                except ValueError:
                    pass
            raise ContractError(
                f"path '{resolved_target}' escapes workspace root '{resolved_root}'",
                ErrorCode.POLICY_DENIED,
            ) from exc

        return resolved_target
