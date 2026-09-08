"""JHOC Dynamic Tiered Governance Prompt Injector.

Implements C1 & C5 from Phase 2 Architectural Review:
1. GovernanceLayer hierarchy (Layer 0 Base, Layer 1 Action, Layer 2 Asset) to eliminate
   terminology collision with intent-classifier Tiers.
2. Cache-friendly architecture: Layer 0 acts as a deterministic static prefix,
   while Layer 1 & 2 are assembled as an ephemeral tail overlay.
3. Byte-determinism contract: identical inputs produce 100% byte-identical pure-ASCII strings.
4. Token budget control: Layer 0 < 200 tokens, Layer 1 < 350 tokens, Layer 2 < 600 tokens.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
import re
from typing import Any, Mapping


class GovernanceLayer(StrEnum):
    LAYER_0_BASE = "LAYER_0_BASE"
    LAYER_1_ACTION = "LAYER_1_ACTION"
    LAYER_2_ASSET = "LAYER_2_ASSET"


_HIGH_RISK_PATTERNS = (
    re.compile(r"(^|/|\\)AGENTS\.md$", re.IGNORECASE),
    re.compile(r"(^|/|\\)CLAUDE\.md$", re.IGNORECASE),
    re.compile(r"(^|/|\\)\.agents[/\\]rules[/\\]", re.IGNORECASE),
    re.compile(r"(^|/|\\)src[/\\]jhoc[/\\]contracts[/\\]", re.IGNORECASE),
    re.compile(r"(^|/|\\)src[/\\]jhoc[/\\]guard[/\\]", re.IGNORECASE),
    re.compile(r"(^|/|\\)schemas[/\\]", re.IGNORECASE),
    re.compile(r"(^|/|\\)scripts[/\\]jhoc_hook_gate\.py$", re.IGNORECASE),
    re.compile(r"(^|/|\\)scripts[/\\]jhoc_shougong\.py$", re.IGNORECASE),
    re.compile(r"(^|/|\\)scripts[/\\]jhoc_kaigong\.py$", re.IGNORECASE),
)

_MUTATING_TOOL_KEYWORDS = (
    "write", "edit", "patch", "replace", "create", "delete", "run", "bash", "command", "exec"
)
_MUTATING_TOOLS_EXACT = {
    "write_to_file",
    "replace_file_content",
    "multi_replace_file_content",
    "run_command",
    "bash",
    "write",
    "edit",
    "apply_patch",
    "notebook_edit",
    "notebookedit",
    "applypatch",
}


def is_mutating_tool(tool_name: str | None) -> bool:
    """Determine if a tool call has mutating capabilities."""
    if not tool_name or not str(tool_name).strip():
        return False
    norm = str(tool_name).strip().lower()
    if norm in _MUTATING_TOOLS_EXACT:
        return True
    return any(kw in norm for kw in _MUTATING_TOOL_KEYWORDS)


def is_high_risk_asset(path: str | Path) -> bool:
    """Determine if a file path points to a core governance asset."""
    p_str = str(path).replace("\\", "/")
    return any(pat.search(p_str) for pat in _HIGH_RISK_PATTERNS)


class TieredGovernanceInjector:
    """Deterministic, cache-friendly prompt injector for layered governance."""

    def __init__(self, workspace_root: Path | str | None = None) -> None:
        self.root = Path(workspace_root).resolve() if workspace_root else Path.cwd()

    def render_layer_0_base(self) -> str:
        """Layer 0: Global baseline identity, ASCII discipline, and fail-closed contract.
        
        Strictly bounded: < 200 tokens, 100% deterministic ASCII.
        """
        return (
            "[JHOC GOVERNANCE: LAYER 0 BASE]\n"
            "- Role: Managed Execution Agent under strict external harness.\n"
            "- Rule 0: Anti-Sycophancy & Ground Truth. Objective empirical proof is sole standard.\n"
            "- Rule 2: Zero-Trust Boundary. Fail-Closed security. Model possesses zero self-approval authority.\n"
            "- Rule 7: Zero-Emoji Discipline. Output strictly pure ASCII / standard text. Emojis forbidden."
        )

    def render_layer_1_action(self, tool_name: str) -> str:
        """Layer 1: Action-dependent rules invoked strictly for mutating tools.
        
        Strictly bounded: < 350 tokens, deterministic ASCII.
        """
        tool_clean = tool_name.strip()
        return (
            f"[JHOC GOVERNANCE: LAYER 1 ACTION -> {tool_clean}]\n"
            "- Rule 3: Dual-Plane Isolation. Data plane sanitized; operational plane parameterized (allow_shell=False).\n"
            "- Atomic Persistence: All file updates must write to same-directory temp files, fsync, then replace.\n"
            "- Workspace Hygiene: No transient litter (temp_*, test_*, *.tmp) in workspace root; use scratch/."
        )

    def render_layer_2_asset(self, target_path: str | Path) -> str:
        """Layer 2: High-risk governance asset rules invoked strictly when touching core files.
        
        Strictly bounded: < 600 tokens, deterministic ASCII.
        """
        norm_path = str(target_path).replace("\\", "/")
        return (
            f"[JHOC GOVERNANCE: LAYER 2 CORE ASSET -> {norm_path}]\n"
            "- CRITICAL CONSTITUTIONAL ASSET TOUCHED: Self-modification forbidden (mutable_by_agent: false).\n"
            "- Rule 4: Static Capability Closure. No runtime AST injection, no dynamic unvetted imports.\n"
            "- Rule 6: Chain of Evidence. Modifications must preserve schema backward compatibility.\n"
            "- Mandatory 36 Co-Review: Must pass 3 post-flight self-audits and 6 invariant co-reviews prior to closure."
        )

    def render_tail_overlay(
        self,
        tool_name: str | None = None,
        target_path: str | Path | None = None,
    ) -> str:
        """Assembles a deterministic, cache-friendly tail overlay.
        
        Layer 0 is omitted here if already present in the static prompt head.
        Only activated layers are included, separated by deterministic newlines.
        """
        blocks: list[str] = []

        if is_mutating_tool(tool_name):
            blocks.append(self.render_layer_1_action(str(tool_name).strip()))

        if target_path and is_high_risk_asset(target_path):
            blocks.append(self.render_layer_2_asset(target_path))

        if not blocks:
            return ""

        return "\n\n".join(blocks)

    def estimate_token_count(self, text: str) -> int:
        """Conservative token count estimation (pure ASCII ~ 4 chars/token; CJK ~ 1.5 chars/token)."""
        if not text:
            return 0
        ascii_chars = sum(1 for ch in text if ord(ch) < 128)
        non_ascii_chars = len(text) - ascii_chars
        return int((ascii_chars / 3.8) + (non_ascii_chars / 1.5))
