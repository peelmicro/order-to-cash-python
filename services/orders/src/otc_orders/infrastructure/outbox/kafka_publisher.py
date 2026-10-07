"""`KafkaFactPublisher`: the ONLY module that imports aiokafka (OI16, L23, L24).

* No aiokafka object is built in `__init__` (an `AIOKafkaProducer` binds to the loop that creates
  it, L23): `start()` constructs and starts it inside the running loop, `stop()` stops it.
* `producer_options()` is what `start()` passes: `enable_idempotence=True`, `acks="all"` (OI7: a
  producer-internal retry can neither reorder the records of a partition nor duplicate one the
  broker already accepted). aiokafka has no `max_in_flight` option: the installed 0.14.0 sender
  hands a node at most one produce request at a time (`producer/sender.py:141`, `drain_by_nodes(
  ignore_nodes=self._in_flight, ...)`, `self._in_flight.add(node_id)` at `:148`, removed after the
  request completes at `:290`) and mutes every partition of an in-flight batch (`:149-150`), so one
  partition never has two batches in flight; idempotence requires `acks` of `"all"` or `-1`
  (`producer/producer.py:265-272`).
* `publish` sends in the given order (the futures come back in that order), then gathers them with
  `return_exceptions=True` so every future's exception is retrieved (no "Future exception was never
  retrieved"), and raises `FactPublicationError` naming the failed event ids. aiokafka's own error
  types never cross this module; the three calls it makes are typed through a private `Protocol`.
"""

import asyncio
import contextlib
from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from aiokafka import AIOKafkaProducer

from otc_orders.infrastructure.outbox.publisher import FactPublicationError, PublishableFact
from otc_orders.infrastructure.outbox.topic import ORDERS_FACTS_TOPIC
from otc_orders.infrastructure.settings import KafkaSettings


class _Producer(Protocol):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def send(
        self, topic: str, *, value: bytes, key: bytes, headers: list[tuple[str, bytes]]
    ) -> asyncio.Future[object]: ...


class KafkaFactPublisher:
    def __init__(self, settings: KafkaSettings) -> None:
        self._settings = settings
        self._producer: _Producer | None = None

    def producer_options(self) -> dict[str, object]:
        return {
            "bootstrap_servers": self._settings.brokers,
            "client_id": self._settings.client_id,
            "enable_idempotence": True,
            "acks": "all",
        }

    async def start(self) -> None:
        producer: _Producer = AIOKafkaProducer(**self.producer_options())
        try:
            await producer.start()
        except BaseException:
            # A producer whose start() raised still holds its client; close it, then re-raise.
            with contextlib.suppress(Exception):
                await producer.stop()
            raise
        self._producer = producer

    async def stop(self) -> None:
        producer, self._producer = self._producer, None
        if producer is not None:
            await producer.stop()

    async def publish(self, facts: Sequence[PublishableFact]) -> None:
        producer = self._producer
        if producer is None:
            raise FactPublicationError(
                [fact.event_id for fact in facts], "the producer is not started"
            )
        sent: list[tuple[PublishableFact, asyncio.Future[object]]] = []
        failed: list[UUID] = []
        reason = ""
        for index, fact in enumerate(facts):
            try:
                future = await producer.send(
                    ORDERS_FACTS_TOPIC, value=fact.value, key=fact.key, headers=list(fact.headers)
                )
            except Exception as error:
                failed = [later.event_id for later in facts[index:]]
                reason = f"send failed: {error!r}"
                break
            sent.append((fact, future))
        results = await asyncio.gather(*(future for _, future in sent), return_exceptions=True)
        for (fact, _), result in zip(sent, results, strict=True):
            # A future that ends in an exception (CancelledError included: a producer stopped under
            # it) is a failed record. OUR cancellation is not in `results`: `gather` itself raises.
            if isinstance(result, BaseException):
                failed.append(fact.event_id)
                reason = reason or f"not acknowledged: {result!r}"
        if failed:
            raise FactPublicationError(failed, reason)
