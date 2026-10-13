"""`KafkaFactSubscriber`: the ONLY module that imports `AIOKafkaConsumer`.

Design: `design.md` 5.1 - 5.3; SO9.

The offset contract is the load-bearing part, and it is aiokafka-specific:

* `enable_auto_commit=False` (aiokafka's default is `True`, `aiokafka/consumer/consumer.py:247`) and
  an explicit `commit({tp: offset + 1})` only AFTER the handler returned (L1).
* A failed record is not skipped (L2). aiokafka's fetch position is already past a record once it
  has been returned, so after a failure the next fetch would return the NEXT record of that
  partition, whose success would commit past the failed one. On failure: no commit, `seek(tp,
  record.offset)` (`consumer.py:755`), a paced back-off, continue. And `getmany(max_records=1)`, so
  no second record of the partition is in hand when the failure happens.
* One task, one record at a time, the handler awaited before the next poll (L3, L29): aiokafka
  heartbeats from a coroutine on the SAME loop (`session_timeout_ms=10000`,
  `max_poll_interval_ms=300000`, `consumer.py:252-254`), so nothing synchronous may run in a
  handler.
* `auto_offset_reset="earliest"` (default `"latest"`, `consumer.py:246`): a first boot reads the
  facts published before the group existed (SO1, L5).
* `group_id` is `orders.saga` verbatim and `client_id` is `otc-orders-saga` (both predecessors'
  value), distinct from the relay's `otc-orders` (L4).

Budget (5.2): a record's time on this path is one database transaction (the RPC runs in other
tasks), so `max_poll_interval_ms` (300 000, the binding constraint, the same as #8's librdkafka) is
never approached; the numbers 5 000 ms x 3 x 500 ms stay #7's and #8's (`command_dispatcher.py`).

Event-loop affinity (L28): an `AIOKafkaConsumer` binds to the loop that creates it, so nothing is
built in `__init__`; `run` builds and starts it inside the running loop and stops it in `finally`.
The calls this module makes are typed through a private `Protocol` (aiokafka ships no stubs); it
returns only `FactMessage`, `None` or its own errors.

Since `R16` the handler the consumer task passes in retries a processing failure itself and
dead-letters it (`FactRetry`, `R16`), so it raises HERE only when the dead-letter publication itself
fails (`OR8`) or on cancellation. Such a record still holds its partition and is delivered again,
paced 1 s doubling to a 30 s cap for consecutive failures of the same (partition, offset) and reset
by a success (#7's kafkajs crash-loop on the offset, #8's re-entry after 2 s).
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Protocol

from aiokafka import AIOKafkaConsumer
from aiokafka.errors import CommitFailedError
from opentelemetry.trace import SpanKind, Tracer

from otc_orders.application.ports.fact_stream import FactMessage
from otc_orders.infrastructure.messaging.consumer_name import ConsumerName
from otc_orders.infrastructure.messaging.fact_retry import FactRetryStopped
from otc_orders.infrastructure.messaging.fact_topics import SAGA_FACT_TOPICS
from otc_orders.infrastructure.observability.trace_context import NO_TRACER, extract_kafka
from otc_orders.infrastructure.settings import CONSUMER_MAX_POLL_INTERVAL_MS, KafkaSettings

log = logging.getLogger("otc_orders.messaging.kafka_fact_subscriber")

CLIENT_ID = "otc-orders-saga"
POLL_MS = 500
RETRY_BASE_SECONDS = 1.0
RETRY_CAP_SECONDS = 30.0

type _TopicPartition = tuple[str, int]  # aiokafka's `TopicPartition` is a namedtuple of these


class _Record(Protocol):
    @property
    def topic(self) -> str: ...
    @property
    def partition(self) -> int: ...
    @property
    def offset(self) -> int: ...
    @property
    def key(self) -> bytes | None: ...
    @property
    def value(self) -> bytes | None: ...
    @property
    def headers(self) -> Sequence[tuple[str, bytes]]: ...


class _Consumer(Protocol):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def getmany(
        self, *, timeout_ms: int, max_records: int
    ) -> Mapping[_TopicPartition, Sequence[_Record]]: ...
    def seek(self, partition: _TopicPartition, offset: int) -> None: ...
    async def commit(self, offsets: Mapping[_TopicPartition, int]) -> None: ...


type ConsumerFactory = Callable[..., _Consumer]


def retry_delay_seconds(consecutive_failures: int) -> float:
    """1 s doubling per consecutive failure of the same offset, capped at 30 s."""
    doublings = min(consecutive_failures - 1, 5)  # 2 ** 5 s already exceeds the cap
    return min(RETRY_BASE_SECONDS * (1 << doublings), RETRY_CAP_SECONDS)


class KafkaFactSubscriber:
    def __init__(
        self,
        settings: KafkaSettings,
        *,
        topics: Sequence[str] = SAGA_FACT_TOPICS,
        consumer_factory: ConsumerFactory = AIOKafkaConsumer,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        poll_ms: int = POLL_MS,
        tracer: Tracer = NO_TRACER,
    ) -> None:
        self._tracer = tracer
        self._settings = settings
        self._topics = tuple(topics)
        self._consumer_factory = consumer_factory
        self._sleep = sleep
        self._poll_ms = poll_ms

    def consumer_options(self) -> dict[str, object]:
        return {
            "bootstrap_servers": self._settings.brokers,
            "group_id": ConsumerName.ORDERS_SAGA.value,
            "client_id": CLIENT_ID,
            "enable_auto_commit": False,
            "max_poll_interval_ms": CONSUMER_MAX_POLL_INTERVAL_MS,
            "auto_offset_reset": "earliest",
        }

    async def run(
        self, handler: Callable[[FactMessage], Awaitable[None]], stop: asyncio.Event
    ) -> None:
        async def pace(seconds: float) -> None:
            if self._sleep is not None:
                await self._sleep(seconds)
                return
            # Interruptible: a poisoned record's back-off must not hold a shutdown for 30 s.
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=seconds)

        consumer = self._consumer_factory(*self._topics, **self.consumer_options())
        try:
            await consumer.start()
            await self._consume(consumer, handler, stop, pace)
        finally:
            await consumer.stop()

    async def _consume(
        self,
        consumer: _Consumer,
        handler: Callable[[FactMessage], Awaitable[None]],
        stop: asyncio.Event,
        pace: Callable[[float], Awaitable[None]],
    ) -> None:
        failures: dict[_TopicPartition, int] = {}  # consecutive failures of the partition head
        while not stop.is_set():
            batch = await consumer.getmany(timeout_ms=self._poll_ms, max_records=1)
            for partition, records in batch.items():
                record = records[0]
                try:
                    with self._tracer.start_as_current_span(
                        f"{record.topic} process",
                        context=extract_kafka(record.headers),
                        kind=SpanKind.CONSUMER,
                        attributes={
                            "messaging.system": "kafka",
                            "messaging.destination.name": record.topic,
                            "messaging.kafka.partition": record.partition,
                            "messaging.kafka.offset": record.offset,
                        },
                    ):
                        await handler(
                            FactMessage(
                                topic=record.topic,
                                partition=record.partition,
                                offset=record.offset,
                                key=record.key,
                                value=record.value if record.value is not None else b"",
                                headers=tuple(record.headers),
                            )
                        )
                except FactRetryStopped:
                    # A shutdown ended the retry back-off (`stop_aware_sleep`): not a handler
                    # failure, so no failure line, no count and no seek. Nothing was committed, the
                    # loop ends with the stop signal, and the record is redelivered after the
                    # restart for a fresh round of attempts.
                    log.info(
                        "fact retry interrupted by shutdown; the offset is not committed and the "
                        "record will be delivered after the restart",
                        extra={
                            "topic": record.topic,
                            "partition": record.partition,
                            "offset": record.offset,
                        },
                    )
                    continue
                except Exception:
                    log.exception(
                        "fact handler failed; the offset is not committed and the record will be "
                        "delivered again",
                        extra={
                            "topic": record.topic,
                            "partition": record.partition,
                            "offset": record.offset,
                        },
                    )
                    # The failed record is sought back and retried before any later record of its
                    # partition, so consecutive failures of a partition are of ONE offset.
                    count = failures.get(partition, 0) + 1
                    failures[partition] = count
                    consumer.seek(partition, record.offset)
                    await pace(retry_delay_seconds(count))
                    continue
                failures.pop(partition, None)
                try:
                    await consumer.commit({partition: record.offset + 1})
                except CommitFailedError:
                    # A rebalance revoked the partition: the next owner redelivers the record and
                    # the dedup layer absorbs it. Neither a seek nor a stop is right here.
                    log.warning(
                        "offset commit failed after a rebalance; the record will be redelivered",
                        extra={
                            "topic": record.topic,
                            "partition": record.partition,
                            "offset": record.offset,
                        },
                    )
