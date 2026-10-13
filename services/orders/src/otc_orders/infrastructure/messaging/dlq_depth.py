"""`otc_dlq_depth`: how many records sit on each dead-letter topic (`R59`, `OR9`; `design.md` 6.2).

`KafkaDlqDepth` asks the BROKER: an admin client names each topic's partitions (one
`describe_topics` call for all of them) and a dedicated group-less `AIOKafkaConsumer`, which never
subscribes, never joins a group and never commits, reads the offsets: for each `<topic>.dlq` the
depth is the sum over its partitions of `end_offset - beginning_offset`. The admin client is needed
because the consumer's own metadata knows only topics it was told about (`partitions_for_topic` is
`None` for any other, and `topics()` returns a throw-away copy). A topic the broker does not have
(`UnknownTopicOrPartition`, error code 3, which is also what a topic created a moment ago answers
until the metadata reaches the broker asked) reports `0` and never raises (the companions are
created by `kafka-init`; a deployment without one has a missing topic, not a failure of the
others). Any other failure of a read raises to the task, which logs it
and leaves the gauge as it was: a depth that cannot be read is not reported as `0`.

`DlqDepthTask.run(stop)` is the self-scheduled loop of the relay's task (one `while`, an
interruptible sleep, no second task): it starts the reader INSIDE the lifespan's loop (an aiokafka
client binds to the loop that creates it), sets one SYNCHRONOUS `Gauge.set(depth, {"topic": ...})`
per topic from this task (ledger L12: an observable callback would run on the metric reader's
thread, where aiokafka objects must not be touched), and stops the reader when it ends. A reader
that cannot start ends the task with the error, so readiness goes down with it (CLAUDE.md "a task
that dies takes readiness down").
"""

import asyncio
import contextlib
import logging
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any, Protocol

from aiokafka import AIOKafkaConsumer, TopicPartition
from aiokafka.admin import AIOKafkaAdminClient

from otc_orders.infrastructure.observability.metrics import Gauge
from otc_orders.infrastructure.settings import KafkaSettings

log = logging.getLogger("otc_orders.messaging.dlq_depth")

DLQ_DEPTH_CLIENT_ID = "otc-orders-dlq-depth"
DEAD_LETTER_SUFFIX = ".dlq"


class _Consumer(Protocol):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def beginning_offsets(
        self, partitions: Iterable[TopicPartition]
    ) -> Mapping[TopicPartition, int]: ...
    async def end_offsets(
        self, partitions: Iterable[TopicPartition]
    ) -> Mapping[TopicPartition, int]: ...


class _Admin(Protocol):
    async def start(self) -> None: ...
    async def close(self) -> None: ...
    async def describe_topics(self, topics: list[str]) -> list[dict[str, Any]]: ...


type ConsumerFactory = Callable[..., _Consumer]
type AdminFactory = Callable[..., _Admin]

UNKNOWN_TOPIC_OR_PARTITION = 3  # the Kafka protocol's error code


class DlqDepths(Protocol):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def depths(self) -> dict[str, int]: ...


class KafkaDlqDepth:
    def __init__(
        self,
        settings: KafkaSettings,
        topics: Sequence[str],
        *,
        client_id: str = DLQ_DEPTH_CLIENT_ID,
        consumer_factory: ConsumerFactory | None = None,
        admin_factory: AdminFactory | None = None,
    ) -> None:
        self._settings = settings
        self._topics = tuple(topics)
        self._client_id = client_id
        self._consumer_factory: ConsumerFactory = (
            AIOKafkaConsumer if consumer_factory is None else consumer_factory
        )
        self._admin_factory: AdminFactory = (
            AIOKafkaAdminClient if admin_factory is None else admin_factory
        )
        self._consumer: _Consumer | None = None
        self._admin: _Admin | None = None

    def consumer_options(self) -> dict[str, object]:
        return {
            "bootstrap_servers": self._settings.brokers,
            "client_id": self._client_id,
            "group_id": None,
            "enable_auto_commit": False,
        }

    def admin_options(self) -> dict[str, object]:
        return {
            "bootstrap_servers": self._settings.brokers,
            "client_id": f"{self._client_id}-admin",
        }

    async def start(self) -> None:
        consumer = self._consumer_factory(**self.consumer_options())
        admin = self._admin_factory(**self.admin_options())
        try:
            await consumer.start()
            self._consumer = consumer
            await admin.start()
            self._admin = admin
        except BaseException:
            await self.stop()
            with contextlib.suppress(Exception):
                await consumer.stop()
            with contextlib.suppress(Exception):
                await admin.close()
            raise

    async def stop(self) -> None:
        consumer, self._consumer = self._consumer, None
        admin, self._admin = self._admin, None
        try:
            if consumer is not None:
                await consumer.stop()
        finally:
            if admin is not None:
                await admin.close()

    async def depths(self) -> dict[str, int]:
        """The depth of every configured topic, read from the broker; `0` for a missing topic."""
        consumer, admin = self._consumer, self._admin
        if consumer is None or admin is None:
            raise RuntimeError("the dead-letter depth reader is not started")
        described = {
            str(item["topic"]): item for item in await admin.describe_topics(list(self._topics))
        }
        depths: dict[str, int] = {}
        for topic in self._topics:
            item = described.get(topic)
            code = None if item is None else item["error_code"]
            if item is None or code == UNKNOWN_TOPIC_OR_PARTITION:
                depths[topic] = 0
                continue
            if code != 0:
                raise RuntimeError(f"describing {topic} failed with Kafka error code {code}")
            assigned = [
                TopicPartition(topic, int(partition["partition"]))
                for partition in sorted(item["partitions"], key=lambda p: p["partition"])
            ]
            beginning = await consumer.beginning_offsets(assigned)
            end = await consumer.end_offsets(assigned)
            depths[topic] = sum(end[tp] - beginning[tp] for tp in assigned)
        return depths


class DlqDepthTask:
    def __init__(
        self,
        reader: DlqDepths,
        gauge: Gauge,
        *,
        poll_interval: float,
        enabled: bool,
    ) -> None:
        self._reader = reader
        self._gauge = gauge
        self._poll_interval = poll_interval
        self._enabled = enabled

    async def run(self, stop: asyncio.Event) -> None:
        if not self._enabled:
            return
        await self._reader.start()
        try:
            while not stop.is_set():
                try:
                    for topic, depth in (await self._reader.depths()).items():
                        self._gauge.set(depth, {"topic": topic})
                except Exception:
                    log.exception("dead-letter depth cycle failed; next cycle after the interval")
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=self._poll_interval)
        finally:
            await self._reader.stop()
