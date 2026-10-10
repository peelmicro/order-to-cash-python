"""BC16 (F5): a hold transaction's fact reaches `otc.billing.facts.v1` through Billing's own outbox
relay, keyed by `correlationId`, and is stamped only after the broker acknowledged it.

The relay is driven by hand (`run_once()`) so the order of events is the test's: the row exists
unpublished, the run publishes, the stamp follows. A real consumer reads the topic back. The Kafka
broker is shared by the session, so the record is found by this test's own correlation id (never
the first on the topic: #8 id 74).

Loop scope: function. The producer, the consumers and the engine are created and closed in the loop
of the test.
"""

import asyncio
import json
import uuid
from typing import Any

from aiokafka import AIOKafkaConsumer, TopicPartition
from aiokafka.admin import AIOKafkaAdminClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from otc_billing.infrastructure.clock import SystemClock
from otc_billing.infrastructure.outbox.kafka_publisher import KafkaFactPublisher
from otc_billing.infrastructure.outbox.relay import OutboxRelay
from otc_billing.infrastructure.outbox.topic import BILLING_FACTS_TOPIC
from otc_billing.infrastructure.settings import KafkaSettings

RETAILER = "RETAIL-77"
COMPANY = "SUPPLY-CO"
CODE = "CR-000321"
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
    """Every record of the topic whose ENVELOPE carries `correlationId` (selected by value, so a
    record under a wrong key is still found and the key assertion is what fails), from the start."""
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
                    if json.loads(r.value)["correlationId"] == correlation_id
                )
        return found
    finally:
        await consumer.stop()


async def test_bc16_publishes_the_hold_facts_to_the_billing_topic_keyed_by_correlation_id_and_stamps_published_at_after_the_ack(  # noqa: E501
    billing_host: Any, db: Any, rpc: Any, decode: Any, engine: AsyncEngine, kafka_server: Any
) -> None:
    line_id = await db.seed_line(RETAILER, COMPANY, limit=100_000, code=CODE)
    correlation = str(uuid.uuid4())  # the order id: NOT the aggregate id
    request = str(uuid.uuid4())
    reply = await rpc(
        "billing.credit.hold",
        {
            "orderReference": "ORD-000101",
            "retailerCode": RETAILER,
            "companyCode": COMPANY,
            "amount": {"amount": 4210, "currency": "EUR"},
        },
        headers={"x-correlation-id": correlation, "x-request-id": request},
    )
    assert decode.hold(reply).outcome.value == "approved"
    [row] = await db.outbox()
    assert row["published_at"] is None, "the row exists and is not published yet"
    assert str(row["correlation_id"]) == correlation
    assert row["aggregate_id"] == line_id
    assert str(row["aggregate_id"]) != correlation, "the key must be told apart from the aggregate"
    orders_before = await end_offsets(kafka_server.bootstrap_servers, ORDERS_TOPIC)

    publisher = KafkaFactPublisher(
        KafkaSettings.model_validate(
            {
                "KAFKA_BROKERS": kafka_server.bootstrap_servers,
                "BILLING_KAFKA_CLIENT_ID": "otc-billing-tests",
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

    records = await records_for(kafka_server.bootstrap_servers, BILLING_FACTS_TOPIC, correlation)
    assert len(records) == 1, f"expected exactly one record for correlation id, got {len(records)}"
    [record] = records
    assert record.key == correlation.encode(), (
        f"BC16: keyed by {record.key!r}, not by the correlationId (the order id)"
    )
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
    assert envelope["eventType"] == "credit.approved.v1"
    assert envelope["aggregateId"] == str(line_id)
    assert envelope["correlationId"] == correlation
    assert envelope["causationId"] == request
    assert envelope["occurredAt"] == row["occurred_at"].strftime("%Y-%m-%dT%H:%M:%S.") + (
        f"{row['occurred_at'].microsecond // 1000:03d}Z"
    )
    assert envelope["payload"] == row["payload"]
    assert envelope["payload"]["heldAmount"] == 4210
    assert dict(record.headers)["x-event-type"] == b"credit.approved.v1"

    orders_after = await end_offsets(kafka_server.bootstrap_servers, ORDERS_TOPIC)
    assert orders_after == orders_before, "nothing from this test reached the Orders topic"


async def test_f5_publishes_invoice_issued_to_the_billing_topic_keyed_by_the_order_id_read_from_the_broker(  # noqa: E501
    billing_host: Any,
    db: Any,
    rpc: Any,
    decode: Any,
    engine: AsyncEngine,
    kafka_server: Any,
    issue_body: Any,
) -> None:
    """Task F5: an `invoice.issued.v1` reaches `otc.billing.facts.v1` keyed by the ORDER id (the
    envelope's `correlationId`), not by the invoice id (its `aggregateId`). The relay is driven by
    hand; a real consumer reads the key back from the broker; the record is selected by this test's
    own correlation id, never the first on the topic."""
    await db.seed_line(RETAILER, COMPANY, limit=250_000, code=CODE)
    order_id = str(uuid.uuid4())  # the order id: NOT the invoice id
    request = str(uuid.uuid4())
    built = issue_body(
        [("PRD-ZZ", 3, 1999), ("PRD-AA", 2, 1234)],
        350,
        order_reference="ORD-000101",
        retailer_code=RETAILER,
        company_code=COMPANY,
    )
    held = await rpc(
        "billing.credit.hold",
        {
            "orderReference": "ORD-000101",
            "retailerCode": RETAILER,
            "companyCode": COMPANY,
            "amount": {"amount": built.total, "currency": "EUR"},
        },
        headers={"x-correlation-id": str(uuid.uuid4()), "x-request-id": str(uuid.uuid4())},
    )
    assert decode.hold(held).outcome.value == "approved"
    # drain the hold's fact first, so the run under test claims exactly the invoice's
    publisher = KafkaFactPublisher(
        KafkaSettings.model_validate(
            {
                "KAFKA_BROKERS": kafka_server.bootstrap_servers,
                "BILLING_KAFKA_CLIENT_ID": "otc-billing-tests",
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
        assert (await relay.run_once()).published == 1  # the credit.approved.v1 of the hold
        reply = await rpc(
            "billing.invoice.issue",
            built.body,
            headers={"x-correlation-id": order_id, "x-request-id": request},
        )
        issued = decode.invoice_issue(reply)
        assert issued.created is True
        [row] = [r for r in await db.outbox() if r["event_type"] == "invoice.issued.v1"]
        assert row["published_at"] is None, "the row exists and is not published yet"
        assert str(row["correlation_id"]) == order_id
        assert row["aggregate_id"] == issued.invoice_id
        assert str(row["aggregate_id"]) != order_id, "the key must be told apart from the aggregate"
        result = await relay.run_once()
    finally:
        await publisher.stop()

    assert (result.claimed, result.published, result.poisoned) == (1, 1, None)
    records = await records_for(kafka_server.bootstrap_servers, BILLING_FACTS_TOPIC, order_id)
    invoice_records = [
        r for r in records if json.loads(r.value)["eventType"] == "invoice.issued.v1"
    ]
    assert len(invoice_records) == 1, (
        f"expected exactly one invoice.issued.v1 for correlation id, got {len(invoice_records)}"
    )
    [record] = invoice_records
    assert record.key == order_id.encode(), (
        f"F5: keyed by {record.key!r}, not by the order id (correlationId) {order_id}"
    )
    envelope = json.loads(record.value)
    assert envelope["aggregateId"] == str(issued.invoice_id)
    assert envelope["correlationId"] == order_id
    assert envelope["causationId"] == request
    assert envelope["payload"] == row["payload"]
    assert envelope["payload"]["totalAmount"] == 8115
    assert dict(record.headers)["x-event-type"] == b"invoice.issued.v1"
