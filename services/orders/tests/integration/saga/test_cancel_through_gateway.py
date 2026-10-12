# ruff: noqa: E501 - test names are the sentences the acceptance items use
"""Acceptance items 1 and 2 of feature 41 THROUGH THE REAL GATEWAY (`otc_gateway.main.create_app()`,
its own lifespan, its real NATS RPC client) against the REAL Orders host and PostgreSQL: no stub on
either side of the seam (`docs/lessons.md:123`).

* item 1: `POST /orders/{id}/cancel` is a 202 for every cancellable order, and its body is the
  responder's own reply as the contract declares it;
* item 2: an order that cannot be cancelled is a 409 `ORDER_NOT_CANCELLABLE` problem, an unknown one
  a 404 - a domain answer, never the 503 of an absent responder;
* item 6 (carried from feature 40's review N2): with NOBODY serving the subject, the same route
  answers 503 `UPSTREAM_UNAVAILABLE` over real NATS, at once. This is the real-NATS, HTTP-level
  proof the retired `test_cancel_answers_the_mapped_no_responder_error_until_feature_41` gave.

The Gateway is driven in-process over ASGI, as its own real-responder suite does.
"""

import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack
from typing import Any, Protocol

import asyncpg
import httpx
import pytest
import pytest_asyncio

from otc_orders.domain.order import Order
from otc_orders.domain.value_objects.order_status import OrderStatus

pytestmark = pytest.mark.integration

OPERATOR_PASSWORD = "integration-operator-password"
JWT_SECRET = "integration-jwt-secret-0123456789abcdef-0123456789"
OrderAt = Callable[..., Awaitable[Order]]


class NatsServerShape(Protocol):
    @property
    def url(self) -> str: ...


class FreshMongoDatabase(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def uri(self) -> str: ...


class GatewayClient:
    def __init__(self, http: httpx.AsyncClient, token: str) -> None:
        self.http = http
        self.auth = {"Authorization": f"Bearer {token}"}

    async def cancel(self, order_id: Any, note: str | None = None) -> httpx.Response:
        body = None if note is None else {"note": note}
        return await self.http.post(f"/orders/{order_id}/cancel", json=body, headers=self.auth)


async def _gateway(
    stack: AsyncExitStack,
    nats_server: NatsServerShape,
    mongo: FreshMongoDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> GatewayClient:
    from otc_gateway.main import create_app as create_gateway

    for name, value in {
        "NATS_URL": nats_server.url,
        "JWT_SECRET": JWT_SECRET,
        "GATEWAY_OPERATOR_PASSWORD": OPERATOR_PASSWORD,
        "GATEWAY_RPC_TIMEOUT_MS": "5000",
        "MONGO_URI": mongo.uri,
        "MONGO_DB_READMODEL": mongo.name,
    }.items():
        monkeypatch.setenv(name, value)
    app = create_gateway()
    await stack.enter_async_context(app.router.lifespan_context(app))
    http = await stack.enter_async_context(
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway.test")
    )
    login = await http.post(
        "/auth/login", json={"username": "operator", "password": OPERATOR_PASSWORD}
    )
    assert login.status_code == 200, login.text
    return GatewayClient(http, login.json()["accessToken"])


@pytest_asyncio.fixture(loop_scope="function")  # Orders host and Gateway: created and closed here
async def gateway(
    orders_host_factory: Any,
    nats_server: NatsServerShape,
    fresh_mongo_database: FreshMongoDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[GatewayClient]:
    async with orders_host_factory(OUTBOX_RELAY_ENABLED="false"), AsyncExitStack() as stack:
        yield await _gateway(stack, nats_server, fresh_mongo_database, monkeypatch)


@pytest_asyncio.fixture(loop_scope="function")  # no Orders host: nobody serves `orders.cancel`
async def gateway_alone(
    nats_server: NatsServerShape,
    fresh_mongo_database: FreshMongoDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[GatewayClient]:
    async with AsyncExitStack() as stack:
        yield await _gateway(stack, nats_server, fresh_mongo_database, monkeypatch)


async def rows(dsn: str, sql: str, *args: Any) -> list[asyncpg.Record]:
    connection = await asyncpg.connect(dsn)
    try:
        return list(await connection.fetch(sql, *args))
    finally:
        await connection.close()


@pytest.mark.parametrize(
    ("status", "planned", "answered_status", "reason"),
    [
        (OrderStatus.PLACED, [], "cancelled", "operator_cancelled"),
        (OrderStatus.STOCK_RESERVED, ["stock_release"], "stock_reserved", None),
        (OrderStatus.CREDIT_APPROVED, ["stock_release", "credit_release"], "credit_approved", None),
        (OrderStatus.CONFIRMED, ["stock_release", "credit_release"], "confirmed", None),
    ],
)
async def test_post_cancel_is_202_for_each_cancellable_status_with_the_planned_compensation_in_release_order(
    status: OrderStatus,
    planned: list[str],
    answered_status: str,
    reason: str | None,
    gateway: GatewayClient,
    order_at: OrderAt,
) -> None:
    order = await order_at(status)

    response = await gateway.cancel(order.id.value, "$note through the gateway")

    assert response.status_code == 202, response.text
    expected = {
        "orderId": str(order.id.value),
        "orderReference": order.order_reference.value,
        "status": answered_status,
        "compensationPlanned": planned,
    }
    if reason is not None:
        expected["cancellationReason"] = reason
    assert response.json() == expected


async def test_post_cancel_without_a_body_is_accepted_and_carries_no_note(
    gateway: GatewayClient, order_at: OrderAt, migrated_db: Any
) -> None:
    order = await order_at(OrderStatus.STOCK_RESERVED)

    response = await gateway.cancel(order.id.value)

    assert response.status_code == 202, response.text
    [row] = await rows(
        migrated_db.dsn,
        "SELECT operator_note FROM saga_commands WHERE order_id = $1",
        order.id.value,
    )
    assert row["operator_note"] is None


async def test_the_note_posted_reaches_the_row_that_will_complete_the_cancellation(
    gateway: GatewayClient, order_at: OrderAt, migrated_db: Any
) -> None:
    order = await order_at(OrderStatus.CONFIRMED)

    response = await gateway.cancel(order.id.value, "$where: {x: 1} — café")

    assert response.status_code == 202, response.text
    [row] = await rows(
        migrated_db.dsn,
        "SELECT command, operator_note, payload::text AS payload FROM saga_commands WHERE order_id = $1",
        order.id.value,
    )
    assert row["command"] == "stock.release"
    assert row["operator_note"] == "$where: {x: 1} — café"
    assert "$where" not in row["payload"], "the note never rides the wire request to Fulfillment"


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
async def test_a_terminal_order_is_a_409_order_not_cancellable_problem_not_a_503(
    status: OrderStatus, gateway: GatewayClient, order_at: OrderAt
) -> None:
    order = await order_at(status)

    response = await gateway.cancel(order.id.value)

    assert response.status_code == 409, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "ORDER_NOT_CANCELLABLE"


async def test_an_unknown_order_is_a_404(gateway: GatewayClient, reference_data: Any) -> None:
    response = await gateway.cancel(uuid.uuid4())

    assert response.status_code == 404, response.text
    assert response.json()["code"] == "NOT_FOUND"


async def test_without_a_token_cancel_is_401(gateway: GatewayClient, order_at: OrderAt) -> None:
    order = await order_at(OrderStatus.PLACED)

    response = await gateway.http.post(f"/orders/{order.id.value}/cancel")

    assert response.status_code == 401


async def test_a_gateway_route_whose_subject_nobody_serves_answers_503_upstream_unavailable_at_once(
    gateway_alone: GatewayClient,
) -> None:
    started = time.monotonic()

    response = await gateway_alone.cancel(uuid.uuid4())

    elapsed = time.monotonic() - started
    assert (response.status_code, response.json()["code"]) == (503, "UPSTREAM_UNAVAILABLE"), (
        response.text
    )
    assert elapsed < 3, (
        f"no responders is answered at once, not after the 5 s deadline ({elapsed:.1f}s)"
    )
