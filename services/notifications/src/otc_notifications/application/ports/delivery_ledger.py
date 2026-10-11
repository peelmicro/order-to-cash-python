"""`DeliveryLedger`: the durable `(eventId, consumer)` record that makes a duplicate email
impossible (R17, R18).

Record-first, then send, then `forget` when the send throws (`dispatch.py` states why). The
adapter composes the canonical, byte-identical `IdempotentConsumer`; `forget` is this service's own
compensating statement.
"""

import enum
from typing import Protocol
from uuid import UUID


class LedgerOutcome(enum.Enum):
    RECORDED = "recorded"
    DUPLICATE = "duplicate"


class DeliveryLedger(Protocol):
    async def record(self, event_id: UUID) -> LedgerOutcome:
        """Insert `(event_id, notifications)`; `DUPLICATE` when the pair was already recorded."""
        ...

    async def forget(self, event_id: UUID) -> None:
        """Delete the pair (the compensation of a failed send)."""
        ...
