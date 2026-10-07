"""`orders.create` end to end over real NATS, Postgres and Kafka (feature 15, acceptance items 1-3).

The caller is a plain NATS client (what the Gateway is); the service is the REAL host
(`otc_orders.main.create_app()` and its lifespan); Fulfillment is a stand-in on the real
`fulfillment.stock.check` subject. Nothing is mocked.

Money fixtures are pairwise distinct and non-zero: initial amount 8465, discounts 350, total 8115
(#7's blocking defect was a swapped reply field that a zero discount hid).
"""

import asyncio
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import asyncpg
import pytest
from nats.aio.client import Client as NatsClient

from otc_orders.composition import OrdersRuntime

REQUEST: dict[str, Any] = {
    "retailerCode": "RET-01",
    "companyCode": "CMP-01",
    "currency": "EUR",
    "lines": [
        {"productCode": "SKU-A", "quantity": 3, "unitPrice": 1999, "lineDiscount": 250},
        {"productCode": "SKU-B", "quantity": 2, "unitPrice": 1234, "lineDiscount": 100},
    ],
    "notes": "dock 4, before noon",
}
ENOUGH = [("SKU-A", 3, 50), ("SKU-B", 2, 50)]


class Host:
    """Just what these tests need from the `orders_host` fixture."""

    runtime: OrdersRuntime
    client: NatsClient


async def call(client: NatsClient, payload: dict[str, Any] | bytes) -> Any:
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    reply = await client.request("orders.create", body, timeout=10)
    return json.loads(reply.data)


async def rows(dsn: str, sql: str, *args: object) -> list[asyncpg.Record]:
    conn = await asyncpg.connect(dsn)
    try:
        return await conn.fetch(sql, *args)
    finally:
        await conn.close()


async def test_acceptance_1_and_2_stock_is_checked_synchronously_and_the_order_id_is_returned(
    orders_host: Any,
    stand_in_stock_check: Any,
    stock_reply: Callable[..., bytes],
    migrated_db: Any,
) -> None:
    stand_in = await stand_in_stock_check(lambda request: stock_reply(ENOUGH))

    reply = await call(orders_host.client, REQUEST)

    assert reply["status"] == "placed"
    assert reply["orderReference"] == "ORD-000001"
    order_id = uuid.UUID(reply["orderId"])
    assert reply["currency"] == "EUR"
    # three pairwise-distinct, non-zero money values, each from its own source
    assert (reply["initialAmount"], reply["initialDiscount"], reply["totalAmount"]) == (
        8465,
        350,
        8115,
    )
    assert len({reply["initialAmount"], reply["initialDiscount"], reply["totalAmount"]}) == 3
    assert reply["orderDate"].endswith("Z")
    assert len(reply["orderDate"]) == 24
    # the stock check carried this request's company and lines, in order
    assert stand_in.requests == [
        {
            "companyCode": "CMP-01",
            "lines": [
                {"productCode": "SKU-A", "quantity": 3},
                {"productCode": "SKU-B", "quantity": 2},
            ],
        }
    ]
    # the order is committed, `placed`, with its totals, and the fact is in the outbox
    [order] = await rows(migrated_db.dsn, "SELECT * FROM orders WHERE id = $1", order_id)
    assert (order["status"], order["order_reference"], order["notes"]) == (
        "placed",
        "ORD-000001",
        "dock 4, before noon",
    )
    assert (order["initial_amount"], order["initial_discount"], order["total_amount"]) == (
        8465,
        350,
        8115,
    )
    facts = await rows(
        migrated_db.dsn, "SELECT event_type FROM outbox WHERE aggregate_id = $1", order_id
    )
    assert [f["event_type"] for f in facts] == ["order.placed.v1"]


async def test_an_order_in_a_zero_decimal_currency_is_placed_and_answered_in_that_currency(
    orders_host: Any,
    stand_in_stock_check: Any,
    stock_reply: Callable[..., bytes],
    migrated_db: Any,
) -> None:
    conn = await asyncpg.connect(migrated_db.dsn)
    try:
        await conn.execute(
            "INSERT INTO currencies VALUES ($1, 'JPY', '392', 'J', 0, now(), now())", uuid.uuid4()
        )
    finally:
        await conn.close()
    await stand_in_stock_check(lambda request: stock_reply(ENOUGH))

    reply = await call(orders_host.client, REQUEST | {"currency": "JPY"})

    assert reply["status"] == "placed", reply
    assert reply["currency"] == "JPY"
    assert (reply["initialAmount"], reply["initialDiscount"], reply["totalAmount"]) == (
        8465,
        350,
        8115,
    )
    [order] = await rows(
        migrated_db.dsn,
        "SELECT c.code FROM orders o JOIN currencies c ON c.id = o.currency_id WHERE o.id = $1",
        uuid.UUID(reply["orderId"]),
    )
    assert order["code"] == "JPY"


async def test_acceptance_2_the_placed_fact_reaches_kafka_through_the_started_relay(
    orders_host: Any,
    stand_in_stock_check: Any,
    stock_reply: Callable[..., bytes],
    migrated_db: Any,
    read_topic: Callable[[], Awaitable[list[Any]]],
) -> None:
    await stand_in_stock_check(lambda request: stock_reply(ENOUGH))
    reply = await call(orders_host.client, REQUEST)
    order_id = reply["orderId"]
    deadline = time.monotonic() + 30
    found: list[dict[str, Any]] = []
    while time.monotonic() < deadline and not found:
        found = [
            json.loads(record.value)
            for record in await read_topic()
            if json.loads(record.value).get("aggregateId") == order_id
        ]
        await asyncio.sleep(0.2)
    assert [envelope["eventType"] for envelope in found] == ["order.placed.v1"]
    assert found[0]["payload"]["orderReference"] == "ORD-000001"
    assert found[0]["payload"]["totalAmount"] == 8115


async def test_acceptance_2_a_short_line_is_refused_with_the_shortage_and_persists_nothing(
    orders_host: Any,
    stand_in_stock_check: Any,
    stock_reply: Callable[..., bytes],
    migrated_db: Any,
) -> None:
    await stand_in_stock_check(lambda request: stock_reply([("SKU-A", 3, 50), ("SKU-B", 2, 1)]))

    reply = await call(orders_host.client, REQUEST)

    assert reply["code"] == "STOCK_UNAVAILABLE"
    assert reply["details"] == {
        "shortages": [{"productCode": "SKU-B", "requested": 2, "available": 1}]
    }
    assert await rows(migrated_db.dsn, "SELECT 1 FROM orders") == []
    assert await rows(migrated_db.dsn, "SELECT 1 FROM outbox") == []
    # no transaction was ever opened, so no number was allocated either
    assert await rows(migrated_db.dsn, "SELECT 1 FROM order_number_sequences") == []


async def test_a_line_without_a_unit_price_snapshots_the_catalogue_price_and_description(
    orders_host: Any,
    stand_in_stock_check: Any,
    stock_reply: Callable[..., bytes],
    migrated_db: Any,
) -> None:
    conn = await asyncpg.connect(migrated_db.dsn)
    try:
        await conn.execute(
            "UPDATE products SET price = 777, description = 'Alpha pallet' WHERE code = 'SKU-A'"
        )
    finally:
        await conn.close()
    await stand_in_stock_check(lambda request: stock_reply([("SKU-A", 4, 9)]))
    request = REQUEST | {"lines": [{"productCode": "SKU-A", "quantity": 4}], "notes": None}

    reply = await call(orders_host.client, request)

    assert (reply["initialAmount"], reply["initialDiscount"], reply["totalAmount"]) == (
        3108,
        0,
        3108,
    )
    [item] = await rows(migrated_db.dsn, "SELECT price, description, quantity FROM order_items")
    assert (item["price"], item["description"], item["quantity"]) == (777, "Alpha pallet", 4)


@pytest.mark.parametrize(
    ("field", "value", "unknown"),
    [
        ("retailerCode", "NOPE", "retailerCode"),
        ("companyCode", "NOPE", "companyCode"),
        ("currency", "XXX", "currency"),
    ],
)
async def test_an_unknown_reference_code_is_not_found_before_any_stock_check(
    orders_host: Any,
    stand_in_stock_check: Any,
    stock_reply: Callable[..., bytes],
    migrated_db: Any,
    field: str,
    value: str,
    unknown: str,
) -> None:
    stand_in = await stand_in_stock_check(lambda request: stock_reply(ENOUGH))

    reply = await call(orders_host.client, REQUEST | {field: value})

    assert reply["code"] == "NOT_FOUND"
    assert reply["details"] == {"field": unknown, "value": value}
    assert stand_in.requests == []
    assert await rows(migrated_db.dsn, "SELECT 1 FROM orders") == []


async def test_an_unknown_product_code_is_not_found_with_that_line_s_code(
    orders_host: Any,
    stand_in_stock_check: Any,
    stock_reply: Callable[..., bytes],
) -> None:
    stand_in = await stand_in_stock_check(lambda request: stock_reply(ENOUGH))
    lines = [REQUEST["lines"][0], {"productCode": "SKU-GHOST", "quantity": 1}]

    reply = await call(orders_host.client, REQUEST | {"lines": lines})

    assert reply["code"] == "NOT_FOUND"
    assert reply["details"] == {"field": "productCode", "value": "SKU-GHOST"}
    assert stand_in.requests == []


async def test_a_non_zero_order_discount_is_refused_and_a_zero_one_is_accepted(
    orders_host: Any,
    stand_in_stock_check: Any,
    stock_reply: Callable[..., bytes],
    migrated_db: Any,
) -> None:
    await stand_in_stock_check(lambda request: stock_reply(ENOUGH))

    refused = await call(orders_host.client, REQUEST | {"orderDiscount": 500})
    accepted = await call(orders_host.client, REQUEST | {"orderDiscount": 0})

    assert refused["code"] == "VALIDATION_FAILED"
    assert refused["message"].startswith("orderDiscount 5.00 EUR was supplied")
    assert accepted["status"] == "placed"
    assert len(await rows(migrated_db.dsn, "SELECT 1 FROM orders")) == 1


async def test_an_aggregate_refusal_is_validation_failed_with_the_domain_code_under_details_code(
    orders_host: Any,
    stand_in_stock_check: Any,
    stock_reply: Callable[..., bytes],
    migrated_db: Any,
) -> None:
    await stand_in_stock_check(lambda request: stock_reply(ENOUGH))
    # a discount larger than the line: the aggregate refuses a negative total
    lines = [{"productCode": "SKU-A", "quantity": 1, "unitPrice": 100, "lineDiscount": 5000}]

    reply = await call(orders_host.client, REQUEST | {"lines": lines})

    assert reply["code"] == "VALIDATION_FAILED"
    assert reply["details"] == {"code": "order.total_must_not_be_negative"}
    assert "domainCode" not in reply["details"]
    assert await rows(migrated_db.dsn, "SELECT 1 FROM orders") == []
    # the transaction rolled back, and with it the number it had allocated (and the counter row it
    # had seeded): the next order is ORD-000001, not ORD-000002
    accepted = await call(orders_host.client, REQUEST)
    assert accepted["orderReference"] == "ORD-000001"


async def test_a_quantity_beyond_int32_is_refused_at_the_write_boundary_as_a_domain_code(
    orders_host: Any,
    stand_in_stock_check: Any,
    stock_reply: Callable[..., bytes],
    migrated_db: Any,
) -> None:
    await stand_in_stock_check(lambda request: stock_reply([("SKU-A", 2**31, 2**31)]))
    lines = [{"productCode": "SKU-A", "quantity": 2**31, "unitPrice": 1, "lineDiscount": 0}]

    reply = await call(orders_host.client, REQUEST | {"lines": lines})

    assert reply["code"] == "VALIDATION_FAILED"
    assert reply["details"] == {"code": "quantity.out_of_range"}
    assert await rows(migrated_db.dsn, "SELECT 1 FROM orders") == []


async def test_a_request_id_on_the_wire_is_carried_and_the_order_is_still_placed(
    orders_host: Any,
    stand_in_stock_check: Any,
    stock_reply: Callable[..., bytes],
) -> None:
    # R62 (idempotent replay) is `observability_reliability`'s; here the field must be accepted.
    await stand_in_stock_check(lambda request: stock_reply(ENOUGH))

    reply = await call(orders_host.client, REQUEST | {"requestId": str(uuid.uuid4())})

    assert reply["status"] == "placed"


async def test_no_responder_on_the_stock_check_subject_is_unavailable_at_once_and_persists_nothing(
    orders_host: Any, migrated_db: Any
) -> None:
    started = time.monotonic()
    reply = await call(orders_host.client, REQUEST)
    elapsed = time.monotonic() - started

    assert reply["code"] == "UNAVAILABLE"
    assert reply["details"] == {"subject": "fulfillment.stock.check"}
    assert reply["message"] == "no responder is subscribed to fulfillment.stock.check."
    assert elapsed < 1.0, f"no-responders must not wait out the 1.5 s budget: {elapsed:.2f}s"
    assert await rows(migrated_db.dsn, "SELECT 1 FROM orders") == []


async def test_a_silent_stock_check_responder_is_a_timeout_after_the_budget_and_persists_nothing(
    orders_host: Any, stand_in_stock_check: Any, migrated_db: Any
) -> None:
    await stand_in_stock_check(lambda request: None)

    started = time.monotonic()
    reply = await call(orders_host.client, REQUEST)
    elapsed = time.monotonic() - started

    assert reply["code"] == "TIMEOUT"
    assert reply["details"] == {"subject": "fulfillment.stock.check", "timeoutMs": 1500}
    assert elapsed >= 1.4, f"a timeout is the budget elapsing: {elapsed:.2f}s"
    assert elapsed < 3.0, f"the 1.5 s budget is what was applied, not a longer one: {elapsed:.2f}s"
    assert await rows(migrated_db.dsn, "SELECT 1 FROM orders") == []


async def test_the_stock_check_responder_s_own_error_passes_through_with_its_code_and_message(
    orders_host: Any, stand_in_stock_check: Any
) -> None:
    await stand_in_stock_check(
        lambda request: json.dumps(
            {"code": "VALIDATION_FAILED", "message": "company CMP-01 has no warehouse"}
        ).encode()
    )

    reply = await call(orders_host.client, REQUEST)

    assert reply["code"] == "VALIDATION_FAILED"
    assert reply["message"] == "company CMP-01 has no warehouse"
    assert reply["details"] == {"subject": "fulfillment.stock.check"}


async def test_a_responder_code_outside_the_wire_enum_is_unavailable_carrying_that_code(
    orders_host: Any, stand_in_stock_check: Any
) -> None:
    await stand_in_stock_check(
        lambda request: json.dumps({"code": "WAREHOUSE_ON_FIRE", "message": "boom"}).encode()
    )

    reply = await call(orders_host.client, REQUEST)

    assert reply["code"] == "UNAVAILABLE"
    assert reply["details"] == {
        "subject": "fulfillment.stock.check",
        "responderCode": "WAREHOUSE_ON_FIRE",
    }


async def test_a_stock_check_reply_that_is_not_json_is_unavailable_never_internal_error(
    orders_host: Any, stand_in_stock_check: Any
) -> None:
    await stand_in_stock_check(lambda request: b"<html>502 Bad Gateway</html>")

    reply = await call(orders_host.client, REQUEST)

    assert reply["code"] == "UNAVAILABLE"
    assert reply["message"].endswith("reply payload was not valid JSON.")
