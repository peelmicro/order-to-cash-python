"""Feature 28 fixtures: ONE composed fleet per test, every service booted through its own
`create_app()` and its own real lifespan, in the test's loop, over real PostgreSQL / MongoDB /
Kafka / NATS from the repository-root session fixtures (testcontainers only; the developer stack on
5432 / 27017 / 9092 / 4222 is never contacted).

Booted: Fulfillment, Billing (the saga's two participants, relays on), Orders (responder, saga
consumer, sweeper, relay), the Projector (read model, so `GET /orders/{id}` answers) and the
Gateway (the only entry the tests drive, in-process over ASGI). NOT booted: Notifications (no
criterion observes an e-mail).

Loop scopes: every async fixture is `loop_scope="function"`, written next to it. The hosts, the
HTTP client, the asyncpg connections and the Kafka clients are created in the test's own loop and
closed in it, in reverse order (the `AsyncExitStack` exits every lifespan, which awaits the tasks
the lifespan started). The databases are private copies of the migrated templates, loaded by the
real seed; the fixture that created them drops them.

Kafka: the broker is ONE per pytest session and the three fact topics are constants of the
services, so the two consumer groups this fleet joins (`orders.saga` is a constant of Orders; the
Projector's is set here) are first committed at the END of the topics: a fleet reads only what it
publishes. The tests select their own records by order id, never by position.
"""

import asyncio
import importlib.util
import json
import sys
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Protocol

import asyncpg
import httpx
import pytest
import pytest_asyncio
from aiokafka import AIOKafkaConsumer, TopicPartition

from otc_seed.application import run_seed
from otc_seed.composition import build_runtime
from otc_seed.infrastructure.settings import SeedSettings

OPERATOR_PASSWORD = "e2e-operator-password"
JWT_SECRET = "e2e-jwt-secret-0123456789abcdef-0123456789abcdef"
ORDERS_TOPIC = "otc.orders.facts.v1"
FULFILLMENT_TOPIC = "otc.fulfillment.facts.v1"
BILLING_TOPIC = "otc.billing.facts.v1"
FACT_TOPICS = (ORDERS_TOPIC, FULFILLMENT_TOPIC, BILLING_TOPIC)
ORDERS_SAGA_GROUP = "orders.saga"  # constant of Orders' subscriber (ConsumerName.ORDERS_SAGA)
OBSERVABILITY = Path(__file__).resolve().parents[1] / "observability"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, OBSERVABILITY / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


dead_letter_support = _load("dead_letter_support")


class FreshDatabase(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def url(self) -> str: ...
    @property
    def dsn(self) -> str: ...


class FreshMongoDatabase(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def uri(self) -> str: ...


class NatsServerShape(Protocol):
    @property
    def url(self) -> str: ...


class KafkaServerShape(Protocol):
    @property
    def bootstrap_servers(self) -> str: ...


async def commit_group_at_end(bootstrap_servers: str, group: str) -> None:
    """Commit the END offset of every partition of the three fact topics under `group` (manual
    assignment: no group join, no rebalance delay)."""
    consumer = AIOKafkaConsumer(
        bootstrap_servers=bootstrap_servers,
        group_id=group,
        client_id="otc-e2e-baseline",
        enable_auto_commit=False,
    )
    await consumer.start()
    try:
        partitions = [
            TopicPartition(topic, partition)
            for topic in FACT_TOPICS
            for partition in await dead_letter_support.partitions_of(bootstrap_servers, topic)
        ]
        consumer.assign(partitions)
        ends: dict[Any, int] = await consumer.end_offsets(partitions)
        await consumer.commit({tp: ends[tp] for tp in partitions})
    finally:
        await asyncio.sleep(0.05)  # aiokafka 0.14.0: stop() can raise CancelledError before a tick
        await consumer.stop()


async def eventually[T](
    probe: Callable[[], Awaitable[T | None]], what: str, *, seconds: float = 60.0
) -> T:
    """Poll `probe` every 100 ms until it answers something other than None / False / empty, or
    fail naming `what`. The pacing is explicit and bounded; a test never sleeps blind."""
    deadline = asyncio.get_running_loop().time() + seconds
    while True:
        found = await probe()
        if found:
            return found
        if asyncio.get_running_loop().time() > deadline:
            raise TimeoutError(f"never happened within {seconds} s: {what}")
        await asyncio.sleep(0.1)


@dataclass
class Fleet:
    http: httpx.AsyncClient  # the Gateway, in-process over ASGI, already logged in
    databases: dict[str, FreshDatabase]  # "orders" | "fulfillment" | "billing"
    mongo: FreshMongoDatabase
    bootstrap_servers: str

    async def rows(self, database: str, sql: str, *args: Any) -> list[asyncpg.Record]:
        connection = await asyncpg.connect(self.databases[database].dsn)
        try:
            return list(await connection.fetch(sql, *args))
        finally:
            await connection.close()

    async def place(
        self, lines: list[dict[str, Any]], *, traceparent: str | None = None
    ) -> httpx.Response:
        headers = {"traceparent": traceparent} if traceparent else {}
        return await self.http.post(
            "/orders",
            json={
                "retailerCode": "AldiEs",
                "companyCode": "SPANATURAL",
                "currency": "EUR",
                "lines": lines,
            },
            headers=headers,
        )

    async def order_status(self, order_id: str) -> str | None:
        rows = await self.rows(
            "orders", "SELECT status FROM orders WHERE id = $1", uuid.UUID(order_id)
        )
        return str(rows[0]["status"]) if rows else None

    async def wait_status(self, order_id: str, status: str) -> None:
        async def reached() -> bool:
            return await self.order_status(order_id) == status

        await eventually(reached, f"order {order_id} reaches {status}")

    async def pay(
        self, order_reference: str, reference: str, *, traceparent: str | None = None
    ) -> httpx.Response:
        """Register the remittance for the order's invoice through the Gateway."""

        async def issued() -> list[dict[str, Any]] | None:
            page = (await self.http.get(f"/invoices?orderReference={order_reference}")).json()
            return list(page["items"]) if page.get("items") else None

        invoice = (await eventually(issued, f"an invoice of {order_reference} is listed"))[0]
        headers = {"traceparent": traceparent} if traceparent else {}
        return await self.http.post(
            f"/invoices/{invoice['invoiceId']}/payments",
            json={
                "paymentReference": reference,
                "amount": {"amount": invoice["totalAmount"], "currency": "EUR"},
                "valueDate": "2026-10-13T08:30:00.000Z",
                "source": "test",
            },
            headers=headers,
        )

    async def eventually[T](
        self, probe: Callable[[], Awaitable[T | None]], what: str, *, seconds: float = 60.0
    ) -> T:
        return await eventually(probe, what, seconds=seconds)

    async def observed_facts(self, order_id: str) -> list[tuple[str, str]]:
        return await observed_facts(self, order_id)

    async def facts_reach(self, order_id: str, expected: list[tuple[str, str]]) -> None:
        await facts_reach(self, order_id, expected)

    async def produce(self, topic: str, key: bytes, value: bytes) -> None:
        await dead_letter_support.produce(self.bootstrap_servers, topic, key=key, value=value)

    async def read_all(self, topic: str) -> list[Any]:
        """Every record on `topic` as the broker holds it (no group, nothing committed)."""
        found: list[Any] = await dead_letter_support.read_records(self.bootstrap_servers, topic)
        return found

    async def records(self, topic: str, order_id: str) -> list[Any]:
        """Every record on `topic` keyed by `order_id`, as the broker holds it."""
        return [r for r in await self.read_all(topic) if r.key == order_id.encode("utf-8")]


@pytest_asyncio.fixture(loop_scope="function")  # hosts, clients, connections: this test's loop
async def fleet(
    migrated_database_from_template: Callable[[str], Awaitable[FreshDatabase]],
    fresh_mongo_database: FreshMongoDatabase,
    nats_server: NatsServerShape,
    kafka_server: KafkaServerShape,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> AsyncIterator[Fleet]:
    from otc_billing.main import create_app as create_billing
    from otc_fulfillment.main import create_app as create_fulfillment
    from otc_gateway.main import create_app as create_gateway
    from otc_orders.main import create_app as create_orders
    from otc_projector.main import create_app as create_projector

    databases = {
        name: await migrated_database_from_template(name)
        for name in ("orders", "fulfillment", "billing")
    }
    monkeypatch.chdir(tmp_path)  # no developer `.env` can reach a settings class
    for name in (
        "POSTGRES_APP_PASSWORD",
        "POSTGRES_APP_USER",
        "POSTGRES_HOST",
        "POSTGRES_HOST_PORT",
    ):
        monkeypatch.delenv(name, raising=False)

    def environment(**values: str) -> None:
        for name, value in values.items():
            monkeypatch.setenv(name, value)

    environment(
        ORDERS_DATABASE_URL=databases["orders"].url,
        FULFILLMENT_DATABASE_URL=databases["fulfillment"].url,
        BILLING_DATABASE_URL=databases["billing"].url,
        MONGO_URI=fresh_mongo_database.uri,
        MONGO_DB_READMODEL=fresh_mongo_database.name,
    )
    seed = build_runtime(SeedSettings(_env_file=None))  # type: ignore[call-arg]
    try:
        await run_seed(seed.targets)  # the reference data: retailers, products, stock, credit lines
    finally:
        await seed.aclose()

    projector_group = f"projector-e2e-{uuid.uuid4().hex[:8]}"
    await commit_group_at_end(kafka_server.bootstrap_servers, ORDERS_SAGA_GROUP)
    await commit_group_at_end(kafka_server.bootstrap_servers, projector_group)

    environment(
        NATS_URL=nats_server.url,
        KAFKA_BROKERS=kafka_server.bootstrap_servers,
        OUTBOX_RELAY_ENABLED="true",
        OUTBOX_POLL_INTERVAL_MS="50",
        WEB_CONCURRENCY="1",
        FACT_RETRY_MAX_ATTEMPTS="3",
        FACT_RETRY_BACKOFF_MS="20",
        CREDIT_FAILURE_RATE="0",
    )
    async with AsyncExitStack() as hosts:
        environment(
            FULFILLMENT_KAFKA_CLIENT_ID="otc-fulfillment-e2e",
            FULFILLMENT_MAX_CONCURRENT_REQUESTS="8",
        )
        fulfillment = create_fulfillment()
        await hosts.enter_async_context(fulfillment.router.lifespan_context(fulfillment))
        environment(BILLING_KAFKA_CLIENT_ID="otc-billing-e2e", BILLING_MAX_CONCURRENT_REQUESTS="8")
        billing = create_billing()
        await hosts.enter_async_context(billing.router.lifespan_context(billing))
        environment(
            KAFKA_CLIENT_ID="otc-orders-e2e",
            STOCK_CHECK_TIMEOUT_MS="5000",
            SAGA_CONSUMER_ENABLED="true",
            SAGA_COMMAND_TIMEOUT_MS="5000",
        )
        orders = create_orders()
        await hosts.enter_async_context(orders.router.lifespan_context(orders))
        environment(
            PROJECTOR_KAFKA_CLIENT_ID="otc-projector-e2e", PROJECTOR_CONSUMER_GROUP=projector_group
        )
        projector = create_projector()
        await hosts.enter_async_context(projector.router.lifespan_context(projector))
        environment(
            JWT_SECRET=JWT_SECRET,
            GATEWAY_OPERATOR_PASSWORD=OPERATOR_PASSWORD,
            GATEWAY_RPC_TIMEOUT_MS="10000",
        )
        gateway = create_gateway()
        await hosts.enter_async_context(gateway.router.lifespan_context(gateway))
        http = await hosts.enter_async_context(
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=gateway), base_url="http://gateway.test"
            )
        )
        login = await http.post(
            "/auth/login", json={"username": "operator", "password": OPERATOR_PASSWORD}
        )
        assert login.status_code == 200, login.text
        http.headers["Authorization"] = f"Bearer {login.json()['accessToken']}"
        yield Fleet(
            http=http,
            databases=databases,
            mongo=fresh_mongo_database,
            bootstrap_servers=kafka_server.bootstrap_servers,
        )


def event_types(records: list[Any]) -> list[str]:
    return sorted(str(json.loads(r.value)["eventType"]) for r in records)


TOPIC_NAMES = {ORDERS_TOPIC: "orders", FULFILLMENT_TOPIC: "fulfillment", BILLING_TOPIC: "billing"}


async def observed_facts(fleet: Fleet, order_id: str) -> list[tuple[str, str]]:
    """Every fact the brokers hold for `order_id` (key = the order id), as sorted
    (producing service, eventType) pairs. Read from the topics, never inferred from a table."""
    observed: list[tuple[str, str]] = []
    for topic in FACT_TOPICS:
        for record in await fleet.records(topic, order_id):
            observed.append((TOPIC_NAMES[topic], str(json.loads(record.value)["eventType"])))
    return sorted(observed)


async def facts_reach(fleet: Fleet, order_id: str, expected: list[tuple[str, str]]) -> None:
    """Wait (bounded, paced) until the order's facts on the brokers are exactly `expected`, then
    read once more and require the same set: nothing else was published meanwhile."""

    async def reached() -> bool:
        return await observed_facts(fleet, order_id) == sorted(expected)

    await eventually(reached, f"the facts of {order_id} are exactly {sorted(expected)}")
    assert await observed_facts(fleet, order_id) == sorted(expected)
