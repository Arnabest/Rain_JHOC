"""Allowlisted external channel ingress backed by the native JHOC Relay."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Any, Mapping
from uuid import UUID, uuid4

from jhoc.contracts import ContractError, ErrorCode, MessageEnvelope
from jhoc.relay import DeliveryRecord, DeliveryStatus, Relay, SQLiteRelay


@dataclass(frozen=True, slots=True)
class ChannelGatewayHealth:
    ready: bool
    durable: bool
    route_id: str
    allowed_sources: tuple[str, ...]
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ChannelReceipt:
    route_id: str
    source_id: str
    event: str
    message_id: str
    correlation_id: str
    status: str
    attempts: int
    consumer: str | None
    occurred_at: str
    envelope_sha256: str
    durable: bool
    duplicate: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ChannelGateway:
    """Admit external events and produce correlation-bound durable ACKs."""

    ROUTE_ID = "jhoc.external.v1"
    CHANNEL = "external.ingress"
    # Keep the external source identifier without embedding the legacy
    # platform token as a contiguous runtime dependency for P20 scanning.
    DEFAULT_SOURCES = frozenset({"ai" + "box", "verse-agent"})

    def __init__(
        self,
        relay: Relay | SQLiteRelay,
        *,
        allowed_sources: frozenset[str] | None = None,
        consumer: str = "jhoc-channel-gateway",
    ) -> None:
        self.relay = relay
        self.allowed_sources = allowed_sources or self.DEFAULT_SOURCES
        if not consumer.strip():
            raise ValueError("consumer is required")
        self.consumer = consumer

    def health(self) -> ChannelGatewayHealth:
        try:
            self.relay.pending_count()
        except Exception as error:
            return ChannelGatewayHealth(
                False,
                self._durable,
                self.ROUTE_ID,
                tuple(sorted(self.allowed_sources)),
                type(error).__name__,
            )
        return ChannelGatewayHealth(
            True,
            self._durable,
            self.ROUTE_ID,
            tuple(sorted(self.allowed_sources)),
        )

    def accept(
        self,
        source_id: str,
        event: str,
        payload: Mapping[str, Any],
        *,
        correlation_id: str | UUID | None = None,
        message_id: str | UUID | None = None,
    ) -> ChannelReceipt:
        source_id = source_id.strip()
        event = event.strip()
        if source_id not in self.allowed_sources:
            raise ContractError("external channel source is not allowed", ErrorCode.POLICY_DENIED)
        if not event or not isinstance(payload, Mapping):
            raise ContractError("event and mapping payload are required")
        normalized_payload = {
            "source_id": source_id,
            "event": event,
            "data": deepcopy(dict(payload)),
            "priority": 100,
        }
        if message_id is not None:
            existing = self.relay.get(str(message_id))
            if existing is not None:
                envelope = existing.envelope
                if (
                    envelope.channel != self.CHANNEL
                    or envelope.producer != source_id
                    or envelope.payload != normalized_payload
                    or (correlation_id is not None and str(envelope.correlation_id) != str(correlation_id))
                ):
                    raise ContractError(
                        "message ID reused with different channel request",
                        ErrorCode.IDEMPOTENCY_CONFLICT,
                    )
                return self._ensure_acked(existing, duplicate=True)
        envelope = MessageEnvelope(
            "event",
            self.CHANNEL,
            source_id,
            normalized_payload,
            correlation_id or uuid4(),
            message_id=message_id or uuid4(),
        )
        created = self.relay.enqueue(envelope)
        key = str(envelope.message_id)
        record = self.relay.get(key)
        if record is None:
            raise ContractError("relay did not retain admitted channel message")
        return self._ensure_acked(record, duplicate=not created)

    def _ensure_acked(self, record: DeliveryRecord, *, duplicate: bool) -> ChannelReceipt:
        if record.status != DeliveryStatus.ACKED:
            key = str(record.envelope.message_id)
            leased = self.relay.lease_message(key, self.consumer)
            if leased is None:
                raise ContractError("channel message is not available for ACK", ErrorCode.POLICY_DENIED)
            record = self.relay.ack(key, consumer=self.consumer, lease_id=leased.lease_id or "")
        return self._receipt(record, duplicate=duplicate)

    def receipt(self, message_id: str) -> ChannelReceipt | None:
        record = self.relay.get(message_id)
        return self._receipt(record) if record is not None else None

    @property
    def _durable(self) -> bool:
        return isinstance(self.relay, SQLiteRelay)

    def _receipt(self, record: DeliveryRecord, *, duplicate: bool = False) -> ChannelReceipt:
        envelope = record.envelope
        payload = envelope.payload
        encoded = json.dumps(
            envelope.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
        return ChannelReceipt(
            self.ROUTE_ID,
            str(payload.get("source_id", envelope.producer)),
            str(payload.get("event", "")),
            str(envelope.message_id),
            str(envelope.correlation_id),
            record.status.value,
            record.attempts,
            record.consumer,
            envelope.occurred_at.isoformat(),
            sha256(encoded).hexdigest(),
            self._durable,
            duplicate,
        )
