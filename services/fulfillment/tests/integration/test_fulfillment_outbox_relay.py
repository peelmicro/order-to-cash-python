"""FS16 (C6): a reserve transaction's fact reaches `otc.fulfillment.facts.v1` through Fulfillment's
own outbox relay, keyed by `correlationId`, and is stamped only after the broker acknowledged it.

The relay is driven by hand (`run_once()`) so the order of events is the test's: the row exists
unpublished, the run publishes, the stamp follows. A real consumer reads the topic back. The Kafka
broker is shared by the session, so the records are found by this test's own correlation id.
"""

import asyncio
import json
import uuid
from typing import Any

from aiokafka import AIOKafkaConsumer, TopicPartition
from aiokafka.admin import AIOKafkaAdminClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from otc_fulfillment.infrastructure.clock import SystemClock
from otc_fulfillment.infrastructure.outbox.kafka_publisher import KafkaFactPublisher
from otc_fulfillment.infrastructure.outbox.relay import OutboxRelay
from otc_fulfillment.infrastructure.outbox.topic import FULFILLMENT_FACTS_TOPIC
from otc_fulfillment.infrastructure.settings import KafkaSettings

COMPANY = "ACME-CO"
ORDERS_TOPIC = "otc.orders.facts.v1"


async def partitions_of(bootstrap: str, topic: str) -> list[TopicPartition]:
    """The partitions the BROKER reports for the topic (its metadata, not a constant)."""
    admin = AIOKafkaAdminClient(bootstrap_servers=bootstrap)
    await admin.start()
    try:
        described: list[dict[str, Any]] = await admin.describe_topics([topic])
    finally:
        await admin.close()
    return [TopicPartition(topic, int(p["partition"])) for p in described[0]["partitions"]]


async def end_offsets(bootstrap: str, topic: str) -> dict[int, int]:
    consumer = AIOKafkaConsumer(
        bootstrap_servers=bootstrap, enable_auto_commit=False, auto_offset_reset="earliest"
    )
    await consumer.start()
    try:
        assigned = await partitions_of(bootstrap, topic)
        consumer.assign(assigned)
        offsets = await consumer.end_offsets(assigned)
        return {tp.partition: offset for tp, offset in offsets.items()}
    finally:
        await consumer.stop()


async def records_for(bootstrap: str, topic: str, correlation_id: str) -> list[Any]:
    """Every record of the topic whose key is `correlation_id`, read from the beginning."""
    consumer = AIOKafkaConsumer(
        bootstrap_servers=bootstrap, enable_auto_commit=False, auto_offset_reset="earliest"
    )
    await consumer.start()
    try:
        assigned = await partitions_of(bootstrap, topic)
        consumer.assign(assigned)
        await consumer.seek_to_beginning(*assigned)
        ends = await consumer.end_offsets(assigned)
        found: list[Any] = []
        async with asyncio.timeout(30):
            while True:
                behind = [tp for tp in assigned if await consumer.position(tp) < ends[tp]]
                if not behind:
                    break
                batch = await consumer.getmany(timeout_ms=500)
                found.extend(
                    r
                    for records in batch.values()
                    for r in records
                    if r.key == correlation_id.encode()
                )
        return found
    finally:
        await consumer.stop()


async def test_fs16_publishes_a_reserve_transactions_fact_to_the_fulfillment_topic_keyed_by_correlation_id_and_stamps_it_only_after_acknowledgement(  # noqa: E501
    fulfillment_host: Any, db: Any, rpc: Any, engine: AsyncEngine, kafka_server: Any
) -> None:
    ids = await db.seed_stock(COMPANY, [("PRD-A1", 10, 0, 3)])
    correlation = str(uuid.uuid4())  # the order id: NOT the aggregate id
    request = str(uuid.uuid4())
    await rpc(
        "fulfillment.stock.reserve",
        {
            "orderReference": "ORD-000042",
            "retailerCode": "RET-9",
            "companyCode": COMPANY,
            "lines": [{"productCode": "PRD-A1", "units": 3}],
        },
        headers={"x-correlation-id": correlation, "x-request-id": request},
    )
    [row] = await db.outbox()
    assert row["published_at"] is None, "the row exists and is not published yet"
    assert str(row["correlation_id"]) == correlation
    assert row["aggregate_id"] == ids["PRD-A1"]
    assert str(row["aggregate_id"]) != correlation, "the key must be told apart from the aggregate"
    orders_before = await end_offsets(kafka_server.bootstrap_servers, ORDERS_TOPIC)

    publisher = KafkaFactPublisher(
        KafkaSettings.model_validate(
            {
                "KAFKA_BROKERS": kafka_server.bootstrap_servers,
                "FULFILLMENT_KAFKA_CLIENT_ID": "otc-fulfillment-tests",
            }
        )
    )
    await publisher.start()
    try:
        relay = OutboxRelay(
            sessions=async_sessionmaker(engine, expire_on_commit=False),
            publisher=publisher,
            clock=SystemClock(),
            batch_size=100,
            publish_timeout=10,
        )
        result = await relay.run_once()
    finally:
        await publisher.stop()

    assert (result.claimed, result.published, result.poisoned) == (1, 1, None)
    [stamped] = await db.outbox()
    assert stamped["published_at"] is not None, "stamped by the run, after the acknowledgement"

    [record] = await records_for(
        kafka_server.bootstrap_servers, FULFILLMENT_FACTS_TOPIC, correlation
    )
    assert record.key == correlation.encode(), "keyed by correlationId, not the aggregate id"
    envelope = json.loads(record.value)
    assert list(envelope) == [
        "eventId",
        "eventType",
        "aggregateId",
        "correlationId",
        "causationId",
        "occurredAt",
        "payload",
    ]
    assert envelope["eventId"] == str(row["event_id"])
    assert envelope["eventType"] == "stock.reserved.v1"
    assert envelope["aggregateId"] == str(ids["PRD-A1"])
    assert envelope["correlationId"] == correlation
    assert envelope["causationId"] == request
    assert envelope["occurredAt"] == row["occurred_at"].strftime("%Y-%m-%dT%H:%M:%S.") + (
        f"{row['occurred_at'].microsecond // 1000:03d}Z"
    )
    assert envelope["payload"] == row["payload"]
    assert dict(record.headers)["x-event-type"] == b"stock.reserved.v1"

    orders_after = await end_offsets(kafka_server.bootstrap_servers, ORDERS_TOPIC)
    assert orders_after == orders_before, "nothing from this test reached the Orders topic"
