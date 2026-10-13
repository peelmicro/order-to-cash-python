"""`FactStreamSubscriber`: the transport port of the service's one Kafka consumer.

Lives in `application.ports` so the presentation task depends on a port and never on aiokafka (the
`fact-producer-confinement` contract forbids the client in `application` and `presentation`).
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class FactMessage:
    topic: str
    partition: int
    offset: int
    key: bytes | None
    value: bytes
    headers: tuple[tuple[str, bytes], ...]  # the consume span's parent is read from `traceparent`


class FactStreamSubscriber(Protocol):
    async def run(
        self, handler: Callable[[FactMessage], Awaitable[None]], stop: asyncio.Event
    ) -> None:
        """Deliver records one at a time.

        The handler runs to completion BEFORE the record's offset is committed; a handler that
        raises leaves the offset uncommitted and the record is delivered again, before any later
        record of the same partition.
        """
        ...


class FactProcessor(Protocol):
    """The retry-then-dead-letter wrapper around a record's processing (`R16`; implemented by
    `infrastructure.messaging.fact_retry.FactRetry`).

    `process` runs `work` until it succeeds or the attempts are exhausted; in the latter case the
    record is dead-lettered and the call RETURNS (the offset then commits). It raises only if the
    dead-letter publication fails (the record is then delivered again) or on cancellation.
    """

    async def process(
        self, message: FactMessage, event_type: str, work: Callable[[], Awaitable[None]]
    ) -> None: ...
