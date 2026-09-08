"""JHOC Subagent Sandbox Isolation Bus & Dehydrated Acceptance Packaging.

Implements C7 & C8 from Phase 3 Architectural Review:
1. Isolated Execution Sandbox:
   - Captures all intermediate process stdout/stderr and trial logs into out-of-band sidecars
     in logs/audit/subagents/. Zero noisy child traces leak into parent context.
2. Dehydrated Acceptance Result (SubagentResult):
   - is_success: derived physically by the sandbox harness, NEVER self-certified by child.
   - summary: strictly <= 300 chars, pure ASCII.
   - evidence_sha256: computed over the full canonical UTF-8 bytes of child trace.
   - produced_artifacts: paths verified against workspace boundary, capped at <= 10 files and <= 10MB.
3. Cryptographic Parent Integrity Re-verification:
   - Parent can verify that the on-disk trace file hashes exactly to evidence_sha256.
"""

from __future__ import annotations

from contextlib import redirect_stdout, redirect_stderr
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from jhoc.contracts.errors import ContractError, ErrorCode
from jhoc.runner.encoding import to_console_ascii


MAX_SUMMARY_CHARS = 300
MAX_ARTIFACTS_COUNT = 10
MAX_ARTIFACTS_TOTAL_BYTES = 10 * 1024 * 1024  # 10MB


@dataclass(frozen=True, slots=True)
class SubagentResult:
    is_success: bool
    summary: str
    evidence_sha256: str
    trace_storage_ref: str
    produced_artifacts: tuple[str, ...]
    diagnostic: str = ""

    def verify_trace_integrity(self, workspace_root: Path | str | None = None) -> bool:
        """Independently re-verifies stored trace file against reported evidence_sha256."""
        root = Path(workspace_root).resolve() if workspace_root else Path.cwd()
        trace_file = root / self.trace_storage_ref
        if not trace_file.is_file():
            return False
        raw_bytes = trace_file.read_bytes()
        actual_hash = hashlib.sha256(raw_bytes).hexdigest()
        return actual_hash == self.evidence_sha256


class SubagentSandbox:
    """Isolates child task execution and emits clean, dehydrated acceptance packages."""

    def __init__(
        self,
        subagent_id: str,
        workspace_root: Path | str | None = None,
    ) -> None:
        self.subagent_id = subagent_id
        self.root = Path(workspace_root).resolve() if workspace_root else Path.cwd()
        self.audit_dir = self.root / "logs" / "audit" / "subagents"
        self.audit_dir.mkdir(parents=True, exist_ok=True)

    def execute_isolated(
        self,
        child_runner_fn: Callable[..., Any],
        *args: Any,
        expected_artifacts: list[str | Path] | None = None,
        **kwargs: Any,
    ) -> SubagentResult:
        """Executes child task in sandbox, captures raw logs out-of-band, and derives physical verdict."""
        now_iso = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
        trace_file = self.audit_dir / f"subagent_{self.subagent_id}_{now_iso}.log"

        raw_output_buffer: list[str] = []
        is_physically_successful = False
        diagnostic = ""

        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()

        try:
            # Execute child function with stdout and stderr captured
            with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                raw_res = child_runner_fn(*args, **kwargs)
            captured_stdout = stdout_capture.getvalue()
            captured_stderr = stderr_capture.getvalue()
            if captured_stdout:
                raw_output_buffer.append(f"[SUBAGENT_STDOUT]\n{captured_stdout}")
            if captured_stderr:
                raw_output_buffer.append(f"[SUBAGENT_STDERR]\n{captured_stderr}")
            raw_output_buffer.append(f"[SUBAGENT_OUTPUT] {raw_res}")
            is_physically_successful = True
        except ContractError as ce:
            captured_stdout = stdout_capture.getvalue()
            captured_stderr = stderr_capture.getvalue()
            if captured_stdout:
                raw_output_buffer.append(f"[SUBAGENT_STDOUT]\n{captured_stdout}")
            if captured_stderr:
                raw_output_buffer.append(f"[SUBAGENT_STDERR]\n{captured_stderr}")
            raw_output_buffer.append(f"[CONTRACT_ERROR] {ce}")
            diagnostic = f"Contract error: {ce}"
        except Exception as exc:
            captured_stdout = stdout_capture.getvalue()
            captured_stderr = stderr_capture.getvalue()
            if captured_stdout:
                raw_output_buffer.append(f"[SUBAGENT_STDOUT]\n{captured_stdout}")
            if captured_stderr:
                raw_output_buffer.append(f"[SUBAGENT_STDERR]\n{captured_stderr}")
            raw_output_buffer.append(f"[EXECUTION_FAILURE] {exc}")
            diagnostic = f"Execution failure: {exc}"

        # Physical artifact verification
        verified_artifacts: list[str] = []
        total_artifact_bytes = 0

        if expected_artifacts:
            for art in expected_artifacts[:MAX_ARTIFACTS_COUNT]:
                p = (self.root / art).resolve()
                # Boundary confinement check (PathGuard logic)
                try:
                    p.relative_to(self.root)
                except ValueError:
                    is_physically_successful = False
                    diagnostic = f"Artifact escapes workspace boundary: {art}"
                    break

                if p.is_file():
                    sz = p.stat().st_size
                    total_artifact_bytes += sz
                    if total_artifact_bytes > MAX_ARTIFACTS_TOTAL_BYTES:
                        is_physically_successful = False
                        diagnostic = "Artifact total size exceeded 10MB limit."
                        break
                    rel_path = str(p.relative_to(self.root)).replace("\\", "/")
                    verified_artifacts.append(rel_path)
                else:
                    is_physically_successful = False
                    diagnostic = f"Expected artifact missing on disk: {art}"
                    break

        # Persist complete raw child trace out-of-band
        full_trace_text = "\n".join(raw_output_buffer)
        full_trace_bytes = full_trace_text.encode("utf-8")
        evidence_sha256 = hashlib.sha256(full_trace_bytes).hexdigest()

        temp_trace = self.audit_dir / f".tmp_{trace_file.name}"
        temp_trace.write_bytes(full_trace_bytes)
        temp_trace.replace(trace_file)
        trace_ref = str(trace_file.relative_to(self.root)).replace("\\", "/")

        # Derive concise pure-ASCII summary
        if is_physically_successful:
            summary = f"Subagent '{self.subagent_id}' completed successfully with {len(verified_artifacts)} artifacts."
        else:
            summary = f"Subagent '{self.subagent_id}' failed: {diagnostic}"
        clean_summary = to_console_ascii(summary)[:MAX_SUMMARY_CHARS]

        return SubagentResult(
            is_success=is_physically_successful,
            summary=clean_summary,
            evidence_sha256=evidence_sha256,
            trace_storage_ref=trace_ref,
            produced_artifacts=tuple(verified_artifacts),
            diagnostic=diagnostic,
        )
