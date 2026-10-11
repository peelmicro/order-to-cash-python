"""`KafkaFactSubscriber`: the ONLY module of this service that imports `AIOKafkaConsumer`.

A port of Orders' `kafka_fact_subscriber.py` (the first Kafka consumer of this repository), with
the three choices this consumer makes differently written below. The offset contract is the
load-bearing part, and it is aiokafka-specific:

* `enable_auto_commit=False` (aiokafka's default is `True`, `aiokafka/consumer/consumer.py:247`) and
  an explicit `commit({tp: offset + 1})` only AFTER the handler returned.
* A failed record is not skipped. aiokafka's fetch position is already past a record once it has
  been returned, so after a failure the next fetch would return the NEXT record of that partition,
  whose success would commit past the failed one. On failure: no commit, `seek(tp, record.offset)`,
  a paced back-off, continue. And `getmany(max_records=1)`, so no second record of the partition is
  in hand when the failure happens.
* One task, one record at a time, the handler awaited before the next poll: aiokafka heartbeats
  from a coroutine on the SAME loop, so nothing synchronous may run in a handler.

What differs from Orders' saga consumer, and why:

* `auto_offset_reset="latest"` (Orders: `earliest`). Notifications owns no aggregate; a fact the
  group never saw is an omission, not an inconsistency, and replaying a topic into a new group
  would e-mail the whole history (#7 round 2, #8 `AutoOffsetReset.Latest`). With `latest`, "the log
  end when the group is assigned" is the starting point, so the subscriber resolves the position of
  every assigned partition BEFORE it reports `ready`: a fact published after `ready` is read.
* `group_id` and `client_id` come from `KafkaSettings` (`notifications` / `otc-notifications`,
  both predecessors' values), distinct from every producer's client id.
* `ready` is the readiness signal the runtime serves: false until the group is joined and the
  positions are resolved, false again once `run` ends.

Until feature 27 a record whose handler keeps raising holds its partition and is retried forever,
paced 1 s doubling to a 30 s cap for consecutive failures of the same (partition, offset) and reset
by a success. Event-loop affinity: an `AIOKafkaConsumer` binds to the loop that creates it, so
nothing is built in `__init__`; `run` builds and starts it inside the running loop and stops it in
`finally`. The calls this module makes are typed through a private `Protocol` (aiokafka ships no
stubs); it returns only `FactMessage`, `None` or its own errors.
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Collection, Mapping, Sequence
from typing import Protocol

from aiokafka import AIOKafkaConsumer
from aiokafka.errors import CommitFailedError

from otc_notifications.application.ports.fact_stream import FactMessage
from otc_notifications.infrastructure.messaging.fact_topics import NOTIFICATION_FACT_TOPICS
from otc_notifications.infrastructure.settings import KafkaSettings

log = logging.getLogger("otc_notifications.messaging.kafka_fact_subscriber")

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
    def assignment(self) -> Collection[_TopicPartition]: ...
    async def position(self, partition: _TopicPartition) -> int: ...
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
        topics: Sequence[str] = NOTIFICATION_FACT_TOPICS,
        consumer_factory: ConsumerFactory = AIOKafkaConsumer,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        poll_ms: int = POLL_MS,
    ) -> None:
        self._settings = settings
        self._topics = tuple(topics)
        self._consumer_factory = consumer_factory
        self._sleep = sleep
        self._poll_ms = poll_ms
        self._ready = asyncio.Event()

    @property
    def ready(self) -> bool:
        """The group is joined and every assigned partition has a resolved position."""
        return self._ready.is_set()

    async def wait_ready(self) -> None:
        await self._ready.wait()

    def consumer_options(self) -> dict[str, object]:
        return {
            "bootstrap_servers": self._settings.brokers,
            "group_id": self._settings.group_id,
            "client_id": self._settings.client_id,
            "enable_auto_commit": False,
            "auto_offset_reset": "latest",
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
            # `start()` returns once the group has assigned partitions. With `latest`, a partition's
            # starting point is resolved lazily at the first fetch: resolve it now, so a fact
            # published after `ready` can never fall before the starting point.
            for partition in consumer.assignment():
                await consumer.position(partition)
            self._ready.set()
            await self._consume(consumer, handler, stop, pace)
        finally:
            self._ready.clear()
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
