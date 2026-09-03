from __future__ import annotations

from datetime import datetime
import json
import sqlite3
from uuid import UUID

from jhoc.config import RuntimeMode
from jhoc.contracts.errors import ContractError, ErrorCode
from jhoc.trust import Identity

from .policy import (
    Decision,
    GuardRuntime,
    PolicyBundle,
    PolicyDecision,
    PolicyRequest,
    PolicyRule,
)


class SQLiteGuardRuntime(GuardRuntime):
    """Durable policy bundle history and decision receipts."""

    def __init__(self, path: str) -> None:
        super().__init__()
        self._db = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self._closed = False
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS jhoc_guard_meta (
                singleton INTEGER PRIMARY KEY CHECK(singleton = 1), revision INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS jhoc_guard_bundle (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                version TEXT NOT NULL,
                source TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS jhoc_guard_decision (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL,
                policy_ref TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS jhoc_guard_decision_policy
                ON jhoc_guard_decision(policy_ref, sequence);
            """
        )
        self._db.execute("INSERT OR IGNORE INTO jhoc_guard_meta(singleton,revision) VALUES(1,0)")
        self._db.commit()
        self._revision = 0
        self._load()

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._db.close()
                self._closed = True

    def _load(self) -> None:
        with self._lock:
            self._reload_bundles_unlocked()
            self._reload_decisions_unlocked()

    def evaluate(
        self,
        identity: Identity | None,
        request: PolicyRequest,
        *,
        mode: RuntimeMode = RuntimeMode.OFFLINE,
    ) -> PolicyDecision:
        self._refresh_if_stale()
        return super().evaluate(identity, request, mode=mode)

    def decisions(self, *, policy_ref: str | None = None) -> tuple[PolicyDecision, ...]:
        with self._lock:
            self._require_open()
            self._reload_decisions_unlocked()
        return super().decisions(policy_ref=policy_ref)

    def bundle_history(self) -> tuple[PolicyBundle, ...]:
        self._refresh_if_stale()
        return super().bundle_history()

    def _store_bundle(self, bundle: PolicyBundle) -> None:
        payload = json.dumps(_encode_bundle(bundle), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        with self._lock:
            self._require_open()
            try:
                self._db.execute("BEGIN IMMEDIATE")
                existing = self._db.execute(
                    "SELECT payload FROM jhoc_guard_bundle WHERE version=? ORDER BY sequence",
                    (bundle.version,),
                ).fetchall()
                if existing and any(row[0] != payload for row in existing):
                    raise ContractError(
                        "policy version reused with different content", ErrorCode.IDEMPOTENCY_CONFLICT
                    )
                if not existing:
                    self._db.execute(
                        "INSERT INTO jhoc_guard_bundle(version,source,payload) VALUES(?,?,?)",
                        (bundle.version, bundle.source, payload),
                    )
                    current = int(
                        self._db.execute(
                            "SELECT revision FROM jhoc_guard_meta WHERE singleton=1"
                        ).fetchone()[0]
                    )
                    self._db.execute(
                        "UPDATE jhoc_guard_meta SET revision=? WHERE singleton=1", (current + 1,)
                    )
                self._db.commit()
                self._reload_bundles_unlocked()
            except Exception:
                if self._db.in_transaction:
                    self._db.rollback()
                raise

    def _store_decision(self, decision: PolicyDecision) -> None:
        payload = json.dumps(_encode_decision(decision), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        with self._lock:
            self._require_open()
            try:
                self._db.execute("BEGIN IMMEDIATE")
                self._db.execute(
                    "INSERT INTO jhoc_guard_decision(request_id,policy_ref,payload) VALUES(?,?,?)",
                    (str(decision.request_id), decision.policy_ref, payload),
                )
                self._db.commit()
            except Exception:
                if self._db.in_transaction:
                    self._db.rollback()
                raise
            super()._store_decision(decision)

    def _refresh_if_stale(self) -> None:
        with self._lock:
            self._require_open()
            current = int(
                self._db.execute("SELECT revision FROM jhoc_guard_meta WHERE singleton=1").fetchone()[0]
            )
            if current != self._revision:
                self._reload_bundles_unlocked()

    def _reload_bundles_unlocked(self) -> None:
        rows: list[tuple[str]] | None = None
        revision = self._revision
        for _ in range(5):
            before = int(
                self._db.execute("SELECT revision FROM jhoc_guard_meta WHERE singleton=1").fetchone()[0]
            )
            candidate_rows = self._db.execute(
                "SELECT payload FROM jhoc_guard_bundle ORDER BY sequence"
            ).fetchall()
            after = int(
                self._db.execute("SELECT revision FROM jhoc_guard_meta WHERE singleton=1").fetchone()[0]
            )
            if before == after:
                rows = candidate_rows
                revision = after
                break
        if rows is None:
            raise ContractError("policy changed continuously during refresh", ErrorCode.STALE_STATE)
        history = []
        for payload, in rows:
            bundle = _decode_bundle(json.loads(payload))
            history.append(bundle)
        self._bundle_history = history
        self._bundle = history[-1] if history else None
        self._revision = revision

    def _reload_decisions_unlocked(self) -> None:
        self._decisions = [
            _decode_decision(json.loads(payload))
            for payload, in self._db.execute(
                "SELECT payload FROM jhoc_guard_decision ORDER BY sequence"
            ).fetchall()
        ]

    def _require_open(self) -> None:
        if self._closed:
            raise ContractError("guard runtime is closed", ErrorCode.INVALID_CONTRACT)


def _encode_bundle(bundle: PolicyBundle) -> dict[str, object]:
    return {
        "version": bundle.version,
        "source": bundle.source,
        "rules": [
            {
                "rule_id": rule.rule_id,
                "effect": rule.effect.value,
                "operations": sorted(rule.operations),
                "max_risk_level": rule.max_risk_level,
                "external_side_effect": rule.external_side_effect,
                "requires_network": rule.requires_network,
                "sensitive": rule.sensitive,
                "required_permission": rule.required_permission,
                "priority": rule.priority,
            }
            for rule in bundle.rules
        ],
    }


def _decode_bundle(value: dict[str, object]) -> PolicyBundle:
    rules = tuple(
        PolicyRule(
            str(rule["rule_id"]),
            str(rule["effect"]),
            frozenset(str(item) for item in rule.get("operations", [])),
            int(rule.get("max_risk_level", 0)),
            rule.get("external_side_effect"),
            rule.get("requires_network"),
            rule.get("sensitive"),
            rule.get("required_permission"),
            int(rule.get("priority", 0)),
        )
        for rule in value["rules"]
    )
    return PolicyBundle(str(value["version"]), str(value["source"]), rules)


def _encode_decision(decision: PolicyDecision) -> dict[str, object]:
    return {
        "decision": decision.decision.value,
        "request_id": str(decision.request_id),
        "policy_ref": decision.policy_ref,
        "matched_rules": list(decision.matched_rules),
        "reason": decision.reason,
        "evaluated_at": decision.evaluated_at.isoformat(),
        "operation": decision.operation,
        "identity_id": decision.identity_id,
        "mode": decision.mode,
    }


def _decode_decision(value: dict[str, object]) -> PolicyDecision:
    return PolicyDecision(
        Decision(str(value["decision"])),
        UUID(str(value["request_id"])),
        str(value["policy_ref"]),
        tuple(str(item) for item in value["matched_rules"]),
        str(value["reason"]),
        datetime.fromisoformat(str(value["evaluated_at"])),
        str(value.get("operation", "")),
        str(value["identity_id"]) if value.get("identity_id") else None,
        str(value.get("mode", "OFFLINE")),
    )
