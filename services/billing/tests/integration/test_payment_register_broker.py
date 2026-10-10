"""R47 read back from the BROKER: `payment.received.v1` then `credit.released.v1` reach
`otc.billing.facts.v1` in that order, on the same partition, both keyed by the order id (the
envelope's `correlationId`), the release's `causationId` the payment's `eventId` (#8 id 57).

The relay runs inside the host the test starts (`OUTBOX_RELAY_ENABLED=true`, the Docker-held
Kafka). The broker is shared by the session, so the records are found by this test's own order id
(never the first on the topic: #8 id 74). A real consumer reads the topic from the beginning.

Loop scope: function. The host, the caller and the consumers are created and closed in the loop of
the test.
"""

import asyncio
import json
import uuid
from typing import Any

from aiokafka import AIOKafkaConsumer, TopicPartition
from aiokafka.admin import AIOKafkaAdminClient

from otc_billing.infrastructure.outbox.topic import BILLING_FACTS_TOPIC

VALUE_DATE = "2026-10-09T13:45:10.123Z"


async def partitions_of(bootstrap: str, topic: str) -> list[TopicPartition]:
    admin = AIOKafkaAdminClient(bootstrap_servers=bootstrap)
    await admin.start()
    try:
        described: list[dict[str, Any]] = await admin.describe_topics([topic])
    finally:
        await admin.close()
    return [TopicPartition(topic, int(p["partition"])) for p in described[0]["partitions"]]


async def records_for(bootstrap: str, correlation_id: str, *, want: int) -> list[Any]:
    """Every record whose ENVELOPE carries `correlationId`, polled (bounded) until `want` of them
    were read: the relay publishes asynchronously, so absence is not yet a verdict."""
    consumer = AIOKafkaConsumer(
        bootstrap_servers=bootstrap, enable_auto_commit=False, auto_offset_reset="earliest"
    )
    await consumer.start()
    try:
        assigned = await partitions_of(bootstrap, BILLING_FACTS_TOPIC)
        consumer.assign(assigned)
        await consumer.seek_to_beginning(*assigned)
        found: list[Any] = []
        async with asyncio.timeout(60):
            while len(found) < want:
                batch = await consumer.getmany(timeout_ms=500)
                found.extend(
                    r
                    for records in batch.values()
                    for r in records
                    if json.loads(r.value)["correlationId"] == correlation_id
                )
        # a short settle read: more than `want` records for the order would be a duplicate fact
        batch = await consumer.getmany(timeout_ms=1000)
        found.extend(
            r
            for records in batch.values()
            for r in records
            if json.loads(r.value)["correlationId"] == correlation_id
        )
        return found
    finally:
        await consumer.stop()


async def test_r47_the_payment_fact_then_the_release_fact_reach_the_broker_in_order_keyed_by_the_order_id(  # noqa: E501
    billing_host_factory: Any, db: Any, rpc: Any, decode: Any, make_world: Any, kafka_server: Any
) -> None:
    async with billing_host_factory(OUTBOX_RELAY_ENABLED="true"):
        world = await make_world()
        request = str(uuid.uuid4())

        reply = await rpc(
            "billing.payment.register",
            {
                "invoiceId": str(world.invoice_id),
                "paymentReference": "BANK-REF-7731",
                "amount": {"amount": world.total, "currency": "EUR"},
                "valueDate": VALUE_DATE,
                "source": "robot",
            },
            headers={"x-correlation-id": world.correlation, "x-request-id": request},
        )
        assert decode.payment_register(reply).outcome.value == "accepted"

        # the order's facts: invoice.issued.v1 and credit.approved.v1 (the world's own), then the
        # two of the payment. Selected by VALUE, so a record under a wrong key is still found
        records = await records_for(kafka_server.bootstrap_servers, world.correlation, want=4)

    envelopes = [json.loads(r.value) for r in records]
    types = [e["eventType"] for e in envelopes]
    assert types == [
        "credit.approved.v1",
        "invoice.issued.v1",
        "payment.received.v1",
        "credit.released.v1",
    ], f"R47: the broker delivered {types} for the order"
    (received_record, received), (released_record, released) = list(
        zip(records, envelopes, strict=True)
    )[2:]
    assert received_record.key == released_record.key == world.correlation.encode(), (
        "R47: the facts are not keyed by the order id"
    )
    assert received_record.partition == released_record.partition, "R47: two partitions"
    assert received_record.offset < released_record.offset, (
        "R47: payment.received.v1 does not precede credit.released.v1 on the partition"
    )
    assert released["causationId"] == received["eventId"], (
        "#8 id 57: the broker's credit.released.v1 is not caused by payment.received.v1"
    )
    assert received["causationId"] == request
    assert received["aggregateId"] == str(world.invoice_id)
    assert released["aggregateId"] == str(world.line_id)
    assert received["occurredAt"] == released["occurredAt"]
    assert received["payload"]["valueDate"] == VALUE_DATE
    assert released["payload"]["availableCreditAfter"] == world.available_after
