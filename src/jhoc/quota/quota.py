from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import RLock
from uuid import uuid4

from jhoc.contracts.errors import ContractError, ErrorCode


@dataclass(frozen=True, slots=True)
class ResourcePlan:
    cpu_units: int = 1
    gpu_units: int = 0
    memory_mb: int = 256
    token_budget: int = 4096
    max_concurrency: int = 1
    max_seconds: int = 300
    requires_network: bool = False
    max_temperature_c: float | None = None
    max_power_watts: float | None = None
    min_battery_percent: int | None = None

    def __post_init__(self) -> None:
        if any(value < 0 for value in (self.cpu_units, self.gpu_units, self.memory_mb, self.token_budget)):
            raise ContractError("resource values cannot be negative")
        if self.max_concurrency < 1 or self.max_seconds < 1:
            raise ContractError("concurrency and duration limits must be positive")
        if self.max_temperature_c is not None and self.max_temperature_c <= 0:
            raise ContractError("maximum temperature must be positive")
        if self.max_power_watts is not None and self.max_power_watts <= 0:
            raise ContractError("maximum power must be positive")
        if self.min_battery_percent is not None and not 0 <= self.min_battery_percent <= 100:
            raise ContractError("minimum battery percentage must be between 0 and 100")


@dataclass(frozen=True, slots=True)
class HardwareState:
    """Explicit local hardware/availability facts used by quota admission."""

    temperature_c: float | None = None
    power_watts: float | None = None
    battery_percent: int | None = None
    network_available: bool = False

    def __post_init__(self) -> None:
        if self.temperature_c is not None and self.temperature_c < -100:
            raise ContractError("hardware temperature is invalid")
        if self.power_watts is not None and self.power_watts < 0:
            raise ContractError("hardware power is invalid")
        if self.battery_percent is not None and not 0 <= self.battery_percent <= 100:
            raise ContractError("hardware battery percentage must be between 0 and 100")


@dataclass(frozen=True, slots=True)
class ResourceLease:
    lease_id: str
    owner: str
    plan: ResourcePlan
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class UsageRecord:
    lease_id: str
    owner: str
    tokens_used: int
    recorded_at: datetime


class QuotaManager:
    def __init__(self, capacity: ResourcePlan, hardware_state: HardwareState | None = None) -> None:
        self.capacity = capacity
        self._hardware_state = hardware_state
        self._leases: dict[str, ResourceLease] = {}
        self._usage: dict[str, UsageRecord] = {}
        self._lock = RLock()

    def acquire(self, owner: str, plan: ResourcePlan, *, now: datetime | None = None, hardware_state: HardwareState | None = None) -> ResourceLease:
        if not owner.strip():
            raise ContractError("resource lease owner is required")
        now = now or datetime.now(timezone.utc)
        with self._lock:
            self._reap(now)
            self._check_hardware(plan, hardware_state if hardware_state is not None else self._hardware_state)
            active = list(self._leases.values())
            used_cpu = sum(lease.plan.cpu_units for lease in active)
            used_gpu = sum(lease.plan.gpu_units for lease in active)
            used_memory = sum(lease.plan.memory_mb for lease in active)
            used_tokens = sum(lease.plan.token_budget for lease in active)
            used_concurrency = sum(lease.plan.max_concurrency for lease in active)
            if any((used_cpu + plan.cpu_units > self.capacity.cpu_units,
                    used_gpu + plan.gpu_units > self.capacity.gpu_units,
                    used_memory + plan.memory_mb > self.capacity.memory_mb,
                    used_tokens + plan.token_budget > self.capacity.token_budget,
                    used_concurrency + plan.max_concurrency > self.capacity.max_concurrency)):
                raise ContractError("resource quota exceeded", ErrorCode.POLICY_DENIED)
            lease = ResourceLease(str(uuid4()), owner, plan, now + timedelta(seconds=plan.max_seconds))
            self._leases[lease.lease_id] = lease
            return lease

    def release(self, lease_id: str) -> None:
        with self._lock:
            self._leases.pop(lease_id, None)

    def set_hardware_state(self, state: HardwareState | None) -> None:
        with self._lock:
            self._hardware_state = state

    def hardware_state(self) -> HardwareState | None:
        with self._lock:
            return self._hardware_state

    def record_usage(self, lease_id: str, *, tokens_used: int) -> UsageRecord:
        if tokens_used < 0:
            raise ContractError("usage cannot be negative")
        with self._lock:
            lease = self._leases.get(lease_id)
            if lease is None:
                raise ContractError("resource lease not found", ErrorCode.POLICY_DENIED)
            previous = self._usage.get(lease_id)
            total = (previous.tokens_used if previous else 0) + tokens_used
            if total > lease.plan.token_budget:
                raise ContractError("token usage exceeds lease budget", ErrorCode.POLICY_DENIED)
            record = UsageRecord(lease_id, lease.owner, total, datetime.now(timezone.utc))
            self._usage[lease_id] = record
            return record

    def usage(self, lease_id: str) -> UsageRecord | None:
        with self._lock:
            return self._usage.get(lease_id)

    def active(self) -> tuple[ResourceLease, ...]:
        with self._lock:
            self._reap(datetime.now(timezone.utc))
            return tuple(self._leases.values())

    def _reap(self, now: datetime) -> None:
        for key, lease in tuple(self._leases.items()):
            if lease.expires_at <= now:
                del self._leases[key]

    @staticmethod
    def _check_hardware(plan: ResourcePlan, state: HardwareState | None) -> None:
        requires_state = plan.requires_network or plan.max_temperature_c is not None or plan.max_power_watts is not None or plan.min_battery_percent is not None
        if requires_state and state is None:
            raise ContractError("required hardware state is unavailable", ErrorCode.POLICY_DENIED)
        if state is None:
            return
        if plan.requires_network and not state.network_available:
            raise ContractError("network is unavailable for requested lease", ErrorCode.POLICY_DENIED)
        if plan.max_temperature_c is not None and (state.temperature_c is None or state.temperature_c > plan.max_temperature_c):
            raise ContractError("hardware temperature exceeds lease limit", ErrorCode.POLICY_DENIED)
        if plan.max_power_watts is not None and (state.power_watts is None or state.power_watts > plan.max_power_watts):
            raise ContractError("hardware power exceeds lease limit", ErrorCode.POLICY_DENIED)
        if plan.min_battery_percent is not None and (state.battery_percent is None or state.battery_percent < plan.min_battery_percent):
            raise ContractError("battery level is below lease minimum", ErrorCode.POLICY_DENIED)
