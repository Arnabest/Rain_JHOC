from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from threading import RLock

from jhoc.lens import LensCollector, LogEntry
from jhoc.origin import OriginRuntime, StartupState
from jhoc.storage import ArtifactStore, EventStore, StateStore


class CoreState(StrEnum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    DEGRADED = "DEGRADED"
    STOPPED = "STOPPED"


@dataclass(frozen=True, slots=True)
class CoreHealth:
    state: CoreState
    origin: StartupState
    storage_ready: bool
    lens_ready: bool


class CoreRuntime:
    """Owns local stores and observability, with no legacy runtime imports."""

    def __init__(
        self,
        origin: OriginRuntime | None = None,
        *,
        state_store: StateStore | None = None,
        event_store: EventStore | None = None,
        artifact_store: ArtifactStore | None = None,
        lens: LensCollector | None = None,
    ) -> None:
        self.origin = origin or OriginRuntime()
        self.state = CoreState.CREATED
        self.state_store = state_store or StateStore()
        self.event_store = event_store or EventStore()
        self.artifact_store = artifact_store or ArtifactStore()
        self.lens = lens or LensCollector()
        self._lock = RLock()

    def start(self) -> CoreHealth:
        with self._lock:
            if self.state not in {CoreState.CREATED, CoreState.STOPPED}:
                return self.health()
            origin_health = self.origin.start() if self.origin.state in {StartupState.CREATED, StartupState.STOPPED} else self.origin.health()
            self.state = CoreState.RUNNING if origin_health.state in {StartupState.RUNNING, StartupState.SAFE_MODE} else CoreState.DEGRADED
            self.lens.emit(LogEntry("core started", "core", fields={"origin_state": origin_health.state.value}))
            return self.health()

    def stop(self) -> None:
        with self._lock:
            self.origin.stop()
            self.state = CoreState.STOPPED

    def health(self) -> CoreHealth:
        return CoreHealth(self.state, self.origin.state, True, True)
