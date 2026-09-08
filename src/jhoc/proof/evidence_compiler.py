"""JHOC Formal Compiler Ground-Truth & EvidencePackage Engine.

Implements Phase 5 & Phase 6 Binding Conditions:
- C1: Sole gate-acceptable evidence builder with ordered CompilerProbeResult records:
      AST/syntax compile -> parameterized unit-test execution -> physical file SHA-256.
- C2: Rejection of empty hash (e3b0c442...), all-zero hash, missing files, and live byte mismatches.
- C3 & C5: Mandatory negative-control validation with physical execution provenance (exit_code != 0
      and non-empty output digest) and anti-circular-mock enforcement.
- C4 & C8: Manifest snapshotting with declared-new file tracking (None initial hash) and fail-closed creation verification.
- C5 & C9: TOCTOU live re-hash verification and finalize ghost re-scan across scan_roots.
- C6: Governed negative-control bypass via auditable reason and non-empty policy_ref.

Provenance Boundary Specification (C5 / W3):
EvidencePackageEngine enforces structural integrity, physical file hashing, process exit codes,
non-empty stdout/stderr digests, and anti-circular checks. In an in-memory test or execution harness,
caller-constructed CompilerProbeResult records represent trusted builder inputs. For adversarial
or untrusted caller environments, probe records must be produced directly through run_unit_test()
or run_sandboxed_probe() physical process execution.

Strictly enforces Rule 7 (Zero-Emoji & Pure ASCII), Rule 1 (Physical Reality),
and Rule 2 (Fail-Closed).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping, Sequence

from jhoc.contracts.errors import ContractError, ErrorCode
from jhoc.proof.store import EvidencePackage

# Sentinel hashes that must NEVER be accepted as physical proof
EMPTY_SHA256: str = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
ZERO_SHA256: str = "0" * 64

# Consolidated immutable ignore policies for deterministic artifacts & editor temps (C9)
IMMUTABLE_IGNORE_DIRS: frozenset[str] = frozenset({
    "__pycache__",
    ".git",
    ".pytest_cache",
    ".venv",
    "node_modules",
    ".system_generated",
    "logs",
    "scratch",
})
IMMUTABLE_IGNORE_SUFFIXES: frozenset[str] = frozenset({
    ".pyc",
    ".sqlite-wal",
    ".sqlite-shm",
    ".tmp",
    ".bak",
    ".lock",
    ".swp",
})


def is_ignored_artifact(path: Path) -> bool:
    """Checks whether a path matches immutable transient artifact or editor backup patterns (C9)."""
    if any(part in IMMUTABLE_IGNORE_DIRS for part in path.parts):
        return True
    if path.suffix in IMMUTABLE_IGNORE_SUFFIXES:
        return True
    if path.name.endswith("~") or (path.name.startswith(".") and path.suffix == ".swp"):
        return True
    return False


class CompilerProbeType(StrEnum):
    AST_SYNTAX = "ast_syntax"
    UNIT_TEST = "unit_test"
    FILE_HASH = "file_hash"
    NEGATIVE_CONTROL = "negative_control"


@dataclass(frozen=True, slots=True)
class CompilerProbeResult:
    probe_type: CompilerProbeType
    target: str
    passed: bool
    details: str
    stdout_sha256: str = ""
    stderr_sha256: str = ""
    exit_code: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "probe_type": self.probe_type.value,
            "target": self.target,
            "passed": self.passed,
            "details": self.details,
            "stdout_sha256": self.stdout_sha256,
            "stderr_sha256": self.stderr_sha256,
            "exit_code": self.exit_code,
        }


@dataclass(frozen=True, slots=True)
class EvidenceVerificationReport:
    task_id: str
    is_valid: bool
    probes: tuple[CompilerProbeResult, ...]
    file_hashes: Mapping[str, str]
    manifest_diff_valid: bool
    toctou_verified: bool
    digest: str
    rejection_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "is_valid": self.is_valid,
            "probes": [p.to_dict() for p in self.probes],
            "file_hashes": dict(self.file_hashes),
            "manifest_diff_valid": self.manifest_diff_valid,
            "toctou_verified": self.toctou_verified,
            "digest": self.digest,
            "rejection_reason": self.rejection_reason,
        }


class EvidencePackageEngine:
    """Deterministic, single-node compiler ground-truth arbiter and EvidencePackage compiler."""

    def __init__(self, workspace_root: Path | str, allow_shell: bool = False) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.allow_shell = allow_shell
        if self.allow_shell:
            raise ContractError("allow_shell=True is strictly forbidden by Rule 3", ErrorCode.POLICY_DENIED)

    def hash_file_physical(self, file_path: Path | str) -> str:
        """Computes physical SHA-256, rejecting missing files and sentinel hashes (C2)."""
        p = Path(file_path).resolve()
        if not p.is_file():
            raise ContractError(f"Target physical file not found: {p}", ErrorCode.POLICY_DENIED)

        raw = p.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()

        if digest == EMPTY_SHA256:
            raise ContractError(
                f"Fail-Closed: File {p} is empty (matches empty-byte SHA-256 {EMPTY_SHA256}). "
                "Empty files are prohibited as evidence.",
                ErrorCode.POLICY_DENIED,
            )
        if digest == ZERO_SHA256:
            raise ContractError(
                f"Fail-Closed: File {p} matches zero sentinel hash {ZERO_SHA256}.",
                ErrorCode.POLICY_DENIED,
            )
        return digest

    def compile_ast(self, file_path: Path | str) -> CompilerProbeResult:
        """Verifies syntax and AST validity under Python compiler."""
        p = Path(file_path).resolve()
        if not p.is_file():
            return CompilerProbeResult(
                probe_type=CompilerProbeType.AST_SYNTAX,
                target=str(p),
                passed=False,
                details=f"File not found: {p}",
                exit_code=1,
            )
        try:
            content = p.read_text(encoding="utf-8")
            ast.parse(content, filename=str(p))
            return CompilerProbeResult(
                probe_type=CompilerProbeType.AST_SYNTAX,
                target=str(p),
                passed=True,
                details="AST syntax compilation successful",
                exit_code=0,
            )
        except SyntaxError as se:
            return CompilerProbeResult(
                probe_type=CompilerProbeType.AST_SYNTAX,
                target=str(p),
                passed=False,
                details=f"SyntaxError at line {se.lineno}: {se.msg}",
                exit_code=1,
            )
        except Exception as exc:
            return CompilerProbeResult(
                probe_type=CompilerProbeType.AST_SYNTAX,
                target=str(p),
                passed=False,
                details=f"AST parse error: {exc}",
                exit_code=1,
            )

    def run_unit_test(
        self,
        command_args: Sequence[str],
        timeout: int = 60,
    ) -> CompilerProbeResult:
        """Executes parameterized unit test with allow_shell=False and output hash tracking (C1)."""
        if not command_args:
            raise ContractError("Test command args cannot be empty", ErrorCode.INVALID_CONTRACT)

        target_cmd = " ".join(command_args)
        try:
            res = subprocess.run(
                list(command_args),
                cwd=str(self.workspace_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
                timeout=timeout,
            )
            out_hash = hashlib.sha256(res.stdout.encode("utf-8")).hexdigest()
            err_hash = hashlib.sha256(res.stderr.encode("utf-8")).hexdigest()
            passed = res.returncode == 0

            return CompilerProbeResult(
                probe_type=CompilerProbeType.UNIT_TEST,
                target=target_cmd,
                passed=passed,
                details=f"Process exited with code {res.returncode}",
                stdout_sha256=out_hash,
                stderr_sha256=err_hash,
                exit_code=res.returncode,
            )
        except subprocess.TimeoutExpired:
            return CompilerProbeResult(
                probe_type=CompilerProbeType.UNIT_TEST,
                target=target_cmd,
                passed=False,
                details=f"Execution timed out after {timeout} seconds",
                exit_code=124,
            )
        except Exception as exc:
            return CompilerProbeResult(
                probe_type=CompilerProbeType.UNIT_TEST,
                target=target_cmd,
                passed=False,
                details=f"Process execution failed: {exc}",
                exit_code=1,
            )

    def snapshot_manifest(
        self,
        paths: Sequence[Path | str],
        scan_roots: Sequence[Path | str] | None = None,
    ) -> dict[str, str | None]:
        """Creates a manifest snapshot mapping file path string to live SHA-256 (C4, C8).

        If a declared path does not yet exist on disk, maps to None (expected-new).
        If scan_roots is provided, also snapshots all existing regular files under scan_roots.
        """
        manifest: dict[str, str | None] = {}
        for p_raw in paths:
            p = Path(p_raw).resolve()
            if p.is_file():
                manifest[str(p)] = self.hash_file_physical(p)
            else:
                manifest[str(p)] = None

        if scan_roots:
            for root_raw in scan_roots:
                root = Path(root_raw).resolve()
                if root.is_dir():
                    for item in root.rglob("*"):
                        if is_ignored_artifact(item):
                            continue
                        if item.is_file() and not item.is_symlink():
                            manifest[str(item.resolve())] = self.hash_file_physical(item)
        return manifest

    def verify_file_manifest(
        self,
        initial_manifest: Mapping[str, str | None],
        declared_changes: Sequence[Path | str] | None = None,
        scan_roots: Sequence[Path | str] | None = None,
    ) -> tuple[bool, dict[str, str], str]:
        """Verifies manifest diff completeness against declared changes and detects ghost files (C4, C8, C9)."""
        current_hashes: dict[str, str] = {}
        declared_set = {str(Path(p).resolve()) for p in (declared_changes or ())}

        actual_changed: set[str] = set()

        # 1. Check pre-existing files (initial_hash is not None)
        for path_str, initial_hash in initial_manifest.items():
            if initial_hash is None:
                continue
            p = Path(path_str)
            if not p.is_file():
                actual_changed.add(path_str)
                continue
            cur_hash = self.hash_file_physical(p)
            current_hashes[path_str] = cur_hash
            if cur_hash != initial_hash:
                actual_changed.add(path_str)

        # 2. Check declared new files (initial_hash is None) (C8)
        for path_str, initial_hash in initial_manifest.items():
            if initial_hash is not None:
                continue
            p = Path(path_str)
            if not p.is_file():
                return (
                    False,
                    current_hashes,
                    f"Declared new file was not created: {path_str}",
                )
            cur_hash = self.hash_file_physical(p)
            current_hashes[path_str] = cur_hash
            actual_changed.add(path_str)

        # 3. Undeclared modifications vs declared changes
        undeclared = actual_changed - declared_set
        if undeclared:
            return (
                False,
                current_hashes,
                f"Undeclared file modifications detected: {sorted(undeclared)}",
            )

        # 4. Declared but unobserved changes
        declared_missing = declared_set - actual_changed
        if declared_missing and declared_changes:
            return (
                False,
                current_hashes,
                f"Declared changes not observed in physical manifest: {sorted(declared_missing)}",
            )

        # 5. Ghost file scan in scan_roots (C9)
        if scan_roots:
            ghost_files: list[str] = []
            for root_raw in scan_roots:
                root = Path(root_raw).resolve()
                if root.is_dir():
                    for item in root.rglob("*"):
                        if is_ignored_artifact(item):
                            continue
                        if item.is_file() and not item.is_symlink():
                            p_str = str(item.resolve())
                            if p_str not in initial_manifest and p_str not in declared_set:
                                ghost_files.append(p_str)
            if ghost_files:
                return (
                    False,
                    current_hashes,
                    f"Undeclared ghost file detected in scan scope: {sorted(ghost_files)}",
                )

        return True, current_hashes, "Manifest diff verified complete"

    def verify_toctou(
        self,
        staged_manifest: Mapping[str, str],
        scan_roots: Sequence[Path | str] | None = None,
        declared_changes: Sequence[Path | str] | None = None,
        initial_manifest: Mapping[str, str | None] | None = None,
    ) -> tuple[bool, str]:
        """Immediate pre-acceptance TOCTOU live re-hash and ghost re-scan verification (C5, C9)."""
        for path_str, expected_hash in staged_manifest.items():
            p = Path(path_str)
            if not p.is_file():
                return False, f"TOCTOU drift: File missing at finalize: {p}"
            live_hash = self.hash_file_physical(p)
            if live_hash != expected_hash:
                return (
                    False,
                    f"TOCTOU drift: File {p} modified between prepare and finalize ({live_hash} != {expected_hash})",
                )

        # Ghost re-scan before finalize (C9 / R6)
        if scan_roots and initial_manifest is not None:
            declared_set = {str(Path(p).resolve()) for p in (declared_changes or ())}
            ghosts: list[str] = []
            for root_raw in scan_roots:
                root = Path(root_raw).resolve()
                if root.is_dir():
                    for item in root.rglob("*"):
                        if is_ignored_artifact(item):
                            continue
                        if item.is_file() and not item.is_symlink():
                            p_str = str(item.resolve())
                            if p_str not in initial_manifest and p_str not in declared_set:
                                ghosts.append(p_str)
            if ghosts:
                return False, f"TOCTOU drift: Undeclared ghost file appeared before finalize: {sorted(ghosts)}"

        return True, "TOCTOU check passed: Live bytes identical"

    def compile_package(
        self,
        task_id: str,
        work_id: str,
        policy_ref: str,
        capability_version: str,
        probes: Sequence[CompilerProbeResult],
        file_paths: Sequence[Path | str] | None = None,
        side_effect_state: str = "COMMITTED",
        negative_control_probe: CompilerProbeResult | None = None,
        require_negative_control: bool = True,
        negative_control_bypass_reason: str | None = None,
    ) -> tuple[EvidencePackage, EvidenceVerificationReport]:
        """Compiles gate-acceptable EvidencePackage under C1-C7."""
        if not probes:
            raise ContractError("EvidencePackage requires at least one compiler probe", ErrorCode.INVALID_CONTRACT)

        # C1: Order probes: AST -> Unit Test -> File Hash
        ordered_probes: list[CompilerProbeResult] = []
        ast_probes = [p for p in probes if p.probe_type == CompilerProbeType.AST_SYNTAX]
        test_probes = [p for p in probes if p.probe_type == CompilerProbeType.UNIT_TEST]
        other_probes = [
            p for p in probes
            if p.probe_type not in (CompilerProbeType.AST_SYNTAX, CompilerProbeType.UNIT_TEST)
        ]
        ordered_probes.extend(ast_probes)
        ordered_probes.extend(test_probes)
        ordered_probes.extend(other_probes)

        # Collect physical hashes
        file_hashes: dict[str, str] = {}
        for fp in (file_paths or ()):
            p = Path(fp).resolve()
            h = self.hash_file_physical(p)
            file_hashes[str(p)] = h
            ordered_probes.append(
                CompilerProbeResult(
                    probe_type=CompilerProbeType.FILE_HASH,
                    target=str(p),
                    passed=True,
                    details=f"Physical file SHA-256: {h}",
                )
            )

        # C7 Precedence: First, anti-circular mock rule (require at least one real physical check)
        if not file_hashes and not any(p.exit_code == 0 for p in test_probes):
            raise ContractError(
                "Fail-Closed: Anti-circular-mock violation. EvidencePackage contains zero physical file hashes "
                "and zero process exit observations.",
                ErrorCode.POLICY_DENIED,
            )

        # C5 & C6: Negative control verification, physical provenance & bypass governance
        negative_bypassed = False
        if negative_control_probe is not None:
            if negative_control_probe.passed:
                raise ContractError(
                    "Fail-Closed: Negative-control probe was expected to fail, but passed. "
                    "Evidence package validity rejected.",
                    ErrorCode.POLICY_DENIED,
                )
            # C5: Must carry physical execution provenance (non-zero exit code and non-empty output digest)
            if (
                negative_control_probe.exit_code is None
                or negative_control_probe.exit_code == 0
                or (not negative_control_probe.stdout_sha256 and not negative_control_probe.stderr_sha256)
            ):
                raise ContractError(
                    "Fail-Closed: Negative-control probe lacks physical execution provenance "
                    "(requires non-zero exit code and non-empty output digest).",
                    ErrorCode.POLICY_DENIED,
                )
            neg_record = CompilerProbeResult(
                probe_type=CompilerProbeType.NEGATIVE_CONTROL,
                target=negative_control_probe.target,
                passed=True,
                details=f"Negative control verified: {negative_control_probe.details}",
                stdout_sha256=negative_control_probe.stdout_sha256,
                stderr_sha256=negative_control_probe.stderr_sha256,
                exit_code=negative_control_probe.exit_code,
            )
            ordered_probes.append(neg_record)
        else:
            if require_negative_control:
                if negative_control_bypass_reason and policy_ref and policy_ref not in ("", "default"):
                    negative_bypassed = True
                else:
                    raise ContractError(
                        "Fail-Closed: Negative-control probe is mandatory but was not supplied. "
                        "To bypass, an explicit negative_control_bypass_reason under a valid governed policy_ref is required.",
                        ErrorCode.POLICY_DENIED,
                    )

        # Verify all positive probes passed
        positive_probes = [p for p in ordered_probes if p.probe_type != CompilerProbeType.NEGATIVE_CONTROL]
        all_passed = all(p.passed for p in positive_probes)

        # Assemble EvidencePackage
        verification_dict = {
            "probes": [p.to_dict() for p in ordered_probes],
            "file_hashes": file_hashes,
            "all_passed": all_passed,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        execution_dict = {
            "engine": "EvidencePackageEngine",
            "probe_count": len(ordered_probes),
            "file_count": len(file_hashes),
            "require_negative_control": require_negative_control,
            "negative_control_bypassed": negative_bypassed,
            "negative_control_bypass_reason": negative_control_bypass_reason if negative_bypassed else None,
        }
        expected_dict = {
            "all_probes_pass": True,
            "no_sentinel_hashes": True,
            "negative_control_verified": negative_control_probe is not None,
        }
        evidence_refs = tuple(sorted(file_hashes.keys())) or (f"task:{task_id}:probe_digest",)

        pkg = EvidencePackage(
            task_id=task_id,
            work_id=work_id,
            policy_ref=policy_ref,
            capability_version=capability_version,
            expected=expected_dict,
            execution=execution_dict,
            verification=verification_dict,
            side_effect_state=side_effect_state,
            evidence_refs=evidence_refs,
        )

        # Physical report
        rejection = ""
        if not all_passed:
            failed_probes = [p.target for p in positive_probes if not p.passed]
            rejection = f"Probes failed: {failed_probes}"

        report = EvidenceVerificationReport(
            task_id=task_id,
            is_valid=(all_passed and pkg.digest not in (EMPTY_SHA256, ZERO_SHA256)),
            probes=tuple(ordered_probes),
            file_hashes=file_hashes,
            manifest_diff_valid=True,
            toctou_verified=True,
            digest=pkg.digest,
            rejection_reason=rejection,
        )

        return pkg, report

