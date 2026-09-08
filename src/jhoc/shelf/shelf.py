from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from jhoc.contracts.errors import ContractError, ErrorCode
from jhoc.registry import CapabilityRecord, VerificationStatus


@dataclass(frozen=True, slots=True)
class ShelfEntry:
    capability_id: str
    version: str
    health: str


class Shelf:
    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], ShelfEntry] = {}
        self._lock = RLock()

    def admit(self, record: CapabilityRecord) -> ShelfEntry:
        if record.verification_status != VerificationStatus.VERIFIED or not record.manifest.shelf_eligible:
            raise ContractError("only verified shelf-eligible capabilities may be admitted", ErrorCode.POLICY_DENIED)
        entry = ShelfEntry(record.capability_id, record.version, record.health)
        with self._lock:
            self._entries[(entry.capability_id, entry.version)] = entry
        return entry

    def remove(self, capability_id: str, version: str) -> None:
        with self._lock:
            self._entries.pop((capability_id, version), None)

    def get(self, capability_id: str, version: str) -> ShelfEntry | None:
        with self._lock:
            return self._entries.get((capability_id, version))

    def entries(self) -> tuple[ShelfEntry, ...]:
        with self._lock:
            return tuple(self._entries.values())

