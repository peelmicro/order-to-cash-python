"""Fulfillment's COPY of Orders' `infrastructure/outbox/kafka_publisher.py` (the canonical).

The canonical: `services/orders/src/otc_orders/infrastructure/outbox/kafka_publisher.py`.
After this docstring the copy equals it, modulo the token map `otc_orders` ->
`otc_fulfillment` and `ORDERS_FACTS_TOPIC` -> `FULFILLMENT_FACTS_TOPIC`, and modulo the
formatter's line reflow of the longer names. Any other difference fails
`tests/architecture/test_outbox_copy_parity.py`. Change the canonical, never this copy.
"""

import asyncio
import contextlib
from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from aiokafka import AIOKafkaProducer

from otc_fulfillment.infrastructure.outbox.publisher import FactPublicationError, PublishableFact
from otc_fulfillment.infrastructure.outbox.topic import FULFILLMENT_FACTS_TOPIC
from otc_fulfillment.infrastructure.settings import KafkaSettings


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
                    FULFILLMENT_FACTS_TOPIC,
                    value=fact.value,
                    key=fact.key,
                    headers=list(fact.headers),
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
