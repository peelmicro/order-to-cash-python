"""`OR12` (gate G1, S4.15): an operator cancel's release that is PARKED.

#7 and #8 stored a synthetic `orders.cancel.requested` envelope for this row and dead-lettered it;
that is a record no producer ever wrote. Here the first park appends `order.saga_failed.v1` and
publishes NO dead letter: #8's `OrdersCancelAcceptanceTests.cs:549` scenario with its claim
inverted. The absence is read from the BROKER by content, on the test's private `.dlq` companions
AND on the real `otc.orders.facts.v1.dlq` (where a synthetic envelope naming the real topic would
land), after a decoy dead letter for another order was published first on the private companion.
"""

import json
import re
import uuid
from collections.abc import Awaitable, Callable
from types import ModuleType
from typing import Any

import pytest

from otc_orders.application.saga.command_kind import SagaCommandKind
from otc_orders.domain.order import Order
from otc_orders.domain.value_objects.order_status import OrderStatus
from otc_orders.infrastructure.saga.first_park import SqlAlchemySagaFirstPark

Waits = Callable[..., Awaitable[None]]
OrderAt = Callable[..., Awaitable[Order]]

REAL_ORDERS_DLQ = "otc.orders.facts.v1.dlq"
TRACEPARENT = r"^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$"


async def test_or12_a_parked_operator_release_appends_one_saga_failed_and_publishes_no_dead_letter(
    saga_harness: Any,
    private_topics: Any,
    dl_support: ModuleType,
    kafka_server: Any,
    order_at: OrderAt,
    make_fact_bytes: Callable[..., bytes],
    nats_client: Any,
    waits: Waits,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completions: list[uuid.UUID] = []
    original = SqlAlchemySagaFirstPark.on_parked

    async def counted(self: SqlAlchemySagaFirstPark, row: Any, **kwargs: Any) -> None:
        await original(self, row, **kwargs)
        completions.append(row.id)

    monkeypatch.setattr(SqlAlchemySagaFirstPark, "on_parked", counted)
    order = await order_at(OrderStatus.STOCK_RESERVED)
    servers = kafka_server.bootstrap_servers
    private_letters = private_topics.dead_letter_of(private_topics.orders)
    decoy_order = uuid.uuid4()
    decoy_id = uuid.uuid4()
    await dl_support.produce(
        servers,
        private_letters,
        key=str(decoy_order).encode(),
        value=make_fact_bytes(
            "order.placed.v1",
            correlation_id=decoy_order,
            reference="ORD-000998",
            event_id=decoy_id,
        ),
    )

    async with saga_harness(
        topics=private_topics,
        SAGA_SWEEPER_ENABLED="false",
        OUTBOX_RELAY_ENABLED="false",
    ) as saga:
        saga.stand_in(SagaCommandKind.STOCK_RELEASE).behaviour = saga.behaviours["silent"]
        reply = await nats_client.request(
            "orders.cancel",
            json.dumps({"orderId": str(order.id.value), "reason": "operator_cancelled"}).encode(),
            timeout=10,
            headers={
                "x-correlation-id": str(order.id.value),
                "x-request-id": str(uuid.uuid4()),
            },
        )
        assert json.loads(reply.data)["status"] == "stock_reserved", "accepted, completed later"

        async def hook_finished() -> bool:
            row = await saga.db.command_row(order.id, SagaCommandKind.STOCK_RELEASE)
            return row is not None and row["status"] == "parked" and row["id"] in completions

        await waits(hook_finished, "the operator's stock.release is parked and its hook returned")

        # Absence, read from the broker by content: the decoy proves the topic is being read, and
        # no record anywhere names this order.
        readable = [*private_topics.dead_letters, REAL_ORDERS_DLQ]
        seen: dict[str, list[Any]] = {}
        for topic in readable:
            seen[topic] = await dl_support.read_records(servers, topic)
        assert any(r.event_id == str(decoy_id) for r in seen[private_letters]), (
            "the decoy is on the private companion: the read is not vacuous"
        )
        mentioning = {
            topic: [r.offset for r in records if str(order.id.value).encode() in r.value]
            for topic, records in seen.items()
        }
        assert all(not offsets for offsets in mentioning.values()), (
            f"OR12: a dead letter exists for the operator-cancelled order: {mentioning}"
        )
        keyed = {
            topic: [r.offset for r in records if r.key == str(order.id.value).encode()]
            for topic, records in seen.items()
        }
        assert all(not offsets for offsets in keyed.values()), (
            f"OR12: a dead letter is keyed by the operator-cancelled order: {keyed}"
        )

        row = await saga.db.command_row(order.id, SagaCommandKind.STOCK_RELEASE)
        assert row is not None
        assert row["dead_lettered_at"] is not None, "the first park was claimed"
        assert row["triggering_event_envelope"] is None, "no synthetic envelope is stored"
        assert row["triggering_event_topic"] is None
        assert row["trace_parent"] is not None, "S4.16: the enqueue-time trace is recorded"
        assert re.match(TRACEPARENT, row["trace_parent"]), row["trace_parent"]
        outbox = await saga.db.fetch(
            "SELECT event_type, payload::text AS payload FROM outbox WHERE aggregate_id = $1",
            order.id.value,
        )
        assert [r["event_type"] for r in outbox] == ["order.saga_failed.v1"]
        assert json.loads(outbox[0]["payload"])["command"] == "stock.release"
