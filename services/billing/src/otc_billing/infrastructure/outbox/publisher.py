"""Billing's COPY of Orders' `infrastructure/outbox/publisher.py` (the canonical).

The canonical: `services/orders/src/otc_orders/infrastructure/outbox/publisher.py`.
After this docstring the copy equals it, modulo the token map `otc_orders` ->
`otc_billing` and `ORDERS_FACTS_TOPIC` -> `BILLING_FACTS_TOPIC`, and modulo the
formatter's line reflow of the longer names. Any other difference fails
`tests/architecture/test_outbox_copy_parity.py`. Change the canonical, never this copy.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class PublishableFact:
    """One record, exactly as it goes on the wire."""

    event_id: UUID
    key: bytes  # str(correlation_id), UTF-8 (R15: the partition key)
    value: bytes  # the envelope: compact JSON, UTF-8
    headers: tuple[tuple[str, bytes], ...]


class FactPublicationError(Exception):
    """The broker did not acknowledge every record of the batch. Carries the failed event ids."""

    def __init__(self, event_ids: Sequence[UUID], reason: str) -> None:
        super().__init__(f"{len(event_ids)} fact(s) not acknowledged: {reason}")
        self.event_ids = tuple(event_ids)


class FactPublisher(Protocol):
    async def publish(self, facts: Sequence[PublishableFact]) -> None:
        """Return only when EVERY fact is acknowledged, else raise `FactPublicationError`."""
        ...
