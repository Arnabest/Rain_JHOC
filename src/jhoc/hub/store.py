"""JHOC Multi-Model Hub - Daemonless, SQLite-WAL unified presence, file lease, and relay store."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import threading
from typing import Any, Mapping
from uuid import uuid4

from .models import (
    FileLease,
    HubEnvelope,
    LeaseStatus,
    MessageStatus,
    ModelPresence,
    ModelPresenceState,
    TaskSlot,
)


class JHOCMultiModelHub:
    """Unified SQLite WAL repository managing multi-model presence, file leases, and relay messages."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(str(self.db_path), timeout=10.0)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA busy_timeout=5000;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            self._local.conn = conn
        return self._local.conn

    def _init_db(self) -> None:
        conn = self._get_connection()
        with conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS hub_presence (
                    model_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    task_id TEXT,
                    pid INTEGER,
                    last_heartbeat TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS hub_file_leases (
                    lease_id TEXT PRIMARY KEY,
                    file_path TEXT NOT NULL,
                    locked_by_model TEXT NOT NULL,
                    task_id TEXT,
                    granted_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    ttl_seconds INTEGER NOT NULL,
                    status TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_file_lease_path ON hub_file_leases(file_path, status);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_hub_active_file_lease ON hub_file_leases(file_path) WHERE status = 'ACTIVE';

                CREATE TABLE IF NOT EXISTS hub_messages (
                    message_id TEXT PRIMARY KEY,
                    source_model TEXT NOT NULL,
                    target_model TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    correlation_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    reply_payload_json TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_hub_msg_target ON hub_messages(target_model, status);
                CREATE INDEX IF NOT EXISTS idx_hub_msg_corr ON hub_messages(correlation_id);

                CREATE TABLE IF NOT EXISTS hub_task_slots (
                    task_id TEXT PRIMARY KEY,
                    owner_model TEXT NOT NULL,
                    title TEXT NOT NULL,
                    workspace TEXT NOT NULL,
                    baseline_sha TEXT NOT NULL,
                    status TEXT NOT NULL,
                    armed_at TEXT NOT NULL,
                    closed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_task_slots_owner ON hub_task_slots(owner_model, status);
            """)

    def close(self) -> None:
        if hasattr(self._local, "conn") and self._local.conn is not None:
            try:
                self._local.conn.close()
            except Exception:
                pass
            self._local.conn = None

    # -------------------------------------------------------------------------
    # 1. Model Presence (Lobby)
    # -------------------------------------------------------------------------

    def register_presence(
        self,
        model_id: str,
        state: ModelPresenceState = ModelPresenceState.IDLE,
        task_id: str | None = None,
        pid: int | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ModelPresence:
        now_iso = datetime.now(timezone.utc).isoformat()
        meta_json = json.dumps(metadata or {}, ensure_ascii=True)
        conn = self._get_connection()
        with conn:
            conn.execute(
                """
                INSERT INTO hub_presence (model_id, state, task_id, pid, last_heartbeat, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(model_id) DO UPDATE SET
                    state = excluded.state,
                    task_id = excluded.task_id,
                    pid = excluded.pid,
                    last_heartbeat = excluded.last_heartbeat,
                    metadata_json = excluded.metadata_json
                """,
                (model_id, state.value, task_id, pid, now_iso, meta_json),
            )
        return ModelPresence(model_id, state, task_id, pid, now_iso, metadata or {})

    def heartbeat(self, model_id: str) -> bool:
        now_iso = datetime.now(timezone.utc).isoformat()
        conn = self._get_connection()
        with conn:
            cur = conn.execute(
                "UPDATE hub_presence SET last_heartbeat = ? WHERE model_id = ?",
                (now_iso, model_id),
            )
            return cur.rowcount > 0

    def get_active_models(self, stale_threshold_sec: int = 180) -> list[ModelPresence]:
        conn = self._get_connection()
        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(seconds=stale_threshold_sec)).isoformat()
        cur = conn.execute(
            """
            SELECT model_id, state, task_id, pid, last_heartbeat, metadata_json
            FROM hub_presence
            WHERE last_heartbeat >= ?
            ORDER BY last_heartbeat DESC
            """,
            (cutoff,),
        )
        results: list[ModelPresence] = []
        for mid, st, tid, pid, hb, mj in cur.fetchall():
            try:
                meta = json.loads(mj)
            except Exception:
                meta = {}
            results.append(ModelPresence(mid, ModelPresenceState(st), tid, pid, hb, meta))
        return results

    # -------------------------------------------------------------------------
    # 2. File Lease Registry (File Mutex)
    # -------------------------------------------------------------------------

    @staticmethod
    def normalize_file_path(file_path: str | Path) -> str:
        try:
            return Path(file_path).resolve().as_posix()
        except Exception:
            return str(file_path).replace("\\", "/")

    def acquire_file_lease(
        self,
        model_id: str,
        file_path: str | Path,
        task_id: str | None = None,
        ttl_seconds: int = 120,
        lease_id: str | None = None,
    ) -> tuple[bool, str, FileLease | None]:
        norm_path = self.normalize_file_path(file_path)
        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()
        expires_iso = (now_dt + timedelta(seconds=ttl_seconds)).isoformat()

        conn = self._get_connection()
        with conn:
            # Expire old active leases
            conn.execute(
                """
                UPDATE hub_file_leases
                SET status = 'EXPIRED'
                WHERE file_path = ? AND status = 'ACTIVE' AND expires_at <= ?
                """,
                (norm_path, now_iso),
            )

            # Check for existing active lease
            cur = conn.execute(
                """
                SELECT lease_id, locked_by_model, task_id, granted_at, expires_at, ttl_seconds, status
                FROM hub_file_leases
                WHERE file_path = ? AND status = 'ACTIVE'
                LIMIT 1
                """,
                (norm_path,),
            )
            row = cur.fetchone()
            if row:
                lid, locked_by, tid, granted, exp, ttl, st = row
                if locked_by != model_id:
                    lease = FileLease(lid, norm_path, locked_by, tid, granted, exp, ttl, LeaseStatus(st))
                    return (
                        False,
                        f"File is locked by model '{locked_by}' until {exp}",
                        lease,
                    )
                # Same model: Renew lease (verify lease_id if provided to prevent unauthenticated renewal hijacking)
                if lease_id and lease_id != lid:
                    return False, f"Lease token mismatch: cannot renew lease without valid lease_id (expected '{lid}')", None
                conn.execute(
                    "UPDATE hub_file_leases SET expires_at = ?, ttl_seconds = ? WHERE lease_id = ?",
                    (expires_iso, ttl_seconds, lid),
                )
                lease = FileLease(lid, norm_path, model_id, task_id or tid, granted, expires_iso, ttl_seconds, LeaseStatus.ACTIVE)
                return True, "Lease renewed", lease

            # Grant brand new lease
            new_lease_id = f"lease-{uuid4().hex[:12]}"
            try:
                conn.execute(
                    """
                    INSERT INTO hub_file_leases (lease_id, file_path, locked_by_model, task_id, granted_at, expires_at, ttl_seconds, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'ACTIVE')
                    """,
                    (new_lease_id, norm_path, model_id, task_id, now_iso, expires_iso, ttl_seconds),
                )
            except sqlite3.IntegrityError:
                # Concurrent race condition caught by idx_hub_active_file_lease unique index
                cur = conn.execute(
                    "SELECT lease_id, locked_by_model, task_id, granted_at, expires_at, ttl_seconds, status FROM hub_file_leases WHERE file_path = ? AND status = 'ACTIVE' LIMIT 1",
                    (norm_path,),
                )
                r = cur.fetchone()
                if r:
                    lease = FileLease(r[0], norm_path, r[1], r[2], r[3], r[4], r[5], LeaseStatus(r[6]))
                    return False, f"File is locked by model '{r[1]}' (concurrent race resolved by DB unique index)", lease
                return False, "File lease conflict detected", None

            lease = FileLease(new_lease_id, norm_path, model_id, task_id, now_iso, expires_iso, ttl_seconds, LeaseStatus.ACTIVE)
            return True, "Lease granted", lease

    def check_file_lease(self, file_path: str | Path, requesting_model_id: str | None = None) -> tuple[bool, FileLease | None]:
        norm_path = self.normalize_file_path(file_path)
        now_iso = datetime.now(timezone.utc).isoformat()
        conn = self._get_connection()
        cur = conn.execute(
            """
            SELECT lease_id, locked_by_model, task_id, granted_at, expires_at, ttl_seconds, status
            FROM hub_file_leases
            WHERE file_path = ? AND status = 'ACTIVE' AND expires_at > ?
            LIMIT 1
            """,
            (norm_path, now_iso),
        )
        row = cur.fetchone()
        if not row:
            return True, None  # Available!
        lid, locked_by, tid, granted, exp, ttl, st = row
        lease = FileLease(lid, norm_path, locked_by, tid, granted, exp, ttl, LeaseStatus(st))
        if requesting_model_id and locked_by == requesting_model_id:
            return True, lease  # Allowed: owned by caller
        return False, lease  # Denied: locked by another model

    def release_file_lease(self, model_id: str, file_path: str | Path, lease_id: str | None = None) -> bool:
        norm_path = self.normalize_file_path(file_path)
        conn = self._get_connection()
        with conn:
            query = """
                UPDATE hub_file_leases
                SET status = 'RELEASED'
                WHERE file_path = ? AND locked_by_model = ? AND status = 'ACTIVE'
            """
            params: list[Any] = [norm_path, model_id]
            if lease_id:
                query += " AND lease_id = ?"
                params.append(lease_id)
            cur = conn.execute(query, tuple(params))
            return cur.rowcount > 0

    def release_all_leases(self, model_id: str) -> int:
        conn = self._get_connection()
        with conn:
            cur = conn.execute(
                "UPDATE hub_file_leases SET status = 'RELEASED' WHERE locked_by_model = ? AND status = 'ACTIVE'",
                (model_id,),
            )
            return cur.rowcount

    def list_active_leases(self) -> list[FileLease]:
        now_iso = datetime.now(timezone.utc).isoformat()
        conn = self._get_connection()
        cur = conn.execute(
            """
            SELECT lease_id, file_path, locked_by_model, task_id, granted_at, expires_at, ttl_seconds, status
            FROM hub_file_leases
            WHERE status = 'ACTIVE' AND expires_at > ?
            ORDER BY granted_at DESC
            """,
            (now_iso,),
        )
        results: list[FileLease] = []
        for lid, fp, mid, tid, ga, ea, ttl, st in cur.fetchall():
            results.append(FileLease(lid, fp, mid, tid, ga, ea, ttl, LeaseStatus(st)))
        return results

    # -------------------------------------------------------------------------
    # 3. Inter-Model Relay Messaging & 3-Model Co-Review
    # -------------------------------------------------------------------------

    def send_message(
        self,
        source_model: str,
        target_model: str,
        operation: str,
        payload: Mapping[str, Any],
        correlation_id: str | None = None,
    ) -> str:
        msg_id = f"msg-{uuid4().hex[:12]}"
        corr_id = correlation_id or f"corr-{uuid4().hex[:12]}"
        now_iso = datetime.now(timezone.utc).isoformat()
        payload_json = json.dumps(payload, ensure_ascii=True)

        conn = self._get_connection()
        with conn:
            conn.execute(
                """
                INSERT INTO hub_messages (message_id, source_model, target_model, operation, payload_json, correlation_id, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?, ?)
                """,
                (msg_id, source_model, target_model, operation, payload_json, corr_id, now_iso, now_iso),
            )
        return msg_id

    def fetch_pending_messages(self, target_model: str, limit: int = 20) -> list[HubEnvelope]:
        conn = self._get_connection()
        cur = conn.execute(
            """
            SELECT message_id, source_model, target_model, operation, payload_json, correlation_id, status, created_at, updated_at, reply_payload_json
            FROM hub_messages
            WHERE target_model = ? AND status = 'PENDING'
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (target_model, limit),
        )
        envelopes: list[HubEnvelope] = []
        for mid, sm, tm, op, pj, cid, st, ca, ua, rpj in cur.fetchall():
            p = json.loads(pj) if pj else {}
            rp = json.loads(rpj) if rpj else None
            envelopes.append(HubEnvelope(mid, sm, tm, op, p, cid, MessageStatus(st), ca, ua, rp))
        return envelopes

    def claim_message(self, message_id: str, claiming_model: str) -> bool:
        """Atomically claim a PENDING message into IN_PROGRESS to prevent dual-processing."""
        now_iso = datetime.now(timezone.utc).isoformat()
        conn = self._get_connection()
        with conn:
            cur = conn.execute(
                """
                UPDATE hub_messages
                SET status = 'IN_PROGRESS', updated_at = ?
                WHERE message_id = ? AND target_model = ? AND status = 'PENDING'
                """,
                (now_iso, message_id, claiming_model),
            )
            return cur.rowcount > 0

    def reply_message(
        self,
        message_id: str,
        status: MessageStatus = MessageStatus.COMPLETED,
        reply_payload: Mapping[str, Any] | None = None,
    ) -> bool:
        now_iso = datetime.now(timezone.utc).isoformat()
        reply_json = json.dumps(reply_payload or {}, ensure_ascii=True) if reply_payload else None
        conn = self._get_connection()
        with conn:
            cur = conn.execute(
                """
                UPDATE hub_messages
                SET status = ?, updated_at = ?, reply_payload_json = ?
                WHERE message_id = ? AND status IN ('PENDING', 'IN_PROGRESS')
                """,
                (status.value, now_iso, reply_json, message_id),
            )
            return cur.rowcount > 0

    def get_messages_by_correlation(self, correlation_id: str) -> list[HubEnvelope]:
        conn = self._get_connection()
        cur = conn.execute(
            """
            SELECT message_id, source_model, target_model, operation, payload_json, correlation_id, status, created_at, updated_at, reply_payload_json
            FROM hub_messages
            WHERE correlation_id = ?
            ORDER BY created_at ASC
            """,
            (correlation_id,),
        )
        results: list[HubEnvelope] = []
        for mid, sm, tm, op, pj, cid, st, ca, ua, rpj in cur.fetchall():
            p = json.loads(pj) if pj else {}
            rp = json.loads(rpj) if rpj else None
            results.append(HubEnvelope(mid, sm, tm, op, p, cid, MessageStatus(st), ca, ua, rp))
        return results

    # -------------------------------------------------------------------------
    # 4. Multi-Task Slot Isolation
    # -------------------------------------------------------------------------

    def arm_task_slot(
        self,
        task_id: str,
        owner_model: str,
        title: str,
        workspace: str,
        baseline_sha: str,
    ) -> TaskSlot:
        now_iso = datetime.now(timezone.utc).isoformat()
        conn = self._get_connection()
        with conn:
            conn.execute(
                """
                INSERT INTO hub_task_slots (task_id, owner_model, title, workspace, baseline_sha, status, armed_at)
                VALUES (?, ?, ?, ?, ?, 'ARMED', ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    owner_model = excluded.owner_model,
                    title = excluded.title,
                    workspace = excluded.workspace,
                    baseline_sha = excluded.baseline_sha,
                    status = 'ARMED',
                    armed_at = excluded.armed_at
                """,
                (task_id, owner_model, title, workspace, baseline_sha, now_iso),
            )
        return TaskSlot(task_id, owner_model, title, workspace, baseline_sha, "ARMED", now_iso)

    def close_task_slot(self, task_id: str, owner_model: str) -> bool:
        now_iso = datetime.now(timezone.utc).isoformat()
        conn = self._get_connection()
        with conn:
            cur = conn.execute(
                """
                UPDATE hub_task_slots
                SET status = 'CLOSED', closed_at = ?
                WHERE task_id = ? AND owner_model = ? AND status = 'ARMED'
                """,
                (now_iso, task_id, owner_model),
            )
            return cur.rowcount > 0

    def get_active_task_slot(self, owner_model: str) -> TaskSlot | None:
        conn = self._get_connection()
        cur = conn.execute(
            """
            SELECT task_id, owner_model, title, workspace, baseline_sha, status, armed_at, closed_at
            FROM hub_task_slots
            WHERE owner_model = ? AND status = 'ARMED'
            ORDER BY armed_at DESC
            LIMIT 1
            """,
            (owner_model,),
        )
        row = cur.fetchone()
        if not row:
            return None
        tid, om, ttl, ws, sha, st, aa, ca = row
        return TaskSlot(tid, om, ttl, ws, sha, st, aa, ca)
