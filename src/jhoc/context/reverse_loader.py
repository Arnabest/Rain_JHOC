"""JHOC 4-Tier Reverse Hierarchy Prompt Loader with Verify-Before-Act.

Enforces:
- C7: Verify-Before-Act 3-state physical probing (VERIFIED, STALE_MEMORY_CHANGED, STALE_MEMORY_DISPROVEN).
      Deterministic workspace containment, socket port check, git SHA check.
      Strict Redaction: raw paths/hashes/ports of disproven claims are REDACTED from the prompt
      (replaced by [REDACTED_DISPROVEN_RESOURCE] + explanation); literals surfaced ONLY for VERIFIED claims.
      Memoized per assembly.
- C8: 4-Tier Reverse Hierarchy prompt layout (Tier 1 Managed -> Tier 2 User -> Tier 3 Project -> Tier 4 Local)
      preserving prefix caching for Tiers 1-3 while confining all per-turn volatile observations
      and retrieved memories to Tier 4 at the generation frontier. Sanitization via DataSanitizer.

Enforces Rule 7 (Zero-Emoji & Pure ASCII) and Rule 2 (Fail-Closed).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import os
from pathlib import Path
import re
import socket
import subprocess
from typing import Any, Mapping, Sequence

from jhoc.context.sanitizer import DataSanitizer
from jhoc.contracts.errors import ContractError, ErrorCode


class PromptTier(StrEnum):
    TIER1_MANAGED = "TIER1_MANAGED"
    TIER2_USER = "TIER2_USER"
    TIER3_PROJECT = "TIER3_PROJECT"
    TIER4_LOCAL = "TIER4_LOCAL"


class ProbeStatus(StrEnum):
    VERIFIED = "VERIFIED"
    STALE_MEMORY_CHANGED = "STALE_MEMORY_CHANGED"
    STALE_MEMORY_DISPROVEN = "STALE_MEMORY_DISPROVEN"


@dataclass(frozen=True, slots=True)
class ProbeResult:
    resource_type: str  # "FILE", "GIT_SHA", "PORT"
    raw_literal: str
    status: ProbeStatus
    diagnostic: str
    redacted_replacement: str


class PhysicalClaimVerifier:
    """Probes file paths, git SHAs, and socket ports against physical system ground truth."""

    # Regex patterns for physical claims (both marked and bare paths)
    _FILE_PATTERN = re.compile(
        r"(?:['\"]file:\/\/\/([^'\"\r\n>]+)['\"]"
        r"|\]\(file:\/\/\/([^\)\r\n>]+)\)"
        r"|<file:\/\/\/([^>\r\n]+)>"
        r"|file:\/\/\/([^\s\r\n'\"<>\)\]]+)"
        r"|\b(?:path|file|filepath):\s*['\"]?([a-zA-Z]:[/\\][^\r\n'\"<>\)\]]+|[a-zA-Z0-9_\-\.]+(?:/[a-zA-Z0-9_\-\.]+)+)['\"]?"
        r"|['\"]([a-zA-Z]:[/\\][^\r\n'\"<>]+|[a-zA-Z0-9_\-\.]+(?:/[a-zA-Z0-9_\-\.]+)+)['\"]"
        r"|(?:(?<=\s)|^)([a-zA-Z]:[/\\][^\s\r\n'\"<>\)\]]+|[a-zA-Z0-9_\-\.]+(?:/[a-zA-Z0-9_\-\.]+)+))"
    )
    _GIT_SHA_PATTERN = re.compile(r"(?:\b(?:commit|git_sha|baseline_sha):\s*|(?:(?<=\s)|^))([0-9a-fA-F]{40})\b")
    _PORT_PATTERN = re.compile(r"\b(?:port|localhost:)\s*(\d{2,5})\b")

    def __init__(self, workspace_root: Path | str) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self._memo_cache: dict[str, ProbeResult] = {}

    def probe_resource_claim(self, claim_type: str, literal: str) -> ProbeResult:
        cache_key = f"{claim_type}:{literal}"
        if cache_key in self._memo_cache:
            return self._memo_cache[cache_key]

        res: ProbeResult
        if claim_type == "FILE":
            res = self._probe_file(literal)
        elif claim_type == "GIT_SHA":
            res = self._probe_git_sha(literal)
        elif claim_type == "PORT":
            res = self._probe_port(literal)
        else:
            res = ProbeResult(
                resource_type=claim_type,
                raw_literal=literal,
                status=ProbeStatus.STALE_MEMORY_DISPROVEN,
                diagnostic=f"Unknown resource type: {claim_type}",
                redacted_replacement=f"[REDACTED_DISPROVEN_RESOURCE: Unknown resource type {claim_type}]",
            )
        self._memo_cache[cache_key] = res
        return res

    def clear_cache(self) -> None:
        """Clears memo cache to ensure ground-truth freshness per prompt assembly."""
        self._memo_cache.clear()

    def _probe_file(self, path_str: str) -> ProbeResult:
        norm_path = path_str.replace("/", os.sep).replace("\\", os.sep)
        p = Path(norm_path)
        if not p.is_absolute():
            p = (self.workspace_root / p).resolve()
        else:
            p = p.resolve()

        # Workspace containment check
        is_contained = True
        try:
            p.relative_to(self.workspace_root)
        except ValueError:
            is_contained = False

        if not p.exists():
            return ProbeResult(
                resource_type="FILE",
                raw_literal=path_str,
                status=ProbeStatus.STALE_MEMORY_DISPROVEN,
                diagnostic=f"File not found on disk: {p}",
                redacted_replacement="[REDACTED_DISPROVEN_RESOURCE: File does not exist on disk]",
            )

        if not is_contained:
            return ProbeResult(
                resource_type="FILE",
                raw_literal=path_str,
                status=ProbeStatus.STALE_MEMORY_CHANGED,
                diagnostic=f"File exists outside workspace boundary: {p}",
                redacted_replacement="[REDACTED_CHANGED_OR_EXTERNAL_RESOURCE]",
            )

        return ProbeResult(
            resource_type="FILE",
            raw_literal=path_str,
            status=ProbeStatus.VERIFIED,
            diagnostic="File verified on disk",
            redacted_replacement=path_str,
        )

    def _probe_git_sha(self, sha: str) -> ProbeResult:
        try:
            res = subprocess.run(
                ["git", "cat-file", "-e", sha],
                cwd=str(self.workspace_root),
                capture_output=True,
                text=True,
                timeout=5,
            )
            if res.returncode == 0:
                return ProbeResult(
                    resource_type="GIT_SHA",
                    raw_literal=sha,
                    status=ProbeStatus.VERIFIED,
                    diagnostic=f"Git commit {sha[:10]} verified in object database",
                    redacted_replacement=sha,
                )
            else:
                return ProbeResult(
                    resource_type="GIT_SHA",
                    raw_literal=sha,
                    status=ProbeStatus.STALE_MEMORY_DISPROVEN,
                    diagnostic=f"Git commit {sha[:10]} not found in object database",
                    redacted_replacement="[REDACTED_DISPROVEN_RESOURCE: Git commit does not exist in repository]",
                )
        except Exception as e:
            return ProbeResult(
                resource_type="GIT_SHA",
                raw_literal=sha,
                status=ProbeStatus.STALE_MEMORY_DISPROVEN,
                diagnostic=f"Git probe failed: {e}",
                redacted_replacement="[REDACTED_DISPROVEN_RESOURCE: Git probe failed]",
            )

    def _probe_port(self, port_str: str) -> ProbeResult:
        try:
            port = int(port_str)
            if not (1 <= port <= 65535):
                raise ValueError("Port out of range")
        except ValueError:
            return ProbeResult(
                resource_type="PORT",
                raw_literal=port_str,
                status=ProbeStatus.STALE_MEMORY_DISPROVEN,
                diagnostic=f"Invalid port number: {port_str}",
                redacted_replacement="[REDACTED_DISPROVEN_RESOURCE: Invalid port number]",
            )

        # Check if port is bound/listening locally
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        try:
            res = s.connect_ex(("127.0.0.1", port))
            s.close()
            if res == 0:
                return ProbeResult(
                    resource_type="PORT",
                    raw_literal=port_str,
                    status=ProbeStatus.VERIFIED,
                    diagnostic=f"Port {port} verified listening",
                    redacted_replacement=port_str,
                )
            else:
                return ProbeResult(
                    resource_type="PORT",
                    raw_literal=port_str,
                    status=ProbeStatus.STALE_MEMORY_DISPROVEN,
                    diagnostic=f"Port {port} is closed/not listening",
                    redacted_replacement="[REDACTED_DISPROVEN_RESOURCE: Port is closed or not listening]",
                )
        except Exception as e:
            return ProbeResult(
                resource_type="PORT",
                raw_literal=port_str,
                status=ProbeStatus.STALE_MEMORY_DISPROVEN,
                diagnostic=f"Port probe exception: {e}",
                redacted_replacement="[REDACTED_DISPROVEN_RESOURCE: Port probe error]",
            )

    def verify_and_redact_memory_text(self, text: str) -> tuple[str, list[ProbeResult]]:
        """Scans text for physical resource claims, probes them, and redacts disproven claims."""
        results: list[ProbeResult] = []
        spans_to_redact: list[tuple[int, int, str]] = []

        # 1. Probe Files
        for match in self._FILE_PATTERN.finditer(text):
            idx = match.lastindex
            if idx is None:
                continue
            raw_match = match.group(idx)
            if not raw_match:
                continue
            path_str = raw_match.strip()
            start_idx, end_idx = match.span(idx)
            if path_str.endswith((".", ",", ";", ":", ")", "]")):
                trimmed = path_str.rstrip(".,;:)]")
                end_idx -= (len(path_str) - len(trimmed))
                path_str = trimmed
            probe = self.probe_resource_claim("FILE", path_str)
            results.append(probe)
            if probe.status != ProbeStatus.VERIFIED:
                spans_to_redact.append((start_idx, end_idx, probe.redacted_replacement))

        # 2. Probe Git SHAs
        for match in self._GIT_SHA_PATTERN.finditer(text):
            sha_str = match.group(1).strip()
            start_idx, end_idx = match.span(1)
            probe = self.probe_resource_claim("GIT_SHA", sha_str)
            results.append(probe)
            if probe.status != ProbeStatus.VERIFIED:
                spans_to_redact.append((start_idx, end_idx, probe.redacted_replacement))

        # 3. Probe Ports
        for match in self._PORT_PATTERN.finditer(text):
            port_str = match.group(1).strip()
            start_idx, end_idx = match.span(1)
            probe = self.probe_resource_claim("PORT", port_str)
            results.append(probe)
            if probe.status != ProbeStatus.VERIFIED:
                spans_to_redact.append((start_idx, end_idx, probe.redacted_replacement))

        # Sort spans right-to-left by start index descending to prevent index drift
        spans_to_redact.sort(key=lambda x: x[0], reverse=True)
        redacted_text = text
        for start, end, replacement in spans_to_redact:
            redacted_text = redacted_text[:start] + replacement + redacted_text[end:]

        return redacted_text, results


class ReversePromptLoader:
    """Assembles prompt layers adhering to 4-tier reverse hierarchy and prompt-cache discipline."""

    def __init__(self, workspace_root: Path | str, sanitizer: DataSanitizer | None = None) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.sanitizer = sanitizer or DataSanitizer()
        self.verifier = PhysicalClaimVerifier(self.workspace_root)

    def build_prompt(
        self,
        managed_tier_text: str,
        user_tier_text: str,
        project_tier_text: str,
        local_step_state: str,
        local_latest_observation: str,
        retrieved_memories: Sequence[str] = (),
    ) -> tuple[str, list[ProbeResult]]:
        """Assembles prompt with immutable Tier 1-3 prefix and dynamic Tier 4 generation tail."""
        self.verifier.clear_cache()
        all_probes: list[ProbeResult] = []

        # Tiers 1-3 are static/session-stable
        tier1_sanitized, _ = self.sanitizer.sanitize_text(managed_tier_text)
        tier2_sanitized, _ = self.sanitizer.sanitize_text(user_tier_text)
        tier3_sanitized, _ = self.sanitizer.sanitize_text(project_tier_text)

        # Tier 4 dynamic content: step state, observation, and retrieved memories
        verified_memories: list[str] = []
        for mem in retrieved_memories:
            sanitized_mem, _ = self.sanitizer.sanitize_text(mem)
            redacted_mem, probes = self.verifier.verify_and_redact_memory_text(sanitized_mem)
            all_probes.extend(probes)
            verified_memories.append(redacted_mem)

        memories_block = ""
        if verified_memories:
            mem_items = "\n".join(f"- {m}" for m in verified_memories)
            memories_block = f"\n[RETRIEVED GROUNDED MEMORIES (VERIFIED & REDACTED)]\n{mem_items}\n"

        tier4_body = (
            f"[ACTIVE STEP STATE]\n{local_step_state.strip()}\n\n"
            f"{memories_block}\n"
            f"[LATEST OBSERVATION]\n{local_latest_observation.strip()}"
        )
        tier4_sanitized, _ = self.sanitizer.sanitize_text(tier4_body)

        # Delimited layout with cache breakpoints
        sections = [
            "=== [TIER-1: MANAGED GOVERNANCE (IMMUTABLE PREFIX)] ===",
            tier1_sanitized.strip(),
            "",
            "=== [TIER-2: USER PROFILE & LONG-TERM PREFERENCES] ===",
            tier2_sanitized.strip(),
            "",
            "=== [TIER-3: PROJECT TOPOLOGY & ARCHITECTURAL SPECS] ===",
            tier3_sanitized.strip(),
            "",
            "=== [TIER-4: LOCAL TASK & ACTIVE GENERATION FRONTIER] ===",
            tier4_sanitized.strip(),
        ]

        full_prompt = "\n".join(sections).strip() + "\n"
        return full_prompt, all_probes
