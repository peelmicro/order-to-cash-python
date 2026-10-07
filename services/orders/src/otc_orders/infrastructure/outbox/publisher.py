"""The publisher port of the relay, and what it publishes.

Lives in `infrastructure.outbox`, deliberately NOT in `application.ports`: only the relay uses it,
and below `application` the `layers-orders` contract keeps every handler from reaching a publisher
(OI16; #8 put `IFactPublisher` in its Application ports, where a handler could inject it).
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
