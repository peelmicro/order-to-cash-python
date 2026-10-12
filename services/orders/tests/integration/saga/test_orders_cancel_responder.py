# ruff: noqa: E501 - test names are the sentences the acceptance items use
"""`orders.cancel` over real NATS against the real Orders host and PostgreSQL (feature 41).

Acceptance item 2 at the responder: an order that cannot be cancelled is a DOMAIN refusal
(`ORDER_NOT_CANCELLABLE`, which the Gateway answers 409), never a timeout, an `UNAVAILABLE` or an
`INTERNAL_ERROR`; an unknown order is `NOT_FOUND`; a malformed request is `VALIDATION_FAILED`. A
refusal writes nothing. Reply key sets are compared with `asyncapi.yaml`'s own schema, both ways
(#8 D2): no key list is retyped here.
"""

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import asyncpg
import pytest
import yaml

from otc_orders.domain.order import Order
from otc_orders.domain.value_objects.order_status import OrderStatus

pytestmark = pytest.mark.integration

OrderAt = Callable[..., Awaitable[Order]]
ASYNCAPI = Path(__file__).resolve().parents[5] / "specs" / "shared" / "asyncapi.yaml"


def schema(name: str) -> tuple[set[str], set[str]]:
    """The properties and the required properties of a component schema, read from the spec."""
    document: dict[str, Any] = yaml.safe_load(ASYNCAPI.read_text(encoding="utf-8"))
    component = document["components"]["schemas"][name]
    return set(component["properties"]), set(component.get("required", []))


async def request(client: Any, body: bytes, order_id: uuid.UUID | None = None) -> dict[str, Any]:
    correlation = str(order_id or uuid.uuid4())
    reply = await client.request(
        "orders.cancel",
        body,
        timeout=10,
        headers={"x-correlation-id": correlation, "x-request-id": str(uuid.uuid4())},
    )
    answer: dict[str, Any] = json.loads(reply.data)
    return answer


def cancel_body(order_id: Any, **overrides: Any) -> bytes:
    body = {"orderId": str(order_id), "reason": "operator_cancelled"} | overrides
    return json.dumps({k: v for k, v in body.items() if v is not None}).encode()


async def test_the_reply_of_each_branch_carries_exactly_the_keys_the_schema_allows_and_every_one_it_requires(
    orders_host_factory: Any, order_at: OrderAt
) -> None:
    properties, required = schema("OrdersCancelReplyPayload")
    immediate = await order_at(OrderStatus.PLACED)
    compensating = await order_at(OrderStatus.CONFIRMED)
    async with orders_host_factory(OUTBOX_RELAY_ENABLED="false") as host:
        placed_reply = await request(host.client, cancel_body(immediate.id.value))
        confirmed_reply = await request(host.client, cancel_body(compensating.id.value))

    assert set(placed_reply) <= properties, "a key the schema does not declare"
    assert required <= set(placed_reply), "a key the schema requires is missing"
    assert set(confirmed_reply) <= properties
    assert required <= set(confirmed_reply)
    # the optional key is present exactly where the order is already cancelled
    assert "cancellationReason" in placed_reply
    assert "cancellationReason" not in confirmed_reply
    assert set(placed_reply) == properties, "the immediate branch fills every declared key"


@pytest.mark.parametrize(
    "status",
    [
        OrderStatus.DESPATCHED,
        OrderStatus.INVOICED,
        OrderStatus.PAID,
        OrderStatus.COMPLETED,
        OrderStatus.CANCELLED,
    ],
)
async def test_an_order_that_cannot_be_cancelled_is_refused_order_not_cancellable_and_nothing_is_written(
    status: OrderStatus, orders_host_factory: Any, order_at: OrderAt, migrated_db: Any
) -> None:
    order = await order_at(status)
    async with orders_host_factory(OUTBOX_RELAY_ENABLED="false") as host:
        reply = await request(host.client, cancel_body(order.id.value, note="too late"))

    assert reply["code"] == "ORDER_NOT_CANCELLABLE", reply
    assert reply["details"] == {"code": "order.not_cancellable", "status": status.value}
    assert status.value in reply["message"]
    connection = await asyncpg.connect(migrated_db.dsn)
    try:
        assert await connection.fetchval("SELECT count(*) FROM outbox") == 0
        assert await connection.fetchval("SELECT count(*) FROM saga_commands") == 0
        assert (
            await connection.fetchval("SELECT status FROM orders WHERE id = $1", order.id.value)
            == status.value
        )
    finally:
        await connection.close()


async def test_an_unknown_order_is_not_found_naming_the_order_id(
    orders_host_factory: Any, reference_data: Any
) -> None:
    missing = uuid.uuid4()
    async with orders_host_factory(OUTBOX_RELAY_ENABLED="false") as host:
        reply = await request(host.client, cancel_body(missing))

    assert reply["code"] == "NOT_FOUND", reply
    assert reply["details"] == {"field": "orderId", "value": str(missing)}


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"not json",
        b"[]",
        b"{}",
        b'{"reason":"operator_cancelled"}',
        b'{"orderId":"00000000-0000-0000-0000-000000000000","reason":"operator_cancelled"}',
        b'{"orderId":"not-a-uuid","reason":"operator_cancelled"}',
        b'{"orderId":"3c8f3b5e-5f3a-4a4e-8b1e-7a5b1b1a1a1a","reason":"credit_rejected"}',
        b'{"orderId":"3c8f3b5e-5f3a-4a4e-8b1e-7a5b1b1a1a1a"}',
        b'{"orderId":"3c8f3b5e-5f3a-4a4e-8b1e-7a5b1b1a1a1a","reason":"operator_cancelled","note":5}',
        b'{"orderReference":"ORD-000101","reason":"operator_cancelled"}',
    ],
)
async def test_a_malformed_cancel_request_is_validation_failed_never_internal_error(
    body: bytes, orders_host_factory: Any, reference_data: Any
) -> None:
    async with orders_host_factory(OUTBOX_RELAY_ENABLED="false") as host:
        reply = await request(host.client, body)

    assert reply["code"] == "VALIDATION_FAILED", reply


async def test_two_simultaneous_cancels_of_one_placed_order_cancel_it_once(
    orders_host_factory: Any, order_at: OrderAt, migrated_db: Any
) -> None:
    order = await order_at(OrderStatus.PLACED)
    async with orders_host_factory(OUTBOX_RELAY_ENABLED="false") as host:
        replies = await asyncio.gather(
            request(host.client, cancel_body(order.id.value, note="a")),
            request(host.client, cancel_body(order.id.value, note="b")),
        )

    assert sorted(str(r.get("code", r.get("status"))) for r in replies) == [
        "ORDER_NOT_CANCELLABLE",
        "cancelled",
    ]
    connection = await asyncpg.connect(migrated_db.dsn)
    try:
        types = await connection.fetch(
            "SELECT event_type FROM outbox WHERE aggregate_id = $1", order.id.value
        )
    finally:
        await connection.close()
    assert [t["event_type"] for t in types] == ["order.cancelled.v1"], "exactly one cancelled fact"
