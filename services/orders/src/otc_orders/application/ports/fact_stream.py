"""`FactStreamSubscriber`: the transport port of the saga's one Kafka consumer (`design.md` 5.1).

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
    headers: tuple[tuple[str, bytes], ...]  # kept for feature 27's traceparent


class FactStreamSubscriber(Protocol):
    async def run(
        self, handler: Callable[[FactMessage], Awaitable[None]], stop: asyncio.Event
    ) -> None:
        """Deliver records one at a time (SO9).

        The handler runs to completion BEFORE the record's offset is committed; a handler that
        raises leaves the offset uncommitted and the record is delivered again, before any later
        record of the same partition.
        """
        ...
