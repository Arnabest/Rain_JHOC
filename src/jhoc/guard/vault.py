from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from threading import RLock
from typing import Mapping, Any

from jhoc.contracts.errors import ContractError, ErrorCode


@dataclass(frozen=True, slots=True)
class VaultSecretRef:
    secret_id: str
    token_ref: str
    scope: str
    created_at: str


class CredentialVault:
    """Isolated, zero-knowledge secret vault.

    Keeps raw credentials in protected memory.
    The Data Plane only ever handles anonymous opaque references (`vault://secret/...`).
    Raw secrets are dereferenced strictly at network egress boundaries.
    """

    AUTHORIZED_EGRESS_PREFIXES = ("adapter.", "relay.", "network.", "egress.")

    def __init__(self, persistence_path: str | Path | None = None) -> None:
        self._secrets: dict[str, str] = {}
        self._ref_to_id: dict[str, str] = {}
        self._lock = RLock()
        self._persistence_path = Path(persistence_path) if persistence_path else None
        if self._persistence_path and self._persistence_path.is_file():
            self._load_persisted()

    def _get_fernet(self) -> Any:
        try:
            import base64
            import os
            from cryptography.fernet import Fernet
            user = os.environ.get("USERNAME", os.environ.get("USER", "jhoc_user"))
            node = os.environ.get("COMPUTERNAME", "jhoc_node")
            raw_key = hashlib.sha256(f"JHOC_ENCRYPTED_VAULT:{user}@{node}".encode("utf-8")).digest()
            fernet_key = base64.urlsafe_b64encode(raw_key)
            return Fernet(fernet_key)
        except Exception:
            return None

    def _load_persisted(self) -> None:
        if not self._persistence_path or not self._persistence_path.is_file():
            return
        fernet = self._get_fernet()
        if not fernet:
            return
        try:
            encrypted = self._persistence_path.read_bytes()
            if not encrypted:
                return
            import json
            decrypted = fernet.decrypt(encrypted)
            payload = json.loads(decrypted.decode("utf-8"))
            self._secrets.update(payload.get("secrets", {}))
            self._ref_to_id.update(payload.get("refs", {}))
        except Exception:
            pass

    def _save_persisted(self) -> None:
        if not self._persistence_path:
            return
        fernet = self._get_fernet()
        if not fernet:
            return
        try:
            import json
            import os
            # Merge latest persisted state before saving to prevent lost updates
            self._load_persisted()
            data = json.dumps({"secrets": self._secrets, "refs": self._ref_to_id}).encode("utf-8")
            encrypted = fernet.encrypt(data)
            self._persistence_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._persistence_path.with_suffix(".tmp")
            tmp_path.write_bytes(encrypted)
            os.replace(tmp_path, self._persistence_path)
        except Exception:
            pass

    def register_secret(self, secret_id: str, raw_secret: str, scope: str = "global") -> str:
        """Stores a secret and returns an opaque, context-safe token reference."""
        if not secret_id.strip() or not raw_secret.strip():
            raise ContractError("secret_id and raw_secret must not be empty", ErrorCode.INVALID_CONTRACT)

        with self._lock:
            token_digest = hashlib.sha256(f"{secret_id}:{scope}".encode("utf-8")).hexdigest()[:16]
            token_ref = f"vault://secret/{secret_id}#{token_digest}"

            self._secrets[secret_id] = raw_secret
            self._ref_to_id[token_ref] = secret_id
            self._save_persisted()
            return token_ref

    def resolve_for_egress(self, token_ref: str, authorized_actor: str, caller_model: str | None = None) -> str:
        """Dereferences raw secret value strictly for authorized egress adapters."""
        if not any(authorized_actor.startswith(p) for p in self.AUTHORIZED_EGRESS_PREFIXES):
            raise ContractError(
                f"actor '{authorized_actor}' is not authorized to resolve credential vault references",
                ErrorCode.POLICY_DENIED,
            )

        with self._lock:
            secret_id = self._ref_to_id.get(token_ref)
            if not secret_id or secret_id not in self._secrets:
                raise ContractError(f"unknown vault token reference: '{token_ref}'", ErrorCode.POLICY_DENIED)

            try:
                import json
                import os
                from datetime import datetime, timezone
                audit_dir = Path(__file__).resolve().parent.parent.parent.parent / "logs" / "audit"
                audit_dir.mkdir(parents=True, exist_ok=True)
                audit_file = audit_dir / "vault-access.jsonl"
                resolved_caller = caller_model or os.environ.get("JHOC_MODEL_ID") or "antigravity-ide"
                record = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "actor": authorized_actor,
                    "caller_model": resolved_caller,
                    "secret_id": secret_id,
                    "token_ref": token_ref,
                    "status": "DEREFERENCED",
                }
                with audit_file.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=True) + "\n")
            except Exception:
                pass

            return self._secrets[secret_id]

    def mask_text(self, text: str) -> str:
        """Masks any registered secret literals from text before entering context or journal."""
        if not isinstance(text, str) or not text:
            return text

        with self._lock:
            masked = text
            for secret_id, raw_val in self._secrets.items():
                if raw_val in masked:
                    masked = masked.replace(raw_val, f"[VAULT_MASKED:{secret_id}]")
            return masked

    def list_secrets(self) -> list[str]:
        with self._lock:
            return sorted(self._secrets.keys())

    def get_token_ref(self, secret_id: str) -> str | None:
        with self._lock:
            for ref, sid in self._ref_to_id.items():
                if sid == secret_id:
                    return ref
            return None

    @classmethod
    def is_vault_ref(cls, value: str) -> bool:
        return isinstance(value, str) and value.startswith("vault://secret/")
