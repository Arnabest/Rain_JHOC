from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Iterable, Mapping, Protocol, runtime_checkable

from jhoc.contracts.errors import ContractError, ErrorCode
from jhoc.contracts.models import PluginManifest


class PluginProtocolError(ContractError):
    """Raised when a plugin violates lifecycle or protocol semantics."""


class PluginLifecycle(StrEnum):
    DISCOVERED = "DISCOVERED"
    VERIFIED = "VERIFIED"
    INSTALLED = "INSTALLED"
    LOADED = "LOADED"
    NEGOTIATED = "NEGOTIATED"
    INITIALIZED = "INITIALIZED"
    READY = "READY"
    RUNNING = "RUNNING"
    DRAINING = "DRAINING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


class HealthStatus(StrEnum):
    READY = "READY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class PluginDescription:
    plugin_id: str
    protocol_version: str
    capabilities: tuple[str, ...]
    lifecycle: PluginLifecycle


@runtime_checkable
class PluginProtocol(Protocol):
    """Required plugin surface; implementations own their internal resources."""

    def describe(self) -> Mapping[str, Any]: ...

    def health(self) -> Mapping[str, Any]: ...

    def initialize(self, config: Mapping[str, Any]) -> None: ...

    def validate(self, request: Mapping[str, Any]) -> None: ...

    def invoke(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def stream(self, request: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]: ...

    def cancel(self, work_id: str) -> None: ...

    def checkpoint(self) -> Mapping[str, Any]: ...

    def drain(self) -> None: ...

    def shutdown(self) -> None: ...


_ALLOWED: dict[PluginLifecycle, frozenset[PluginLifecycle]] = {
    PluginLifecycle.DISCOVERED: frozenset({PluginLifecycle.VERIFIED, PluginLifecycle.FAILED}),
    PluginLifecycle.VERIFIED: frozenset({PluginLifecycle.INSTALLED, PluginLifecycle.FAILED}),
    PluginLifecycle.INSTALLED: frozenset({PluginLifecycle.LOADED, PluginLifecycle.FAILED}),
    PluginLifecycle.LOADED: frozenset({PluginLifecycle.NEGOTIATED, PluginLifecycle.FAILED}),
    PluginLifecycle.NEGOTIATED: frozenset({PluginLifecycle.INITIALIZED, PluginLifecycle.FAILED}),
    PluginLifecycle.INITIALIZED: frozenset({PluginLifecycle.READY, PluginLifecycle.FAILED}),
    PluginLifecycle.READY: frozenset({PluginLifecycle.RUNNING, PluginLifecycle.DRAINING, PluginLifecycle.STOPPED, PluginLifecycle.FAILED}),
    PluginLifecycle.RUNNING: frozenset({PluginLifecycle.READY, PluginLifecycle.DRAINING, PluginLifecycle.FAILED}),
    PluginLifecycle.DRAINING: frozenset({PluginLifecycle.STOPPED, PluginLifecycle.FAILED}),
    PluginLifecycle.STOPPED: frozenset(),
    PluginLifecycle.FAILED: frozenset({PluginLifecycle.STOPPED}),
}


class PluginHost:
    """Lifecycle and boundary host for one plugin instance."""

    def __init__(self, manifest: PluginManifest, plugin: PluginProtocol, *, protocol_version: str = "1.0") -> None:
        if not isinstance(plugin, PluginProtocol):
            raise PluginProtocolError("plugin does not implement the native protocol", ErrorCode.PLUGIN_VALIDATION_FAILED)
        self.manifest = manifest
        self.plugin = plugin
        self.protocol_version = protocol_version
        self.state = PluginLifecycle.DISCOVERED
        self._last_error: str | None = None

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def _move(self, target: PluginLifecycle) -> None:
        if target not in _ALLOWED[self.state]:
            raise PluginProtocolError(
                f"invalid plugin transition {self.state} -> {target}", ErrorCode.PLUGIN_STATE_ERROR
            )
        self.state = target

    def _fail(self, error: Exception) -> None:
        self._last_error = f"{type(error).__name__}: {error}"
        if self.state != PluginLifecycle.FAILED and PluginLifecycle.FAILED in _ALLOWED[self.state]:
            self.state = PluginLifecycle.FAILED

    def verify(self) -> None:
        try:
            if self.manifest.protocol_version != self.protocol_version:
                raise PluginProtocolError("manifest protocol version mismatch", ErrorCode.PLUGIN_PROTOCOL_MISMATCH)
            if self.manifest.verification_status not in {"VERIFIED", "TRUSTED"}:
                raise PluginProtocolError("plugin is not verified", ErrorCode.PLUGIN_VALIDATION_FAILED)
            description = self.plugin.describe()
            if description.get("plugin_id") != self.manifest.plugin_id:
                raise PluginProtocolError("plugin identity mismatch", ErrorCode.PLUGIN_VALIDATION_FAILED)
            self._move(PluginLifecycle.VERIFIED)
        except Exception as error:
            self._fail(error)
            raise

    def install(self) -> None:
        self._move(PluginLifecycle.INSTALLED)

    def load(self) -> None:
        self._move(PluginLifecycle.LOADED)

    def handshake(self) -> PluginDescription:
        if self.state != PluginLifecycle.LOADED:
            raise PluginProtocolError("handshake requires LOADED plugin", ErrorCode.PLUGIN_STATE_ERROR)
        try:
            description = self.plugin.describe()
            if description.get("protocol_version") != self.protocol_version:
                raise PluginProtocolError("plugin handshake version mismatch", ErrorCode.PLUGIN_PROTOCOL_MISMATCH)
            self._move(PluginLifecycle.NEGOTIATED)
            return PluginDescription(
                self.manifest.plugin_id,
                self.protocol_version,
                tuple(description.get("capabilities", ())),
                self.state,
            )
        except Exception as error:
            self._fail(error)
            raise

    def initialize(self, config: Mapping[str, Any] | None = None) -> None:
        if self.state != PluginLifecycle.NEGOTIATED:
            raise PluginProtocolError("initialize requires NEGOTIATED plugin", ErrorCode.PLUGIN_STATE_ERROR)
        try:
            self.plugin.initialize(config or {})
            self._move(PluginLifecycle.INITIALIZED)
            self._move(PluginLifecycle.READY)
        except Exception as error:
            self._fail(error)
            raise

    def health(self) -> Mapping[str, Any]:
        if self.state in {PluginLifecycle.DISCOVERED, PluginLifecycle.STOPPED}:
            return {"status": HealthStatus.UNAVAILABLE.value, "lifecycle": self.state.value}
        try:
            value = dict(self.plugin.health())
        except Exception as error:
            self._fail(error)
            return {"status": HealthStatus.UNAVAILABLE.value, "lifecycle": self.state.value, "error": str(error)}
        value.setdefault("status", HealthStatus.READY.value if self.state == PluginLifecycle.READY else HealthStatus.DEGRADED.value)
        value["lifecycle"] = self.state.value
        return value

    def validate(self, request: Mapping[str, Any]) -> None:
        if self.state not in {PluginLifecycle.READY, PluginLifecycle.RUNNING}:
            raise PluginProtocolError("validate requires READY plugin", ErrorCode.PLUGIN_STATE_ERROR)
        self.plugin.validate(request)

    def invoke(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        if self.state != PluginLifecycle.READY:
            raise PluginProtocolError("invoke requires READY plugin", ErrorCode.PLUGIN_STATE_ERROR)
        try:
            self.plugin.validate(request)
            self._move(PluginLifecycle.RUNNING)
            result = self.plugin.invoke(request)
            self._move(PluginLifecycle.READY)
            return result
        except Exception as error:
            self._fail(error)
            raise

    def stream(self, request: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
        if self.state != PluginLifecycle.READY:
            raise PluginProtocolError("stream requires READY plugin", ErrorCode.PLUGIN_STATE_ERROR)
        self.plugin.validate(request)
        self._move(PluginLifecycle.RUNNING)

        def consume() -> Iterable[Mapping[str, Any]]:
            try:
                yield from self.plugin.stream(request)
                self._move(PluginLifecycle.READY)
            except Exception as error:
                self._fail(error)
                raise
            finally:
                # Closing a consumer early must not strand the host in RUNNING.
                if self.state == PluginLifecycle.RUNNING:
                    self._move(PluginLifecycle.READY)

        return consume()

    def cancel(self, work_id: str) -> None:
        if self.state != PluginLifecycle.RUNNING:
            raise PluginProtocolError("cancel requires RUNNING plugin", ErrorCode.PLUGIN_STATE_ERROR)
        self.plugin.cancel(work_id)

    def checkpoint(self) -> Mapping[str, Any]:
        if self.state not in {PluginLifecycle.INITIALIZED, PluginLifecycle.READY, PluginLifecycle.RUNNING, PluginLifecycle.DRAINING}:
            raise PluginProtocolError("checkpoint is unavailable in current lifecycle", ErrorCode.PLUGIN_STATE_ERROR)
        return self.plugin.checkpoint()

    def drain(self) -> None:
        if self.state not in {PluginLifecycle.READY, PluginLifecycle.RUNNING}:
            raise PluginProtocolError("drain requires READY or RUNNING plugin", ErrorCode.PLUGIN_STATE_ERROR)
        try:
            self._move(PluginLifecycle.DRAINING)
            self.plugin.drain()
        except Exception as error:
            self._fail(error)
            raise

    def shutdown(self) -> None:
        if self.state == PluginLifecycle.STOPPED:
            return
        try:
            self.plugin.shutdown()
            self._move(PluginLifecycle.STOPPED)
        except Exception as error:
            self._fail(error)
            raise
