"""JHOC Memory Invariant Distiller & Prompt-Mean Normalization Engine.

Implements C3 from Phase 2 Architectural Review:
1. Normalizes memory records by hard character/token budget:
   - Golden Invariant ceiling: strictly <= 500 characters (approx <= 350 tokens).
2. Mandatory provenance metadata:
   - source_ref: required tracking file/session/task.
   - evidence_sha256: 64-char SHA-256 hex digest of the raw evidence payload.
3. Automatic trace segregation:
   - Raw multi-turn conversation logs, debug outputs, and verbose traces are diverted
     to out-of-band sidecar files in logs/op-log/ to prevent Token-Mean RAG pollution.
4. Single canonical store alignment: records are normalized prior to SQLite persistence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import secrets
from typing import Any, Mapping

from jhoc.contracts.errors import ContractError, ErrorCode
from jhoc.memory_store.store import MemoryRecord, MemoryType


MAX_INVARIANT_BODY_CHARS = 500
MAX_METADATA_HEADROOM_CHARS = 120
MAX_TOTAL_RECORD_CHARS = MAX_INVARIANT_BODY_CHARS + MAX_METADATA_HEADROOM_CHARS  # 620
MAX_INVARIANT_CHARS = MAX_INVARIANT_BODY_CHARS


@dataclass(frozen=True, slots=True)
class DistilledRecord:
    record: MemoryRecord
    sidecar_trace_path: str | None
    raw_evidence_sha256: str


class MemoryDistiller:
    """Extracts compact golden invariants while safely segregating raw verbose traces."""

    def __init__(self, workspace_root: Path | str | None = None) -> None:
        self.root = Path(workspace_root).resolve() if workspace_root else Path.cwd()
        self.op_log_dir = self.root / "logs" / "op-log"
        self.op_log_dir.mkdir(parents=True, exist_ok=True)

    def distill(
        self,
        content: Mapping[str, Any],
        memory_type: MemoryType | str,
        source_ref: str,
        sensitivity: str = "INTERNAL",
        record_id: str = "",
        project_id: str = "jhoc",
    ) -> DistilledRecord:
        """Distill and bound a memory record into a clean, normalized Golden Invariant."""
        if not source_ref or not str(source_ref).strip():
            raise ContractError("source_ref is mandatory for memory provenance", ErrorCode.INVALID_CONTRACT)

        # 1. Compute full SHA-256 of the raw evidence payload prior to any modification
        raw_canonical_bytes = json.dumps(content, sort_keys=True, ensure_ascii=False).encode("utf-8")
        evidence_sha256 = hashlib.sha256(raw_canonical_bytes).hexdigest()

        # 2. Detect verbose traces that should be diverted to out-of-band sidecars
        sidecar_path_str: str | None = None
        clean_content = dict(content)

        trace_keys = [k for k in clean_content.keys() if "trace" in k.lower() or "transcript" in k.lower() or "raw_log" in k.lower()]
        has_large_payload = any(len(str(v)) > 300 for v in clean_content.values())

        if trace_keys or has_large_payload:
            now_iso = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
            nonce = secrets.token_hex(4)
            sidecar_file = self.op_log_dir / f"trace_{now_iso}_{evidence_sha256[:8]}_{nonce}.jsonl"
            sidecar_payload = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source_ref": source_ref,
                "evidence_sha256": evidence_sha256,
                "raw_content": dict(content),
            }
            temp_file = self.op_log_dir / f".tmp_{sidecar_file.name}"
            temp_file.write_text(json.dumps(sidecar_payload, ensure_ascii=False) + "\n", encoding="utf-8")
            temp_file.replace(sidecar_file)
            sidecar_path_str = str(sidecar_file.relative_to(self.root)).replace("\\", "/")

            # Strip bulky traces from the in-memory core content
            for k in trace_keys:
                del clean_content[k]

        # 3. Ensure invariant brevity (max 500 chars total for the content body)
        summary_str = json.dumps(clean_content, ensure_ascii=False)
        if len(summary_str) > MAX_INVARIANT_CHARS:
            # Condense content into bounded golden invariant keys
            rule_text = str(clean_content.get("rule") or clean_content.get("invariant") or clean_content.get("lesson") or "")
            symptom_text = str(clean_content.get("symptom") or clean_content.get("problem") or "")
            prevention_text = str(clean_content.get("prevention") or clean_content.get("fix") or "")

            condensed = {
                "symptom": symptom_text[:120],
                "invariant": rule_text[:180] or summary_str[:180],
                "prevention": prevention_text[:120],
            }
            clean_content = {k: v for k, v in condensed.items() if v}

        # 4. Attach mandatory cryptographic evidence and sidecar reference
        clean_content["evidence_sha256"] = evidence_sha256
        if sidecar_path_str:
            clean_content["sidecar_trace"] = sidecar_path_str

        # Final sanity check on bounded character length (body <= 500, total <= 620)
        final_serialized = json.dumps(clean_content, ensure_ascii=False)
        if len(final_serialized) > MAX_TOTAL_RECORD_CHARS:
            inv_text = str(clean_content.get("invariant") or clean_content.get("symptom") or "")
            clean_content = {
                "invariant": inv_text[:180],
                "evidence_sha256": evidence_sha256,
                "sidecar_trace": sidecar_path_str or "",
            }
            while len(json.dumps(clean_content, ensure_ascii=False)) > MAX_TOTAL_RECORD_CHARS and len(clean_content["invariant"]) > 10:
                clean_content["invariant"] = clean_content["invariant"][:-10]

        rec = MemoryRecord(
            content=clean_content,
            memory_type=MemoryType(memory_type),
            source_ref=source_ref,
            sensitivity=sensitivity,
            record_id=record_id,
            project_id=project_id,
        )

        return DistilledRecord(
            record=rec,
            sidecar_trace_path=sidecar_path_str,
            raw_evidence_sha256=evidence_sha256,
        )
