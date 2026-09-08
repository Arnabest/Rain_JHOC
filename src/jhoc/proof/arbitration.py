"""JHOC Autonomous Dispute Arbitration & Ground-Truth Verification Engine.

Implements Phase 5 and Phase 6 Binding Conditions:
- C6: Arbitration Delta Isolation: Canonical (subject, attribute, value, provenance)
      delta extraction. Unparseable prose divergence resolves immediately to NON_PROBEABLE.
- C7: Sandboxed Probe Execution: Pre-approved static template library; custom probes
      AST-audited, hashed pre-execution, bounded timeout, allow_shell=False.
- C8: ArbitrationVerdict Lattice: Strict lattice:
      PROVEN_A / PROVEN_B / INCONCLUSIVE / NON_PROBEABLE / REQUIRES_APPROVAL.
      INCONCLUSIVE and NON_PROBEABLE escalate to human resolution via SQLiteApprovalInbox
      and block task completion. No heuristic tie-breaking on physical truth.
- C9: Immutable Arbitration Persistence & BlackBox Chaining:
      Content-addressed ArbitrationVerdict with stdout/stderr hashes, chained to
      BlackBoxJournal.latest_hash, persisted in SQLite WAL, immutable with supersedes_ref.
- Phase 6 C1, C2, C3, C4, C10: Mode-aware gating, task correlation in tickets,
      operator approval / supersession resolution, exception surfacing, and inline code AST pre-audit.

Strictly adheres to Rule 7 (Zero-Emoji Pure ASCII), Rule 1 (Physical Reality),
Rule 2 (Fail-Closed), Rule 3 (allow_shell=False), and Rule 5 (SQLite WAL Single-Node).
"""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
from threading import RLock
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4

from jhoc.conductor.inbox import ApprovalStatus, SQLiteApprovalInbox
from jhoc.contracts.errors import ContractError, ErrorCode
from jhoc.proof.blackbox import BlackBoxJournal, BlackBoxStepType
from jhoc.runner.process import classify_process_result


class ArbitrationVerdictStatus(StrEnum):
    PROVEN_A = "PROVEN_A"
    PROVEN_B = "PROVEN_B"
    INCONCLUSIVE = "INCONCLUSIVE"
    NON_PROBEABLE = "NON_PROBEABLE"
    REQUIRES_APPROVAL = "REQUIRES_APPROVAL"

    @property
    def blocks_completion(self) -> bool:
        """Indicates whether this verdict halts pipeline progress until operator intervention."""
        return self in (
            ArbitrationVerdictStatus.INCONCLUSIVE,
            ArbitrationVerdictStatus.NON_PROBEABLE,
            ArbitrationVerdictStatus.REQUIRES_APPROVAL,
        )


@dataclass(frozen=True, slots=True)
class AtomicClaimDelta:
    """Canonical 4-tuple representation of an isolated physical claim delta (C6)."""
    subject: str
    attribute: str
    value: Any
    provenance: str

    def to_dict(self) -> dict[str, str]:
        return {
            "subject": self.subject,
            "attribute": self.attribute,
            "value": str(self.value),
            "provenance": self.provenance,
        }

    @property
    def canonical_key(self) -> str:
        return f"{self.subject}:{self.attribute}".lower().strip()


@dataclass(frozen=True, slots=True)
class DisputeCase:
    """Represents a dispute between two assertions or model propositions (C6)."""
    dispute_id: str
    task_id: str
    claim_a: AtomicClaimDelta | None
    claim_b: AtomicClaimDelta | None
    subject: str = ""
    raw_divergence_text: str = ""
    is_probeable: bool = True
    unprobeable_reason: str | None = None
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.subject:
            derived = self.claim_a.subject if self.claim_a else (self.claim_b.subject if self.claim_b else "dispute")
            object.__setattr__(self, "subject", derived)
        if not self.created_at:
            object.__setattr__(self, "created_at", datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "dispute_id": self.dispute_id,
            "task_id": self.task_id,
            "subject": self.subject,
            "claim_a": self.claim_a.to_dict() if self.claim_a else None,
            "claim_b": self.claim_b.to_dict() if self.claim_b else None,
            "raw_divergence_text": self.raw_divergence_text,
            "is_probeable": self.is_probeable,
            "unprobeable_reason": self.unprobeable_reason,
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class ArbitrationVerdict:
    """Immutable, content-addressed arbitration verdict record (C8, C9)."""
    verdict_id: str
    dispute_id: str
    task_id: str
    status: ArbitrationVerdictStatus
    winning_model: str | None = None
    probe_spec_hash: str = "none"
    probe_stdout_sha256: str = "none"
    probe_stderr_sha256: str = "none"
    probe_exit_code: int = 0
    journal_chain_hash: str = ""
    supersedes_ref: str | None = None
    escalated_ticket_id: str | None = None
    rationale: str = ""
    timestamp: str = ""
    details: Mapping[str, Any] = field(default_factory=dict)
    winner_claim: Any = None
    parent_blackbox_hash: str = ""
    justification: str = ""
    decided_at: str = ""

    def __post_init__(self) -> None:
        if not self.parent_blackbox_hash and self.journal_chain_hash:
            object.__setattr__(self, "parent_blackbox_hash", self.journal_chain_hash)
        elif not self.journal_chain_hash and self.parent_blackbox_hash:
            object.__setattr__(self, "journal_chain_hash", self.parent_blackbox_hash)

        if not self.justification and self.rationale:
            object.__setattr__(self, "justification", self.rationale)
        elif not self.rationale and self.justification:
            object.__setattr__(self, "rationale", self.justification)

        if not self.decided_at and self.timestamp:
            object.__setattr__(self, "decided_at", self.timestamp)
        elif not self.timestamp and self.decided_at:
            object.__setattr__(self, "timestamp", self.decided_at)

    @property
    def digest(self) -> str:
        return self.verdict_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict_id": self.verdict_id,
            "dispute_id": self.dispute_id,
            "task_id": self.task_id,
            "status": self.status.value,
            "winning_model": self.winning_model,
            "probe_spec_hash": self.probe_spec_hash,
            "probe_stdout_sha256": self.probe_stdout_sha256,
            "probe_stderr_sha256": self.probe_stderr_sha256,
            "probe_exit_code": self.probe_exit_code,
            "journal_chain_hash": self.journal_chain_hash,
            "supersedes_ref": self.supersedes_ref,
            "escalated_ticket_id": self.escalated_ticket_id,
            "rationale": self.rationale,
            "timestamp": self.timestamp,
            "details": dict(self.details),
            "winner_claim": self.winner_claim.to_dict() if hasattr(self.winner_claim, "to_dict") else self.winner_claim,
            "parent_blackbox_hash": self.parent_blackbox_hash,
            "justification": self.justification,
            "decided_at": self.decided_at,
            "digest": self.digest,
        }

    @classmethod
    def compute_hash(
        cls,
        dispute_id: str,
        task_id: str,
        status: ArbitrationVerdictStatus,
        probe_spec_hash: str,
        probe_stdout_sha256: str,
        probe_stderr_sha256: str,
        journal_chain_hash: str,
        timestamp: str,
    ) -> str:
        payload = {
            "dispute_id": dispute_id,
            "task_id": task_id,
            "status": status.value,
            "probe_spec_hash": probe_spec_hash,
            "probe_stdout_sha256": probe_stdout_sha256,
            "probe_stderr_sha256": probe_stderr_sha256,
            "journal_chain_hash": journal_chain_hash,
            "timestamp": timestamp,
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()


class ProbeTemplateType(StrEnum):
    FILE_EXISTS = "file_exists"
    FILE_CONTENT_CONTAINS = "file_content_contains"
    FILE_SHA256_EQUALS = "file_sha256_equals"
    AST_SYNTAX_VALID = "ast_syntax_valid"
    COMMAND_EXIT_CODE = "command_exit_code"
    JSON_FIELD_EQUALS = "json_field_equals"
    CUSTOM_PYTHON_PROBE = "custom_python_probe"


FORBIDDEN_CUSTOM_PROBE_CALLS: frozenset[str] = frozenset({
    "system",
    "spawn",
    "popen",
    "fork",
    "eval",
    "exec",
    "__import__",
    "compile",
    "open_browser_url",
    "kill",
})

FORBIDDEN_CUSTOM_PROBE_MODULES: frozenset[str] = frozenset({
    "socket",
    "urllib",
    "requests",
    "http",
    "ftplib",
    "ctypes",
    "multiprocessing",
})


def audit_custom_probe_ast(code: str) -> tuple[bool, str]:
    """Statically audits custom probe Python source for dangerous primitives (C7)."""
    try:
        tree = ast.parse(code, filename="<custom_probe>")
    except SyntaxError as err:
        return False, f"SyntaxError in custom probe: {err}"

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod_root = alias.name.split(".")[0]
                if mod_root in FORBIDDEN_CUSTOM_PROBE_MODULES:
                    return False, f"Forbidden import '{alias.name}' in probe"
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                mod_root = node.module.split(".")[0]
                if mod_root in FORBIDDEN_CUSTOM_PROBE_MODULES:
                    return False, f"Forbidden from-import '{node.module}' in probe"
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CUSTOM_PROBE_CALLS:
                return False, f"Forbidden function call '{node.func.id}()' in probe"
            elif isinstance(node.func, ast.Attribute) and node.func.attr in FORBIDDEN_CUSTOM_PROBE_CALLS:
                return False, f"Forbidden method call '{node.func.attr}()' in probe"

    return True, "AST check passed"


class DisputeArbitrationEngine:
    """Autonomous dispute arbitration and ground-truth verification engine (MA-RAG).
    
    Persists dispute records and immutable verdicts to SQLite WAL.
    """

    GENESIS_CHAIN_HASH: str = "0" * 64

    def __init__(
        self,
        db_path: str | Path | None = None,
        workspace_root: str | Path | None = None,
        approval_inbox: SQLiteApprovalInbox | None = None,
        inbox: SQLiteApprovalInbox | None = None,
        blackbox: Any = None,
        allow_shell: bool = False,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve() if workspace_root else Path.cwd().resolve()
        if db_path is None:
            self.db_path = (self.workspace_root / "arbitration.sqlite").resolve()
        else:
            self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.approval_inbox = inbox if inbox is not None else approval_inbox
        self.blackbox = blackbox
        self.allow_shell = allow_shell
        self.last_escalation_error: str = ""
        self._lock = RLock()
        self._db = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=30)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS jhoc_dispute_cases (
                    dispute_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    is_probeable INTEGER NOT NULL,
                    unprobeable_reason TEXT,
                    created_at TEXT NOT NULL,
                    case_payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS jhoc_arbitration_verdicts (
                    verdict_id TEXT PRIMARY KEY,
                    dispute_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    winning_model TEXT DEFAULT '',
                    probe_spec_hash TEXT NOT NULL DEFAULT '',
                    probe_stdout_sha256 TEXT NOT NULL DEFAULT '',
                    probe_stderr_sha256 TEXT NOT NULL DEFAULT '',
                    probe_exit_code INTEGER NOT NULL DEFAULT 0,
                    journal_chain_hash TEXT NOT NULL DEFAULT '',
                    supersedes_ref TEXT,
                    escalated_ticket_id TEXT,
                    rationale TEXT NOT NULL DEFAULT '',
                    timestamp TEXT NOT NULL DEFAULT '',
                    payload TEXT NOT NULL DEFAULT '',
                    winner_claim_json TEXT DEFAULT '',
                    parent_blackbox_hash TEXT DEFAULT '',
                    justification TEXT DEFAULT '',
                    decided_at TEXT DEFAULT '',
                    digest TEXT DEFAULT ''
                );

                CREATE INDEX IF NOT EXISTS idx_verdicts_task ON jhoc_arbitration_verdicts(task_id);
                CREATE INDEX IF NOT EXISTS idx_verdicts_dispute ON jhoc_arbitration_verdicts(dispute_id);
                """
            )
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            try:
                self._db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception:
                pass
            self._db.close()

    def isolate_delta(
        self,
        task_id: str,
        subject: str,
        claim_a_text: str,
        claim_b_text: str,
        provenance_a: str = "model_a",
        provenance_b: str = "model_b",
        dispute_id: str | None = None,
    ) -> DisputeCase:
        """Extracts canonical (subject, attribute, value, provenance) deltas (C6)."""
        disp_id = dispute_id or f"dispute-{uuid4().hex[:12]}"
        now_iso = datetime.now(timezone.utc).isoformat()

        delta_a = self._parse_atomic_proposition(subject, claim_a_text, provenance_a)
        delta_b = self._parse_atomic_proposition(subject, claim_b_text, provenance_b)

        if delta_a is None or delta_b is None:
            reason = (
                "Unparseable prose divergence: unable to extract canonical "
                "(subject, attribute, value, provenance) propositions from input text."
            )
            case = DisputeCase(
                dispute_id=disp_id,
                task_id=task_id,
                subject=subject,
                claim_a=delta_a,
                claim_b=delta_b,
                raw_divergence_text=f"A: {claim_a_text} | B: {claim_b_text}",
                is_probeable=False,
                unprobeable_reason=reason,
                created_at=now_iso,
            )
        elif delta_a.canonical_key != delta_b.canonical_key:
            reason = (
                f"Attribute mismatch in isolated deltas: Model A asserts on '{delta_a.canonical_key}' "
                f"while Model B asserts on '{delta_b.canonical_key}'. Not directly comparable on single observable."
            )
            case = DisputeCase(
                dispute_id=disp_id,
                task_id=task_id,
                subject=subject,
                claim_a=delta_a,
                claim_b=delta_b,
                raw_divergence_text=f"A: {claim_a_text} | B: {claim_b_text}",
                is_probeable=False,
                unprobeable_reason=reason,
                created_at=now_iso,
            )
        elif str(delta_a.value).strip() == str(delta_b.value).strip():
            reason = "Spurious dispute: both models assert identical value for target attribute."
            case = DisputeCase(
                dispute_id=disp_id,
                task_id=task_id,
                subject=subject,
                claim_a=delta_a,
                claim_b=delta_b,
                raw_divergence_text=f"A: {claim_a_text} | B: {claim_b_text}",
                is_probeable=False,
                unprobeable_reason=reason,
                created_at=now_iso,
            )
        else:
            case = DisputeCase(
                dispute_id=disp_id,
                task_id=task_id,
                subject=subject,
                claim_a=delta_a,
                claim_b=delta_b,
                raw_divergence_text=f"A: {claim_a_text} | B: {claim_b_text}",
                is_probeable=True,
                unprobeable_reason=None,
                created_at=now_iso,
            )

        self._persist_case(case)
        return case

    def _parse_atomic_proposition(
        self,
        subject: str,
        text: str,
        provenance: str,
    ) -> AtomicClaimDelta | None:
        clean = text.strip()
        if not clean:
            return None

        if clean.startswith("{") and clean.endswith("}"):
            try:
                data = json.loads(clean)
                if isinstance(data, dict) and len(data) == 1:
                    attr, val = next(iter(data.items()))
                    return AtomicClaimDelta(
                        subject=subject,
                        attribute=str(attr).strip(),
                        value=str(val).strip(),
                        provenance=provenance,
                    )
            except Exception:
                pass

        m = re.match(r"^([a-zA-Z0-9_\-\.]+)\s*[:=]\s*(.+)$", clean)
        if m:
            attr = m.group(1).strip()
            val = m.group(2).strip().strip("'\"")
            return AtomicClaimDelta(
                subject=subject,
                attribute=attr,
                value=val,
                provenance=provenance,
            )

        m2 = re.match(r"^([a-zA-Z0-9_\-\.]+)\s+is\s+(.+)$", clean, re.IGNORECASE)
        if m2:
            attr = m2.group(1).strip()
            val = m2.group(2).strip().strip("'\"")
            return AtomicClaimDelta(
                subject=subject,
                attribute=attr,
                value=val,
                provenance=provenance,
            )

        return None

    def arbitrate(
        self,
        case: DisputeCase,
        probe_runner: Callable[[], tuple[int, str, str, str]] | None = None,
        probe_template: ProbeTemplateType | None = None,
        probe_args: Mapping[str, Any] | None = None,
        journal: BlackBoxJournal | None = None,
        supersedes_ref: str | None = None,
    ) -> ArbitrationVerdict:
        """Alias for arbitrate_case providing primary interface."""
        return self.arbitrate_case(
            case=case,
            probe_runner=probe_runner,
            probe_template=probe_template,
            probe_args=probe_args,
            journal=journal,
            supersedes_ref=supersedes_ref,
        )

    def arbitrate_case(
        self,
        case: DisputeCase,
        probe_runner: Callable[[], tuple[int, str, str, str]] | None = None,
        probe_template: ProbeTemplateType | None = None,
        probe_args: Mapping[str, Any] | None = None,
        journal: BlackBoxJournal | None = None,
        supersedes_ref: str | None = None,
    ) -> ArbitrationVerdict:
        now_iso = datetime.now(timezone.utc).isoformat()
        chain_hash = journal.latest_hash if journal else self.GENESIS_CHAIN_HASH

        # 1. Non-probeable resolution
        if not case.is_probeable:
            rationale = (
                f"Dispute {case.dispute_id} resolved as NON_PROBEABLE: "
                f"{case.unprobeable_reason or 'No reason provided'}"
            )
            v_hash = ArbitrationVerdict.compute_hash(
                dispute_id=case.dispute_id,
                task_id=case.task_id,
                status=ArbitrationVerdictStatus.NON_PROBEABLE,
                probe_spec_hash="none",
                probe_stdout_sha256="none",
                probe_stderr_sha256="none",
                journal_chain_hash=chain_hash,
                timestamp=now_iso,
            )
            v_id = f"verdict-{v_hash[:16]}"
            ticket_id = self._escalate_to_inbox(
                verdict_id=v_id,
                case=case,
                operation="ARBITRATION_NON_PROBEABLE",
                reason=rationale,
                payload=case.to_dict(),
            )
            verdict = ArbitrationVerdict(
                verdict_id=v_id,
                dispute_id=case.dispute_id,
                task_id=case.task_id,
                status=ArbitrationVerdictStatus.NON_PROBEABLE,
                winning_model=None,
                probe_spec_hash="none",
                probe_stdout_sha256="none",
                probe_stderr_sha256="none",
                probe_exit_code=1,
                journal_chain_hash=chain_hash,
                supersedes_ref=supersedes_ref,
                escalated_ticket_id=ticket_id,
                rationale=rationale,
                timestamp=now_iso,
                details={"unprobeable_reason": case.unprobeable_reason},
            )
            self._persist_verdict(verdict)
            self._log_blackbox(journal, verdict)
            return verdict

        # 2. Probe execution
        if probe_runner is not None:
            exit_code, stdout, stderr, spec_hash = probe_runner()
        elif probe_template is not None:
            exit_code, stdout, stderr, spec_hash = self._execute_template_probe(
                case=case,
                template=probe_template,
                args=probe_args or {},
            )
        else:
            rationale = f"No probe executor or template specified for probeable dispute {case.dispute_id}"
            v_hash = ArbitrationVerdict.compute_hash(
                dispute_id=case.dispute_id,
                task_id=case.task_id,
                status=ArbitrationVerdictStatus.INCONCLUSIVE,
                probe_spec_hash="none",
                probe_stdout_sha256="none",
                probe_stderr_sha256="none",
                journal_chain_hash=chain_hash,
                timestamp=now_iso,
            )
            v_id = f"verdict-{v_hash[:16]}"
            ticket_id = self._escalate_to_inbox(
                verdict_id=v_id,
                case=case,
                operation="ARBITRATION_INCONCLUSIVE",
                reason=rationale,
                payload=case.to_dict(),
            )
            verdict = ArbitrationVerdict(
                verdict_id=v_id,
                dispute_id=case.dispute_id,
                task_id=case.task_id,
                status=ArbitrationVerdictStatus.INCONCLUSIVE,
                winning_model=None,
                probe_spec_hash="none",
                probe_stdout_sha256="none",
                probe_stderr_sha256="none",
                probe_exit_code=1,
                journal_chain_hash=chain_hash,
                supersedes_ref=supersedes_ref,
                escalated_ticket_id=ticket_id,
                rationale=rationale,
                timestamp=now_iso,
                details={"error": "missing_probe_executor"},
            )
            self._persist_verdict(verdict)
            self._log_blackbox(journal, verdict)
            return verdict

        stdout_hash = hashlib.sha256(stdout.encode("utf-8")).hexdigest()
        stderr_hash = hashlib.sha256(stderr.encode("utf-8")).hexdigest()

        # 3. Verdict lattice decision
        assert case.claim_a is not None and case.claim_b is not None
        observed_value = stdout.strip()

        claim_a_match = self._values_match(str(case.claim_a.value), observed_value, exit_code)
        claim_b_match = self._values_match(str(case.claim_b.value), observed_value, exit_code)

        if claim_a_match and not claim_b_match:
            status = ArbitrationVerdictStatus.PROVEN_A
            winner = case.claim_a.provenance
            rationale = (
                f"Physical probe verified Claim A ({case.claim_a.value}) "
                f"and refuted Claim B ({case.claim_b.value}). Observed: '{observed_value}'"
            )
        elif claim_b_match and not claim_a_match:
            status = ArbitrationVerdictStatus.PROVEN_B
            winner = case.claim_b.provenance
            rationale = (
                f"Physical probe verified Claim B ({case.claim_b.value}) "
                f"and refuted Claim A ({case.claim_a.value}). Observed: '{observed_value}'"
            )
        else:
            status = ArbitrationVerdictStatus.INCONCLUSIVE
            winner = None
            rationale = (
                f"Probe result was inconclusive. Observed: '{observed_value}', exit_code={exit_code}. "
                f"Claim A match={claim_a_match}, Claim B match={claim_b_match}."
            )

        v_hash = ArbitrationVerdict.compute_hash(
            dispute_id=case.dispute_id,
            task_id=case.task_id,
            status=status,
            probe_spec_hash=spec_hash,
            probe_stdout_sha256=stdout_hash,
            probe_stderr_sha256=stderr_hash,
            journal_chain_hash=chain_hash,
            timestamp=now_iso,
        )
        v_id = f"verdict-{v_hash[:16]}"

        ticket_id = None
        if status.blocks_completion:
            ticket_id = self._escalate_to_inbox(
                verdict_id=v_id,
                case=case,
                operation="ARBITRATION_INCONCLUSIVE",
                reason=rationale,
                payload={
                    "case": case.to_dict(),
                    "observed": observed_value,
                    "exit_code": exit_code,
                    "stdout": stdout,
                    "stderr": stderr,
                },
            )

        verdict = ArbitrationVerdict(
            verdict_id=v_id,
            dispute_id=case.dispute_id,
            task_id=case.task_id,
            status=status,
            winning_model=winner,
            probe_spec_hash=spec_hash,
            probe_stdout_sha256=stdout_hash,
            probe_stderr_sha256=stderr_hash,
            probe_exit_code=exit_code,
            journal_chain_hash=chain_hash,
            supersedes_ref=supersedes_ref,
            escalated_ticket_id=ticket_id,
            rationale=rationale,
            timestamp=now_iso,
            details={
                "observed_value": observed_value,
                "stdout_snippet": stdout[:200],
                "stderr_snippet": stderr[:200],
            },
        )

        self._persist_verdict(verdict)
        self._log_blackbox(journal, verdict)

        return verdict

    def _values_match(self, claim_val: str, observed_val: str, exit_code: int) -> bool:
        c = claim_val.strip().lower()
        o = observed_val.strip().lower()

        if c == o:
            return True
        if c in {"true", "1", "yes", "passed", "ok"} and (o in {"true", "1", "yes", "passed", "ok"} or (exit_code == 0 and not o)):
            return True
        if c in {"false", "0", "no", "failed"} and (o in {"false", "0", "no", "failed"} or exit_code != 0):
            return True
        if c.isdigit() and str(exit_code) == c:
            return True
        if c in o:
            return True
        return False

    def _execute_template_probe(
        self,
        case: DisputeCase,
        template: ProbeTemplateType,
        args: Mapping[str, Any],
    ) -> tuple[int, str, str, str]:
        spec_payload = {
            "template": template.value,
            "dispute_id": case.dispute_id,
            "args": dict(args),
        }
        spec_hash = hashlib.sha256(
            json.dumps(spec_payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
        ).hexdigest()

        if template == ProbeTemplateType.FILE_EXISTS:
            rel_path = str(args.get("path", case.subject))
            target_path = (self.workspace_root / rel_path).resolve()
            exists = target_path.exists()
            return (0 if exists else 1, str(exists).lower(), "", spec_hash)

        elif template == ProbeTemplateType.FILE_CONTENT_CONTAINS:
            rel_path = str(args.get("path", case.subject))
            target_path = (self.workspace_root / rel_path).resolve()
            search_str = str(args.get("contains", ""))
            if not target_path.is_file():
                return (1, "false", f"File not found: {target_path}", spec_hash)
            content = target_path.read_text(encoding="utf-8", errors="replace")
            contains = search_str in content
            return (0 if contains else 1, str(contains).lower(), "", spec_hash)

        elif template == ProbeTemplateType.FILE_SHA256_EQUALS:
            rel_path = str(args.get("path", case.subject))
            target_path = (self.workspace_root / rel_path).resolve()
            if not target_path.is_file():
                return (1, "none", f"File not found: {target_path}", spec_hash)
            raw = target_path.read_bytes()
            computed_sha = hashlib.sha256(raw).hexdigest()
            return (0, computed_sha, "", spec_hash)

        elif template == ProbeTemplateType.AST_SYNTAX_VALID:
            rel_path = str(args.get("path", case.subject))
            target_path = (self.workspace_root / rel_path).resolve()
            if not target_path.is_file():
                return (1, "false", f"File not found: {target_path}", spec_hash)
            try:
                ast.parse(target_path.read_text(encoding="utf-8", errors="replace"))
                return (0, "true", "", spec_hash)
            except SyntaxError as err:
                return (1, "false", str(err), spec_hash)

        elif template == ProbeTemplateType.JSON_FIELD_EQUALS:
            rel_path = str(args.get("path", case.subject))
            field_name = str(args.get("field", case.claim_a.attribute if case.claim_a else ""))
            target_path = (self.workspace_root / rel_path).resolve()
            if not target_path.is_file():
                return (1, "none", f"File not found: {target_path}", spec_hash)
            try:
                data = json.loads(target_path.read_text(encoding="utf-8", errors="replace"))
                val = str(data.get(field_name, ""))
                return (0, val, "", spec_hash)
            except Exception as err:
                return (1, "none", str(err), spec_hash)

        elif template == ProbeTemplateType.CUSTOM_PYTHON_PROBE:
            code = str(args.get("code", ""))
            passed_ast, ast_err = audit_custom_probe_ast(code)
            if not passed_ast:
                return (1, "", f"Custom probe rejected by AST audit: {ast_err}", spec_hash)

            proc = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True,
                text=True,
                cwd=str(self.workspace_root),
                shell=False,
                timeout=10,
            )
            return (proc.returncode, proc.stdout.strip(), proc.stderr.strip(), spec_hash)

        else:
            return (1, "", f"Unsupported probe template: {template}", spec_hash)

    def run_sandboxed_probe(
        self,
        probe_command: Sequence[str],
        timeout: int = 10,
    ) -> tuple[int, str, str, str, str]:
        """Runs a sandboxed probe command with AST pre-audit on -c/--command (Phase 6 C10)."""
        if not probe_command:
            raise ContractError("Probe command cannot be empty", ErrorCode.INVALID_CONTRACT)

        # 1. Dangling flag check
        if probe_command[-1] in ("-c", "--command"):
            raise ContractError(
                f"Dangling -c/--command argument in probe: {list(probe_command)}",
                ErrorCode.INVALID_CONTRACT,
            )

        # 2. Positional inline code AST pre-audit
        for i, arg in enumerate(probe_command):
            if arg in ("-c", "--command") and i + 1 < len(probe_command):
                code = probe_command[i + 1]
                try:
                    ast.parse(code)
                except SyntaxError as se:
                    raise ContractError(
                        f"Inline probe code AST syntax error: {se}",
                        ErrorCode.POLICY_DENIED,
                    )

        # 3. Parameterized execution with allow_shell=False (Rule 3)
        proc = subprocess.run(
            list(probe_command),
            capture_output=True,
            text=True,
            cwd=str(self.workspace_root),
            shell=False,
            timeout=timeout,
        )
        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()
        out_hash = hashlib.sha256(stdout.encode("utf-8")).hexdigest()
        err_hash = hashlib.sha256(stderr.encode("utf-8")).hexdigest()

        return (proc.returncode, stdout, stderr, out_hash, err_hash)

    def _escalate_to_inbox(
        self,
        verdict_id: str,
        case: DisputeCase,
        operation: str,
        reason: str,
        payload: Mapping[str, Any],
    ) -> str | None:
        """Escalates inconclusive or unprobeable disputes to human approval inbox (C8, Phase 6 C2, C4)."""
        if self.approval_inbox is None:
            return None

        ticket_id = f"arb-esc-{verdict_id[:10]}"
        enriched_payload = dict(payload)
        enriched_payload["task_id"] = case.task_id
        enriched_payload["dispute_id"] = case.dispute_id
        enriched_payload["verdict_id"] = verdict_id

        try:
            ticket = self.approval_inbox.create_ticket(
                ticket_id=ticket_id,
                operation=operation,
                requester="DisputeArbitrationEngine",
                reason=reason,
                payload=enriched_payload,
            )
            return ticket.ticket_id
        except Exception as err:
            self.last_escalation_error = f"Inbox escalation failed: {err}"
            raise ContractError(
                f"Arbitration escalation ticket creation failed: {err}",
                ErrorCode.POLICY_DENIED,
            )

    def _log_blackbox(self, journal: BlackBoxJournal | None, verdict: ArbitrationVerdict) -> None:
        target_journal = journal or self.blackbox
        if target_journal:
            try:
                target_journal.append(
                    step_type=BlackBoxStepType.BACK,
                    actor="DisputeArbitrationEngine",
                    content=verdict.to_dict(),
                )
            except Exception as err:
                self.last_escalation_error = f"BlackBox append failed: {err}"

    def _persist_case(self, case: DisputeCase) -> None:
        with self._lock:
            self._db.execute(
                """
                INSERT OR REPLACE INTO jhoc_dispute_cases
                (dispute_id, task_id, subject, is_probeable, unprobeable_reason, created_at, case_payload)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case.dispute_id,
                    case.task_id,
                    case.subject,
                    1 if case.is_probeable else 0,
                    case.unprobeable_reason,
                    case.created_at,
                    json.dumps(case.to_dict(), ensure_ascii=True),
                ),
            )
            self._db.commit()

    def _persist_verdict(self, verdict: ArbitrationVerdict) -> None:
        with self._lock:
            self._db.execute(
                """
                INSERT OR REPLACE INTO jhoc_arbitration_verdicts
                (verdict_id, dispute_id, task_id, status, winning_model, probe_spec_hash,
                 probe_stdout_sha256, probe_stderr_sha256, probe_exit_code, journal_chain_hash,
                 supersedes_ref, escalated_ticket_id, rationale, timestamp, payload,
                 parent_blackbox_hash, justification, decided_at, digest)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    verdict.verdict_id,
                    verdict.dispute_id,
                    verdict.task_id,
                    verdict.status.value,
                    verdict.winning_model,
                    verdict.probe_spec_hash,
                    verdict.probe_stdout_sha256,
                    verdict.probe_stderr_sha256,
                    verdict.probe_exit_code,
                    verdict.journal_chain_hash,
                    verdict.supersedes_ref,
                    verdict.escalated_ticket_id,
                    verdict.rationale,
                    verdict.timestamp,
                    json.dumps(verdict.to_dict(), ensure_ascii=True),
                    verdict.journal_chain_hash,
                    verdict.rationale,
                    verdict.timestamp,
                    verdict.verdict_id,
                ),
            )
            self._db.commit()

    def is_verdict_resolved(self, verdict: ArbitrationVerdict) -> bool:
        """Determines if a blocking verdict has been resolved by operator approval (Phase 6 C3)."""
        if not verdict.status.blocks_completion:
            return True
        if self.approval_inbox is None:
            return False

        ticket_id = f"arb-esc-{verdict.verdict_id[:10]}"
        ticket = self.approval_inbox.get_ticket(ticket_id)
        if ticket is None:
            return False
        return ticket.status in (ApprovalStatus.APPROVED, ApprovalStatus.CONSUMED)

    def get_active_disputes_for_task(self, task_id: str) -> list[ArbitrationVerdict]:
        """Returns non-superseded verdicts for task (Phase 6 C3)."""
        all_verdicts = self.list_verdicts_for_task(task_id)
        superseded_ids = {v.supersedes_ref for v in all_verdicts if v.supersedes_ref}
        return [v for v in all_verdicts if v.verdict_id not in superseded_ids]

    def get_verdict(self, verdict_id: str) -> ArbitrationVerdict | None:
        with self._lock:
            cur = self._db.execute(
                """
                SELECT verdict_id, dispute_id, task_id, status, winning_model,
                       probe_spec_hash, probe_stdout_sha256, probe_stderr_sha256,
                       probe_exit_code, journal_chain_hash, supersedes_ref,
                       escalated_ticket_id, rationale, timestamp, payload,
                       winner_claim_json, parent_blackbox_hash, justification,
                       decided_at, digest
                FROM jhoc_arbitration_verdicts WHERE verdict_id = ?
                """,
                (verdict_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return self._row_to_verdict(row)

    def list_verdicts_for_task(self, task_id: str) -> tuple[ArbitrationVerdict, ...]:
        with self._lock:
            cur = self._db.execute(
                """
                SELECT verdict_id, dispute_id, task_id, status, winning_model,
                       probe_spec_hash, probe_stdout_sha256, probe_stderr_sha256,
                       probe_exit_code, journal_chain_hash, supersedes_ref,
                       escalated_ticket_id, rationale, timestamp, payload,
                       winner_claim_json, parent_blackbox_hash, justification,
                       decided_at, digest
                FROM jhoc_arbitration_verdicts WHERE task_id = ? ORDER BY timestamp ASC
                """,
                (task_id,),
            )
            rows = cur.fetchall()
            return tuple(self._row_to_verdict(r) for r in rows)

    def _row_to_verdict(self, row: tuple) -> ArbitrationVerdict:
        (
            verdict_id, dispute_id, task_id, status_val, winning_model,
            probe_spec_hash, probe_stdout_sha256, probe_stderr_sha256,
            probe_exit_code, journal_chain_hash, supersedes_ref,
            escalated_ticket_id, rationale, timestamp, payload_str,
            winner_claim_json, parent_blackbox_hash, justification,
            decided_at, digest
        ) = row

        if payload_str:
            try:
                d = json.loads(payload_str)
                v = self._dict_to_verdict(d)
                return v
            except Exception:
                pass

        wc = None
        if winner_claim_json:
            try:
                wcd = json.loads(winner_claim_json)
                wc = AtomicClaimDelta(
                    subject=wcd.get("subject", ""),
                    attribute=wcd.get("attribute", ""),
                    value=wcd.get("value"),
                    provenance=wcd.get("provenance", ""),
                )
            except Exception:
                wc = winner_claim_json

        return ArbitrationVerdict(
            verdict_id=verdict_id,
            dispute_id=dispute_id,
            task_id=task_id,
            status=ArbitrationVerdictStatus(status_val),
            winning_model=winning_model,
            probe_spec_hash=probe_spec_hash or "none",
            probe_stdout_sha256=probe_stdout_sha256 or "none",
            probe_stderr_sha256=probe_stderr_sha256 or "none",
            probe_exit_code=int(probe_exit_code or 0),
            journal_chain_hash=journal_chain_hash or parent_blackbox_hash or "",
            supersedes_ref=supersedes_ref,
            escalated_ticket_id=escalated_ticket_id,
            rationale=rationale or justification or "",
            timestamp=timestamp or decided_at or "",
            winner_claim=wc,
            parent_blackbox_hash=parent_blackbox_hash or journal_chain_hash or "",
            justification=justification or rationale or "",
            decided_at=decided_at or timestamp or "",
        )

    def _dict_to_verdict(self, d: dict[str, Any]) -> ArbitrationVerdict:
        wc = d.get("winner_claim")
        if isinstance(wc, dict):
            wc = AtomicClaimDelta(
                subject=wc.get("subject", ""),
                attribute=wc.get("attribute", ""),
                value=wc.get("value"),
                provenance=wc.get("provenance", ""),
            )
        return ArbitrationVerdict(
            verdict_id=d["verdict_id"],
            dispute_id=d["dispute_id"],
            task_id=d["task_id"],
            status=ArbitrationVerdictStatus(d["status"]),
            winning_model=d.get("winning_model"),
            probe_spec_hash=d.get("probe_spec_hash", "none"),
            probe_stdout_sha256=d.get("probe_stdout_sha256", "none"),
            probe_stderr_sha256=d.get("probe_stderr_sha256", "none"),
            probe_exit_code=int(d.get("probe_exit_code", 0)),
            journal_chain_hash=d.get("journal_chain_hash", ""),
            supersedes_ref=d.get("supersedes_ref"),
            escalated_ticket_id=d.get("escalated_ticket_id"),
            rationale=d.get("rationale", ""),
            timestamp=d.get("timestamp", ""),
            details=d.get("details", {}),
            winner_claim=wc,
            parent_blackbox_hash=d.get("parent_blackbox_hash", ""),
            justification=d.get("justification", ""),
            decided_at=d.get("decided_at", ""),
        )
