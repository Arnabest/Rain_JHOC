"""JHOC-native single-start, persistent provider supervisor.

The supervisor is deliberately small: Relay owns delivery state while this
component owns provider connections and correlation-bound responses.  It is
usable with both the in-memory and SQLite Relay and does not import legacy
Agent Bus code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import Event, Lock, RLock, Thread, local
import os
import sqlite3
import socketserver
from typing import Any, Callable, Mapping
from uuid import UUID, uuid4

from jhoc.contracts import ContractError, MessageEnvelope
from jhoc.relay import Relay, SQLiteRelay


ProviderHandler = Callable[[Mapping[str, Any]], Mapping[str, Any]]


@dataclass(frozen=True, slots=True)
class ProviderConnection:
    provider_id: str
    handler: ProviderHandler
    connected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_heartbeat: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SupervisorResponse:
    correlation_id: str
    request_id: str
    provider_id: str
    status: str
    payload: Mapping[str, Any]
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    session_id: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "correlation_id": self.correlation_id,
            "request_id": self.request_id,
            "provider_id": self.provider_id,
            "status": self.status,
            "payload": dict(self.payload),
            "received_at": self.received_at.isoformat(),
            "session_id": self.session_id,
            "error": self.error,
        }


class JHOCSupervisor:
    """One long-lived local coordinator for provider request/response flow.

    ``start`` is idempotent for the same instance and rejects a second
    supervisor using the same durable path.  Provider handlers remain
    registered across requests; reconnecting is simply registering the same
    provider again, which replaces the old connection without losing queued
    work.
    """

    ROUTE = "jhoc.supervisor.v1"
    CHANNEL = "supervisor.request"
    RESPONSE_CHANNEL = "supervisor.response"
    _process_locks: dict[str, Lock] = {}
    _process_locks_guard = RLock()

    def __init__(
        self,
        relay: Relay | SQLiteRelay,
        *,
        lock_path: str | Path | None = None,
        poll_interval: float = 0.02,
        lease_seconds: float = 30.0,
    ) -> None:
        if poll_interval <= 0:
            raise ValueError("poll_interval must be positive")
        self.relay = relay
        self.poll_interval = poll_interval
        self.lease_seconds = lease_seconds
        self.lock_path = Path(lock_path) if lock_path is not None else None
        self._connections: dict[str, ProviderConnection] = {}
        self._responses: dict[str, SupervisorResponse] = {}
        self._waiters: dict[str, Event] = {}
        self._lock = RLock()
        self._stop = Event()
        self._thread: Thread | None = None
        self._started = False
        self._lock_held = False
        self._response_db: sqlite3.Connection | None = None
        self._correlation_local = local()
        if isinstance(relay, SQLiteRelay):
            self._response_db = sqlite3.connect(relay.path, check_same_thread=False, timeout=30)
            self._response_db.execute(
                "CREATE TABLE IF NOT EXISTS jhoc_supervisor_response ("
                "correlation_id TEXT PRIMARY KEY, request_id TEXT NOT NULL, provider_id TEXT NOT NULL, "
                "status TEXT NOT NULL, payload TEXT NOT NULL, received_at TEXT NOT NULL, session_id TEXT, error TEXT)"
            )
            columns = {row[1] for row in self._response_db.execute("PRAGMA table_info(jhoc_supervisor_response)")}
            if "session_id" not in columns:
                self._response_db.execute("ALTER TABLE jhoc_supervisor_response ADD COLUMN session_id TEXT")
                self._response_db.commit()
            self._response_db.commit()
            self._load_responses()

    def start(self) -> "JHOCSupervisor":
        with self._lock:
            if self._started:
                return self
            self._acquire_singleton()
            self._stop.clear()
            self._thread = Thread(target=self._dispatch_loop, name="jhoc-supervisor", daemon=True)
            self._thread.start()
            self._started = True
            return self

    def stop(self, *, timeout: float = 2.0) -> None:
        with self._lock:
            if not self._started:
                if self._response_db is not None:
                    self._response_db.close()
                    self._response_db = None
                return
            self._stop.set()
            thread = self._thread
        if thread is not None:
            thread.join(timeout=max(0.0, timeout))
        with self._lock:
            self._started = False
            self._thread = None
            self._connections.clear()
            self._release_singleton()
            if self._response_db is not None:
                self._response_db.close()
                self._response_db = None

    def register_provider(
        self,
        provider_id: str,
        handler: ProviderHandler,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> ProviderConnection:
        provider_id = provider_id.strip()
        if not provider_id or not callable(handler):
            raise ContractError("provider_id and callable handler are required")
        connection = ProviderConnection(provider_id, handler, metadata=dict(metadata or {}))
        with self._lock:
            self._connections[provider_id] = connection
        return connection

    def heartbeat(self, provider_id: str) -> ProviderConnection:
        with self._lock:
            current = self._connections.get(provider_id)
            if current is None:
                raise ContractError("provider is not connected")
            refreshed = ProviderConnection(
                current.provider_id,
                current.handler,
                current.connected_at,
                datetime.now(timezone.utc),
                current.metadata,
            )
            self._connections[provider_id] = refreshed
            return refreshed

    def providers(self) -> tuple[ProviderConnection, ...]:
        with self._lock:
            return tuple(self._connections.values())

    def submit(
        self,
        payload: Mapping[str, Any],
        *,
        provider_id: str | None = None,
        correlation_id: str | UUID | None = None,
        request_id: str | UUID | None = None,
    ) -> str:
        if not self._started:
            raise RuntimeError("supervisor is not started")
        if not isinstance(payload, Mapping):
            raise ContractError("payload must be a mapping")
        correlation = UUID(str(correlation_id)) if correlation_id is not None else uuid4()
        envelope = MessageEnvelope(
            "command",
            self.CHANNEL,
            "jhoc-supervisor",
            {"provider_id": provider_id, "data": dict(payload)},
            correlation,
            message_id=request_id or uuid4(),
        )
        self.relay.enqueue(envelope)
        with self._lock:
            self._waiters.setdefault(str(correlation), Event())
        return str(correlation)

    def response(self, correlation_id: str | UUID) -> SupervisorResponse | None:
        with self._lock:
            return self._responses.get(str(correlation_id))

    def await_response(self, correlation_id: str | UUID, *, timeout: float = 30.0) -> SupervisorResponse | None:
        key = str(correlation_id)
        with self._lock:
            response = self._responses.get(key)
            waiter = self._waiters.setdefault(key, Event())
        if response is None:
            waiter.wait(timeout=max(0.0, timeout))
        with self._lock:
            return self._responses.get(key)

    def health(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": self._started,
                "providers": len(self._connections),
                "provider_ids": sorted(self._connections),
                "pending": self.relay.pending_count(),
                "responses": len(self._responses),
                "route": self.ROUTE,
            }

    def _dispatch_loop(self) -> None:
        while not self._stop.is_set():
            try:
                delivered = self._dispatch_once()
            except Exception:
                delivered = False
            if not delivered and not self._stop.is_set():
                self._stop.wait(self.poll_interval)

    def _dispatch_once(self) -> bool:
        with self._lock:
            if not self._connections:
                return False
        record = self.relay.lease("jhoc-supervisor")
        if record is None:
            return False
        envelope = record.envelope
        requested = envelope.payload.get("provider_id")
        with self._lock:
            connection = self._connections.get(requested) if requested else None
            if connection is None and requested is None and self._connections:
                connection = next(iter(self._connections.values()))
        if connection is None:
            try:
                self.relay.defer(
                    str(envelope.message_id), consumer="jhoc-supervisor", lease_id=record.lease_id or ""
                )
            except Exception:
                pass
            return True
        try:
            self._correlation_local.id = str(envelope.correlation_id)
            result = connection.handler(dict(envelope.payload.get("data", {})))
            if not isinstance(result, Mapping):
                raise TypeError("provider response must be a mapping")
            request_data = dict(envelope.payload.get("data", {}))
            response = SupervisorResponse(
                str(envelope.correlation_id), str(envelope.message_id), connection.provider_id,
                str(result.get("status", "accepted")), dict(result),
                session_id=str(request_data.get("session_id")) if request_data.get("session_id") else None,
            )
            with self._lock:
                self._responses[response.correlation_id] = response
                waiter = self._waiters.get(response.correlation_id)
                if waiter:
                    waiter.set()
                self._persist_response(response)
            try:
                self.relay.ack(str(envelope.message_id), consumer="jhoc-supervisor", lease_id=record.lease_id or "")
            except Exception:
                pass
        except Exception as error:
            try:
                self.relay.nack(
                    str(envelope.message_id), consumer="jhoc-supervisor", lease_id=record.lease_id or "",
                    retryable=True, error=f"{type(error).__name__}: {error}",
                )
            except Exception:
                pass
        finally:
            self._correlation_local.id = None
        return True

    def _acquire_singleton(self) -> None:
        key = str(self.lock_path.resolve()) if self.lock_path else f"memory:{id(self.relay)}"
        with self._process_locks_guard:
            lock = self._process_locks.setdefault(key, Lock())
        if not lock.acquire(blocking=False):
            raise RuntimeError("JHOC supervisor already running")
        self._lock_key, self._singleton_lock = key, lock
        if self.lock_path is not None:
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
                fd = os.open(str(self.lock_path), flags)
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                    stream.write(json.dumps({"pid": os.getpid()}))
            except FileExistsError as error:
                # A crashed process may leave the marker behind.  Reclaim it
                # only when the recorded PID is no longer alive; active owners
                # remain fail-closed.
                try:
                    owner = json.loads(self.lock_path.read_text(encoding="utf-8")).get("pid")
                    os.kill(int(owner), 0)
                except (OSError, ValueError, TypeError, json.JSONDecodeError):
                    try:
                        self.lock_path.unlink(missing_ok=True)
                        fd = os.open(str(self.lock_path), flags)
                        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                            stream.write(json.dumps({"pid": os.getpid()}))
                    except Exception:
                        lock.release()
                        raise RuntimeError("JHOC supervisor already running") from error
                else:
                    lock.release()
                    raise RuntimeError("JHOC supervisor already running") from error
            except Exception:
                lock.release()
                raise
        self._lock_held = True

    def _release_singleton(self) -> None:
        if not self._lock_held:
            return
        if self.lock_path is not None:
            try:
                self.lock_path.unlink(missing_ok=True)
            except OSError:
                pass
        self._singleton_lock.release()
        self._lock_held = False

    def _load_responses(self) -> None:
        if self._response_db is None:
            return
        for row in self._response_db.execute(
            "SELECT correlation_id, request_id, provider_id, status, payload, received_at, session_id, error "
            "FROM jhoc_supervisor_response"
        ):
            try:
                response = SupervisorResponse(
                    row[0], row[1], row[2], row[3], json.loads(row[4]),
                    datetime.fromisoformat(row[5]), row[6], row[7],
                )
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            self._responses[response.correlation_id] = response

    def _persist_response(self, response: SupervisorResponse) -> None:
        if self._response_db is None:
            return
        self._response_db.execute(
            "INSERT OR REPLACE INTO jhoc_supervisor_response "
            "(correlation_id, request_id, provider_id, status, payload, received_at, session_id, error) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                response.correlation_id, response.request_id, response.provider_id,
                response.status, json.dumps(dict(response.payload), sort_keys=True),
                response.received_at.isoformat(), response.session_id, response.error,
            ),
        )
        self._response_db.commit()


class JHOCSupervisorServer:
    """Local JSON-lines endpoint for persistent provider connections.

    ``register`` connections stay open; the supervisor pushes each request as
    a JSON line and waits for a matching ``response`` line. Client connections
    can submit work or query a correlation-bound response independently.
    """

    def __init__(self, supervisor: JHOCSupervisor, *, host: str = "127.0.0.1", port: int = 0) -> None:
        self.supervisor, self.host, self.port = supervisor, host, port
        self._server: socketserver.ThreadingTCPServer | None = None
        self._thread: Thread | None = None

    def start(self) -> tuple[str, int]:
        if self._server is not None:
            return self.host, self.port
        supervisor = self.supervisor

        class Handler(socketserver.StreamRequestHandler):
            def _send(self, value: Mapping[str, Any]) -> None:
                self.wfile.write((json.dumps(dict(value), sort_keys=True) + "\n").encode("utf-8"))
                self.wfile.flush()

            def handle(self) -> None:
                line = self.rfile.readline()
                if not line:
                    return
                request = json.loads(line.decode("utf-8"))
                operation = request.get("op")
                if operation == "register":
                    provider_id = str(request.get("provider_id", "")).strip()
                    io_lock = Lock()

                    def invoke(payload: Mapping[str, Any]) -> Mapping[str, Any]:
                        with io_lock:
                            correlation = getattr(supervisor._correlation_local, "id", None) or str(uuid4())
                            self._send({"op": "request", "correlation_id": correlation, "payload": dict(payload)})
                            reply = self.rfile.readline()
                            if not reply:
                                raise ConnectionError("provider connection closed")
                            value = json.loads(reply.decode("utf-8"))
                            if value.get("correlation_id") != correlation:
                                raise ValueError("provider response correlation mismatch")
                            return value.get("payload", {})

                    supervisor.register_provider(provider_id, invoke, metadata=request.get("metadata", {}))
                    self._send({"ok": True, "op": "registered", "provider_id": provider_id})
                    while not supervisor._stop.wait(0.5):
                        pass
                    return
                if operation == "submit":
                    correlation = supervisor.submit(request.get("payload", {}), provider_id=request.get("provider_id"))
                    self._send({"ok": True, "correlation_id": correlation})
                    return
                if operation == "response":
                    response = supervisor.response(request.get("correlation_id", ""))
                    self._send({"ok": response is not None, "response": response.to_dict() if response else None})
                    return
                if operation == "health":
                    self._send({"ok": True, **supervisor.health()})
                    return
                self._send({"ok": False, "error": "unsupported operation"})

        self._server = socketserver.ThreadingTCPServer((self.host, self.port), Handler)
        self._server.daemon_threads = True
        self.host, self.port = self._server.server_address
        self._thread = Thread(target=self._server.serve_forever, name="jhoc-supervisor-endpoint", daemon=True)
        self._thread.start()
        return self.host, self.port

    def stop(self) -> None:
        server, thread = self._server, self._thread
        self._server = self._thread = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=2)


__all__ = ["JHOCSupervisor", "JHOCSupervisorServer", "ProviderConnection", "SupervisorResponse"]
