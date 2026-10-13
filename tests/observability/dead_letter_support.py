"""Private topics and their dead-letter companions, shared by the reliability tests of feature 27.

Not a test module. Loaded BY PATH (the suite runs in importlib mode, so a sibling module is not
importable by name), the way `trace_support.py` is. It imports nothing from a service.

Item 10 (`design.md` 5.1): the session broker is ONE broker for the whole pytest session and every
service's tests publish to the real fact topics, whose names are constants of the services. A
consumer that starts at `earliest` on those topics replays whatever ANY earlier test produced, and
a poison fact a dead-letter test publishes there would be met by every later consumer. So a
dead-letter test runs on THREE private source topics (one per producing service, like the real
ones) and THREE private `<topic>.dlq` companions, all created here under a unique suffix. The
dead-letter publisher derives the companion from the record's own topic, so no configuration names
the `.dlq`.
"""

import asyncio
import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, TopicPartition
from aiokafka.admin import AIOKafkaAdminClient, NewTopic

PARTITIONS = 3


@dataclass(frozen=True)
class PrivateTopics:
    """THREE private source topics, one per producing service, in place of the three real ones."""

    orders: str
    fulfillment: str
    billing: str

    @property
    def all(self) -> tuple[str, str, str]:
        return (self.orders, self.fulfillment, self.billing)

    @property
    def dead_letters(self) -> tuple[str, str, str]:
        return (f"{self.orders}.dlq", f"{self.fulfillment}.dlq", f"{self.billing}.dlq")

    def for_event(self, event_type: str) -> str:
        """The topic a fact is published on: one per producing service (`asyncapi.yaml`)."""
        if event_type.startswith("stock.") or event_type == "order.despatched.v1":
            return self.fulfillment
        if event_type.startswith(("credit.", "invoice.", "payment.")):
            return self.billing
        return self.orders

    def dead_letter_of(self, topic: str) -> str:
        assert topic in self.all, f"{topic} is not one of this test's private topics"
        return f"{topic}.dlq"


async def create_private_topics(bootstrap_servers: str, prefix: str) -> PrivateTopics:
    """Create the six topics (three sources, three companions) under a name unique to the call."""
    suffix = uuid.uuid4().hex[:10]
    topics = PrivateTopics(
        orders=f"otc-{prefix}-{suffix}-orders-facts",
        fulfillment=f"otc-{prefix}-{suffix}-fulfillment-facts",
        billing=f"otc-{prefix}-{suffix}-billing-facts",
    )
    admin = AIOKafkaAdminClient(bootstrap_servers=bootstrap_servers)
    await admin.start()
    try:
        await admin.create_topics(
            [
                NewTopic(name=name, num_partitions=PARTITIONS, replication_factor=1)
                for name in (*topics.all, *topics.dead_letters)
            ]
        )
    finally:
        await admin.close()
    return topics


@dataclass(frozen=True)
class Recorded:
    """One record as the BROKER holds it (never inferred from a stamped row)."""

    partition: int
    offset: int
    key: bytes | None
    value: bytes
    headers: dict[str, bytes]

    @property
    def event_id(self) -> str | None:
        try:
            parsed = json.loads(self.value)
            return str(parsed["eventId"])
        except ValueError, KeyError, TypeError:
            return None


async def partitions_of(bootstrap_servers: str, topic: str) -> list[int]:
    admin = AIOKafkaAdminClient(bootstrap_servers=bootstrap_servers)
    await admin.start()
    try:
        described: list[dict[str, Any]] = await admin.describe_topics([topic])
    finally:
        await admin.close()
    return sorted(int(partition["partition"]) for partition in described[0]["partitions"])


async def read_records(
    bootstrap_servers: str, topic: str, *, seconds: float = 30
) -> list[Recorded]:
    """Every record on `topic` up to its end offsets as they are when the call starts. Explicit
    partition assignment, no consumer group, so it joins nothing and commits nothing. A test SELECTS
    its own records by content: a decoy published first must not be returned as the answer."""
    consumer = AIOKafkaConsumer(
        bootstrap_servers=bootstrap_servers,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
        client_id="otc-tests-reader",
    )
    await consumer.start()
    found: list[Recorded] = []
    try:
        assigned = [
            TopicPartition(topic, partition)
            for partition in await partitions_of(bootstrap_servers, topic)
        ]
        consumer.assign(assigned)
        await consumer.seek_to_beginning(*assigned)
        ends: dict[Any, int] = await consumer.end_offsets(assigned)
        deadline = asyncio.get_running_loop().time() + seconds
        while any([await consumer.position(tp) < ends[tp] for tp in assigned]):
            if asyncio.get_running_loop().time() > deadline:
                raise TimeoutError(f"{topic} could not be read to its end offsets")
            for tp, records in (await consumer.getmany(timeout_ms=500)).items():
                for record in records:
                    found.append(
                        Recorded(
                            partition=tp.partition,
                            offset=record.offset,
                            key=record.key,
                            value=record.value,
                            headers={name: bytes(raw) for name, raw in record.headers},
                        )
                    )
    finally:
        # aiokafka 0.14.0 (measured): `stop()` can raise CancelledError from a coordinator task that
        # has not taken its first step; one loop tick lets it start.
        await asyncio.sleep(0.05)
        await consumer.stop()
    return found


async def committed_offsets_of(
    bootstrap_servers: str, group: str, topics: Sequence[str]
) -> dict[tuple[str, int], int]:
    """The group's committed offsets for `topics` as THE BROKER reports them."""
    admin = AIOKafkaAdminClient(bootstrap_servers=bootstrap_servers)
    await admin.start()
    try:
        offsets: dict[Any, Any] = await admin.list_consumer_group_offsets(group)
        return {
            (tp.topic, tp.partition): int(meta.offset)
            for tp, meta in offsets.items()
            if tp.topic in topics
        }
    finally:
        await admin.close()


async def produce(
    bootstrap_servers: str,
    topic: str,
    *,
    key: bytes | None,
    value: bytes,
    headers: Sequence[tuple[str, bytes]] = (),
) -> tuple[int, int]:
    """Publish one record exactly as given; answer its (partition, offset)."""
    producer = AIOKafkaProducer(bootstrap_servers=bootstrap_servers, client_id="otc-tests-producer")
    await producer.start()
    try:
        sent = await producer.send_and_wait(topic, key=key, value=value, headers=list(headers))
        return int(sent.partition), int(sent.offset)
    finally:
        await producer.stop()
