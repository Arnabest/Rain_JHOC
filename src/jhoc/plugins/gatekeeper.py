from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from jhoc.contracts.errors import ContractError, ErrorCode
from jhoc.contracts.models import PluginManifest


@dataclass(frozen=True, slots=True)
class PluginInspectionReport:
    plugin_id: str
    gate_1_manifest_ok: bool
    gate_2_code_ok: bool
    gate_3_deps_ok: bool
    violations: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_admissible(self) -> bool:
        return self.gate_1_manifest_ok and self.gate_2_code_ok and self.gate_3_deps_ok and not self.violations


class _DangerousASTVisitor(ast.NodeVisitor):
    """AST inspector for dangerous host primitives, dynamic code execution, and credential probing."""

    BLOCKED_MODULES = frozenset({
        "subprocess",
        "pty",
        "ctypes",
        "winreg",
        "commands",
    })

    BLOCKED_CALLS = frozenset({
        "eval",
        "exec",
        "__import__",
        "compile",
    })

    BLOCKED_OS_ATTRIBUTES = frozenset({
        "system",
        "popen",
        "spawn",
        "spawnl",
        "spawnle",
        "spawnlp",
        "spawnlpe",
        "spawnv",
        "spawnve",
        "spawnvp",
        "spawnvpe",
    })

    SENSITIVE_LITERAL_KEYWORDS = frozenset({
        ".ssh",
        ".aws",
        ".dsh",
        "id_rsa",
        "id_ed25519",
        ".credentials.yaml",
    })

    def __init__(self) -> None:
        self.violations: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root_mod = alias.name.split(".")[0]
            if root_mod in self.BLOCKED_MODULES:
                self.violations.append(f"blocked module import: '{alias.name}' at line {node.lineno}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            root_mod = node.module.split(".")[0]
            if root_mod in self.BLOCKED_MODULES:
                self.violations.append(f"blocked module import: '{node.module}' at line {node.lineno}")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # Check direct calls like eval(...) or exec(...)
        if isinstance(node.func, ast.Name) and node.func.id in self.BLOCKED_CALLS:
            self.violations.append(f"blocked dynamic execution call: '{node.func.id}' at line {node.lineno}")

        # Check os.system, os.popen, etc.
        if isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "os":
                if node.func.attr in self.BLOCKED_OS_ATTRIBUTES:
                    self.violations.append(f"blocked OS command execution call: 'os.{node.func.attr}' at line {node.lineno}")

        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str):
            val_lower = node.value.lower()
            for kw in self.SENSITIVE_LITERAL_KEYWORDS:
                if kw in val_lower:
                    self.violations.append(f"suspicious sensitive credential reference: '{kw}' at line {node.lineno}")
        self.generic_visit(node)


class PluginGatekeeper:
    """Implements the 'Three Gates' supply-chain inspection for incoming plugins.

    Gate 1: Publisher and manifest verification.
    Gate 2: Static code AST X-ray (no installation scripts executed).
    Gate 3: Dependency depth and supply-chain cardinality audit.
    """

    MAX_SAFE_DEPENDENCIES = 15

    @classmethod
    def inspect_source(cls, source_code: str, *, filename: str = "<unknown>") -> list[str]:
        """Performs Gate 2 static AST analysis on raw source code."""
        try:
            tree = ast.parse(source_code, filename=filename)
        except SyntaxError as exc:
            return [f"syntax error in plugin source {filename}: {exc}"]

        visitor = _DangerousASTVisitor()
        visitor.visit(tree)
        return visitor.violations

    @classmethod
    def audit(
        cls,
        manifest: PluginManifest,
        source_files: Iterable[tuple[str, str]] = (),
        *,
        max_dependencies: int = MAX_SAFE_DEPENDENCIES,
    ) -> PluginInspectionReport:
        """Runs the complete Three Gates audit on a plugin manifest and its source files."""
        violations: list[str] = []

        # --- Gate 1: Publisher & Manifest Verification ---
        gate_1_ok = True
        if manifest.verification_status not in {"VERIFIED", "TRUSTED"}:
            gate_1_ok = False
            violations.append(f"Gate 1: verification status '{manifest.verification_status}' is untrusted")

        if manifest.mutable_by_agent:
            gate_1_ok = False
            violations.append("Gate 1: plugin allows agent mutation (mutable_by_agent must be false)")

        # --- Gate 2: Static Code X-Ray (AST Inspection) ---
        gate_2_ok = True
        for filepath, content in source_files:
            if filepath.endswith(".py"):
                file_violations = cls.inspect_source(content, filename=filepath)
                if file_violations:
                    gate_2_ok = False
                    violations.extend([f"Gate 2 [{filepath}]: {v}" for v in file_violations])

        # --- Gate 3: Dependency Depth & Supply Chain Audit ---
        gate_3_ok = True
        dep_count = len(manifest.dependencies)
        if dep_count > max_dependencies:
            gate_3_ok = False
            violations.append(
                f"Gate 3: excessive dependencies ({dep_count} > {max_dependencies}), potential supply-chain bloating"
            )

        return PluginInspectionReport(
            plugin_id=manifest.plugin_id,
            gate_1_manifest_ok=gate_1_ok,
            gate_2_code_ok=gate_2_ok,
            gate_3_deps_ok=gate_3_ok,
            violations=tuple(violations),
        )

    @classmethod
    def require_admissible(cls, manifest: PluginManifest, source_files: Iterable[tuple[str, str]] = ()) -> None:
        """Asserts that a plugin passes all three gates; fails closed with ContractError."""
        report = cls.audit(manifest, source_files)
        if not report.is_admissible:
            details = "; ".join(report.violations)
            raise ContractError(
                f"Plugin '{manifest.plugin_id}' failed Gatekeeper admission: {details}",
                ErrorCode.PLUGIN_VALIDATION_FAILED,
            )
