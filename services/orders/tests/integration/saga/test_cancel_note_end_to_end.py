# ruff: noqa: E501 - test names are the sentences the acceptance items use
"""Acceptance item 4 of feature 41, END TO END: the operator's note posted to
`POST /orders/{id}/cancel` reaches the read-model timeline that `GET /orders/{id}` serves.

Everything on the path is the real thing: the Gateway (`otc_gateway.main.create_app()`), the Orders
host (responder, saga consumer, sweeper, outbox relay), PostgreSQL, NATS, Kafka, the Projector host
(`otc_projector.main.create_app()`, its own consumer group) and MongoDB. The only stand-ins are the
saga's other participants (Fulfillment and Billing), real NATS responders that record what they are
asked and publish the facts their real counterparts would.

Three starting statuses are driven through the saga: `placed` (an immediate cancellation),
`stock_reserved` (one release, the stock fact cancels) and `confirmed` (two releases, the credit
fact cancels). `credit_approved` is not reachable through the saga (the order takes both edges in one
step), so its note is proved at the outbox in `test_operator_cancel_flow.py`.

The note begins with `$` and holds non-ASCII text: it must arrive byte for byte (PR47).
"""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

import httpx
import pytest

from otc_orders.application.saga.command_kind import SagaCommandKind

pytestmark = pytest.mark.integration

OPERATOR_PASSWORD = "integration-operator-password"
JWT_SECRET = "integration-jwt-secret-0123456789abcdef-0123456789"
NOTE = "$set: the pallet is gone — café €"
Waits = Callable[..., Awaitable[None]]


@asynccontextmanager
async def read_side(
    monkeypatch: pytest.MonkeyPatch,
    *,
    nats_url: str,
    bootstrap_servers: str,
    mongo: Any,
    commit_at_end: Callable[[str, str], Awaitable[None]],
) -> AsyncIterator[httpx.AsyncClient]:
    """The Projector host (a fresh consumer group, started at the END of the topics so the facts of
    earlier tests are not replayed) and the Gateway over it; yields the Gateway's HTTP client."""
    from otc_gateway.main import create_app as create_gateway
    from otc_projector.main import create_app as create_projector

    group = f"projector-n41-{uuid.uuid4().hex[:8]}"
    await commit_at_end(bootstrap_servers, group)
    for name, value in {
        "MONGO_URI": mongo.uri,
        "MONGO_DB_READMODEL": mongo.name,
        "NATS_URL": nats_url,
        "KAFKA_BROKERS": bootstrap_servers,
        "PROJECTOR_KAFKA_CLIENT_ID": "otc-projector-n41",
        "PROJECTOR_CONSUMER_GROUP": group,
        "JWT_SECRET": JWT_SECRET,
        "GATEWAY_OPERATOR_PASSWORD": OPERATOR_PASSWORD,
        "GATEWAY_RPC_TIMEOUT_MS": "8000",
    }.items():
        monkeypatch.setenv(name, value)
    async with AsyncExitStack() as stack:
        projector = create_projector()
        await stack.enter_async_context(projector.router.lifespan_context(projector))
        gateway = create_gateway()
        await stack.enter_async_context(gateway.router.lifespan_context(gateway))
        http = await stack.enter_async_context(
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=gateway), base_url="http://gateway.test"
            )
        )
        login = await http.post(
            "/auth/login", json={"username": "operator", "password": OPERATOR_PASSWORD}
        )
        assert login.status_code == 200, login.text
        http.headers["Authorization"] = f"Bearer {login.json()['accessToken']}"
        yield http


@pytest.mark.parametrize("start", ["placed", "stock_reserved", "confirmed"])
async def test_the_note_posted_through_the_gateway_is_on_the_timeline_entry_of_order_cancelled(
    start: str,
    saga_harness: Any,
    stand_in_stock_check: Any,
    stock_reply: Callable[..., bytes],
    reference_data: Any,
    waits: Waits,
    nats_server: Any,
    kafka_server: Any,
    fresh_mongo_database: Any,
    commit_at_end: Callable[[str, str], Awaitable[None]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await stand_in_stock_check(lambda _request: stock_reply([("SKU-A", 3, 50), ("SKU-B", 2, 50)]))
    async with saga_harness() as saga:
        stand_in = saga.stand_in
        # Where each order is left to wait: `placed` (stock.reserve answered, no fact),
        # `stock_reserved` (credit.hold unanswered) or `confirmed` (despatch.create unanswered).
        stand_in(SagaCommandKind.STOCK_RESERVE).emit = start != "placed"
        stand_in(SagaCommandKind.CREDIT_HOLD).emit = start == "confirmed"
        if start == "stock_reserved":
            stand_in(SagaCommandKind.CREDIT_HOLD).behaviour = saga.behaviours["silent"]
        if start == "confirmed":
            stand_in(SagaCommandKind.DESPATCH_CREATE).behaviour = saga.behaviours["silent"]
        stand_in(SagaCommandKind.STOCK_RELEASE).emit = True
        stand_in(SagaCommandKind.CREDIT_RELEASE).emit = True

        async with read_side(
            monkeypatch,
            nats_url=nats_server.url,
            bootstrap_servers=kafka_server.bootstrap_servers,
            mongo=fresh_mongo_database,
            commit_at_end=commit_at_end,
        ) as http:
            placed = await http.post(
                "/orders",
                json={
                    "retailerCode": "RET-01",
                    "companyCode": "CMP-01",
                    "currency": "EUR",
                    "lines": [
                        {"productCode": "SKU-A", "quantity": 3, "unitPrice": 1999},
                        {"productCode": "SKU-B", "quantity": 2, "unitPrice": 1234},
                    ],
                },
            )
            assert placed.status_code == 201, placed.text
            order_id = uuid.UUID(placed.json()["orderId"])

            async def at_start() -> bool:
                return bool(await saga.db.status_of(order_id) == start)

            await waits(at_start, f"the order waits at {start}")

            cancel = await http.post(f"/orders/{order_id}/cancel", json={"note": NOTE})
            assert cancel.status_code == 202, cancel.text

            async def on_the_timeline() -> bool:
                response = await http.get(f"/orders/{order_id}")
                if response.status_code != 200:
                    return False
                return any(
                    e["eventType"] == "order.cancelled.v1" for e in response.json()["events"]
                )

            await waits(
                on_the_timeline, "order.cancelled.v1 is on the order's timeline", seconds=60
            )

            detail = (await http.get(f"/orders/{order_id}")).json()
            [entry] = [e for e in detail["events"] if e["eventType"] == "order.cancelled.v1"]
            assert detail["status"] == "cancelled"
            assert detail["cancellationReason"] == "operator_cancelled"
            assert entry["detail"].get("note") == NOTE, (
                "the note, byte for byte, on the order.cancelled.v1 timeline entry"
            )
            assert entry["detail"]["cancellationReason"] == "operator_cancelled"
            steps = [s["step"] for s in entry["detail"]["compensationSteps"]]
            assert (
                steps
                == {
                    "placed": [],
                    "stock_reserved": ["stock_released"],
                    "confirmed": ["stock_released", "credit_released"],
                }[start]
            )
