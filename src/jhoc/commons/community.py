from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from threading import RLock
from typing import Mapping, Any
from uuid import uuid4

from jhoc.contracts.errors import ContractError, ErrorCode
from jhoc.trust import TrustStore


class CommunityMessageType(StrEnum):
    POST = "POST"
    REPLY = "REPLY"
    HANDOFF = "HANDOFF"
    REVIEW = "REVIEW"


@dataclass(frozen=True, slots=True)
class CommunityMessage:
    message_type: CommunityMessageType
    author: str
    content: Mapping[str, Any]
    evidence_refs: tuple[str, ...]
    message_id: str = ""
    verified: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        object.__setattr__(self, "message_type", CommunityMessageType(self.message_type))
        if not self.message_id:
            object.__setattr__(self, "message_id", f"community:{uuid4()}")
        if not self.author.strip() or not isinstance(self.content, Mapping) or not self.evidence_refs:
            raise ContractError("community content requires author, content, and evidence")


class Commons:
    def __init__(self, trust: TrustStore | None = None) -> None:
        self.trust = trust or TrustStore()
        self._messages: dict[str, CommunityMessage] = {}
        self._lock = RLock()

    def publish(
        self,
        message: CommunityMessage,
        *,
        eligible_evidence: bool,
        identity_id: str,
        session_id: str | None = None,
    ) -> CommunityMessage:
        if not eligible_evidence or not message.verified:
            raise ContractError("community messages require eligible verified evidence", ErrorCode.POLICY_DENIED)
        identity = self.trust.get(identity_id)
        permission = f"commons.{message.message_type.value.lower()}"
        if (
            identity is None
            or identity.subject != message.author
            or not (
                self.trust.authorize(identity.identity_id, permission, session_id=session_id)
                or self.trust.authorize(identity.identity_id, "commons.publish", session_id=session_id)
            )
        ):
            raise ContractError("community author identity or permission denied", ErrorCode.POLICY_DENIED)
        with self._lock:
            if message.message_id in self._messages:
                raise ContractError("community message already exists", ErrorCode.IDEMPOTENCY_CONFLICT)
            self._messages[message.message_id] = message
            return message

    def messages(self) -> tuple[CommunityMessage, ...]:
        with self._lock:
            return tuple(self._messages.values())
