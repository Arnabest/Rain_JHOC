"""JHOC local application assembly and health surface."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from jhoc.atlas import AtlasStore, SQLiteAtlasStore
from jhoc.bench import Bench
from jhoc.channel import ChannelGateway
from jhoc.commons import Commons, SQLiteCommons
from jhoc.conductor import Conductor
from jhoc.context import ContextOrchestrator
from jhoc.core import CoreRuntime
from jhoc.forge import Forge, SQLiteForge
from jhoc.gate import Gate
from jhoc.graph import GraphStore, SQLiteGraphStore
from jhoc.guard import GuardRuntime, SQLiteGuardRuntime
from jhoc.idle import IdleScheduler, SQLiteIdleScheduler
from jhoc.independence import IndependenceReport
from jhoc.ingest import IngestScanner, OfflineMigration
from jhoc.lens import LensCollector, SQLiteLensCollector
from jhoc.memory_store import MemoryStore, SQLiteMemoryStore
from jhoc.ops import CutoverValidator
from jhoc.origin import OriginRuntime
from jhoc.output import OutputRuntime
from jhoc.proof import ProofStore, SQLiteProofStore
from jhoc.quota import QuotaManager, ResourcePlan, SQLiteQuotaManager
from jhoc.registry import CapabilityRegistry, SQLiteCapabilityRegistry
from jhoc.relay import Relay, SQLiteRelay
from jhoc.restore import RecoveryManager, SQLiteRecoveryManager
from jhoc.runner import OperationJournal, Runner
from jhoc.shelf import Shelf, SQLiteShelf
from jhoc.storage import (
    ArtifactStore,
    EventStore,
    SQLiteArtifactStore,
    SQLiteEventStore,
    SQLiteStateStore,
    SQLiteStore,
    StateStore,
)
from jhoc.supervisor import JHOCSupervisor
from jhoc.trust import SQLiteTrustStore, TrustStore


@dataclass(frozen=True, slots=True)
class ApplicationHealth:
    running: bool
    origin_state: str
    module_count: int
    legacy_runtime_connected: bool
    channel_gateway_ready: bool
    channel_gateway_sources: tuple[str, ...]
    supervisor_running: bool = False
    supervisor_providers: int = 0


@dataclass(frozen=True, slots=True)
class ApplicationConfig:
    """Explicit application wiring; a path enables durable local state."""

    storage_path: str | Path | None = None


class JHOCApplication:
    """Single-process assembly for local development and acceptance smoke tests."""

    MODULES = (
        "origin", "core", "contracts", "flow", "trust", "config", "relay", "lens", "guard", "atlas",
        "graph", "memory", "proof", "registry", "shelf", "quota", "conductor", "context", "runner", "gate",
        "output", "commons", "idle", "forge", "bench", "restore", "ingest", "ops", "storage", "plugins", "channel",
    )

    def __init__(self, config: ApplicationConfig | None = None) -> None:
        config = config or ApplicationConfig()
        self.config = config
        capacity = ResourcePlan(cpu_units=4, gpu_units=1, memory_mb=4096, token_budget=100_000, max_concurrency=4)
        self._durable_handles: tuple[object, ...] = ()
        self._closed = False
        if config.storage_path is not None:
            path = str(Path(config.storage_path))
            opened: list[object] = []
            try:
                self.trust = self._open(SQLiteTrustStore(path), opened)
                self.guard = self._open(SQLiteGuardRuntime(path), opened)
                sqlite = self._open(SQLiteStore(path), opened)
                self.state_store = SQLiteStateStore(sqlite)
                self.event_store = SQLiteEventStore(sqlite)
                self.artifact_store = SQLiteArtifactStore(sqlite)
                self.registry = self._open(SQLiteCapabilityRegistry(path), opened)
                self.shelf = self._open(SQLiteShelf(path), opened)
                self.quota = self._open(SQLiteQuotaManager(path, capacity), opened)
                self.relay = self._open(SQLiteRelay(path), opened)
                self.proof = self._open(SQLiteProofStore(path), opened)
                self.atlas = self._open(SQLiteAtlasStore(path), opened)
                self.graph = self._open(SQLiteGraphStore(path), opened)
                self.memory = self._open(SQLiteMemoryStore(path), opened)
                self.idle = self._open(SQLiteIdleScheduler(path), opened)
                self.forge = self._open(SQLiteForge(path), opened)
                self.restore = self._open(SQLiteRecoveryManager(path), opened)
                self.lens = self._open(SQLiteLensCollector(path), opened)
                self.commons = self._open(SQLiteCommons(path, self.trust), opened)
                self._durable_handles = tuple(reversed(opened))
            except Exception:
                self._close_handles(reversed(opened), suppress_errors=True)
                raise
        else:
            self.trust = TrustStore()
            self.guard = GuardRuntime()
            self.state_store = StateStore()
            self.event_store = EventStore()
            self.artifact_store = ArtifactStore()
            self.registry = CapabilityRegistry()
            self.shelf = Shelf()
            self.quota = QuotaManager(capacity)
            self.relay = Relay()
            self.proof = ProofStore()
            self.atlas = AtlasStore()
            self.graph = GraphStore()
            self.memory = MemoryStore()
            self.idle = IdleScheduler()
            self.forge = Forge()
            self.restore = RecoveryManager()
            self.lens = LensCollector()
            self.commons = Commons(self.trust)
        try:
            self.origin = OriginRuntime(self.trust)
            self.core = CoreRuntime(
                self.origin,
                state_store=self.state_store,
                event_store=self.event_store,
                artifact_store=self.artifact_store,
                lens=self.lens,
            )
            self.conductor = Conductor(self.registry, self.shelf, self.quota, self.guard)
            self.context = ContextOrchestrator(self.state_store)
            self.runner = Runner(OperationJournal(self.state_store))
            self.gate = Gate(self.proof)
            self.output = OutputRuntime(self.proof, self.state_store)
            self.bench = Bench()
            self.ingest = IngestScanner()
            self.migration = OfflineMigration(self.ingest)
            self.cutover = CutoverValidator(self.trust)
            self.channel_gateway = ChannelGateway(self.relay)
            lock_path = None
            if config.storage_path is not None:
                storage = Path(config.storage_path)
                lock_path = storage.with_suffix(storage.suffix + ".supervisor.lock")
            self.supervisor = JHOCSupervisor(self.relay, lock_path=lock_path)
        except Exception:
            self._close_handles(self._durable_handles, suppress_errors=True)
            self._durable_handles = ()
            self._closed = True
            raise

    def start(self) -> ApplicationHealth:
        if self._closed:
            raise RuntimeError("application is closed")
        try:
            self.core.start()
            self.supervisor.start()
        except Exception:
            try:
                self.supervisor.stop()
            except Exception:
                pass
            try:
                self.core.stop()
            except Exception:
                pass
            handles = self._durable_handles
            self._durable_handles = ()
            self._closed = True
            self._close_handles(handles, suppress_errors=True)
            raise
        return self.health()

    def stop(self) -> ApplicationHealth:
        self.supervisor.stop()
        self.core.stop()
        health = self.health()
        handles = self._durable_handles
        self._durable_handles = ()
        self._closed = True
        self._close_handles(handles)
        return health

    def health(self) -> ApplicationHealth:
        channel_health = self.channel_gateway.health()
        return ApplicationHealth(
            self.core.state.value == "RUNNING",
            self.origin.state.value,
            len(self.MODULES),
            False,
            channel_health.ready,
            channel_health.allowed_sources,
            self.supervisor.health()["running"],
            self.supervisor.health()["providers"],
        )

    @staticmethod
    def _open(handle: object, opened: list[object]) -> object:
        opened.append(handle)
        return handle

    @staticmethod
    def _close_handles(handles: Iterable[object], *, suppress_errors: bool = False) -> None:
        first_error: Exception | None = None
        for handle in handles:
            close = getattr(handle, "close", None)
            if close is None:
                continue
            try:
                close()
            except Exception as error:  # close every owned handle before surfacing one failure
                first_error = first_error or error
        if first_error is not None and not suppress_errors:
            raise first_error
