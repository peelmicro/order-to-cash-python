"""Orders integration fixtures: an Alembic runner and a migrated database per test.

The shared container and `fresh_database` live in the repository-root `conftest.py`.
"""

import asyncio
import json
import uuid
import warnings
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Sequence
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import asyncpg
import nats
import pytest
import pytest_asyncio
from aiokafka import AIOKafkaConsumer, TopicPartition
from aiokafka.admin import AIOKafkaAdminClient
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from nats.aio.client import Client as NatsClient
from nats.aio.msg import Msg as NatsMsg
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.community.nats import NatsContainer

from otc_orders.composition import OrdersRuntime
from otc_orders.domain.order import Order
from otc_orders.domain.order_line import OrderLineInput
from otc_orders.infrastructure.clock import SystemClock
from otc_orders.infrastructure.outbox.kafka_publisher import KafkaFactPublisher
from otc_orders.infrastructure.outbox.publisher import FactPublisher
from otc_orders.infrastructure.outbox.relay import OutboxRelay
from otc_orders.infrastructure.outbox.topic import ORDERS_FACTS_TOPIC
from otc_orders.infrastructure.outbox.writer import OutboxWriter
from otc_orders.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from otc_orders.infrastructure.settings import KafkaSettings
from otc_orders.main import create_app
from otc_shared_kernel import GLN, Money, OrderNumber, Quantity, UniqueId


class FreshDatabase(Protocol):
    """The shape of the root conftest's `FreshDatabase` (not imported: conftest modules are not
    importable by name under `--import-mode=importlib`)."""

    @property
    def name(self) -> str: ...
    @property
    def url(self) -> str: ...
    @property
    def dsn(self) -> str: ...


ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"

AlembicRunner = Callable[[str, str, str], Awaitable[None]]


async def _run_alembic(url: str, action: str, revision: str) -> None:
    config = Config(str(ALEMBIC_INI))
    config.attributes["url"] = url

    def _go() -> None:
        if action == "upgrade":
            command.upgrade(config, revision)
        else:
            command.downgrade(config, revision)

    # env.py is the stock async template and calls asyncio.run(); that cannot run inside the test's
    # own running loop, so it runs in a worker thread with a loop of its own. The engine it creates
    # lives and is disposed entirely inside that loop (env.py's `finally: engine.dispose()`).
    await asyncio.to_thread(_go)


@pytest.fixture
def alembic_runner() -> AlembicRunner:
    return _run_alembic


@pytest_asyncio.fixture(loop_scope="function")
async def migrated_db(
    migrated_database_from_template: Callable[[str], Awaitable[FreshDatabase]],
) -> FreshDatabase:
    # a private copy of the session's migrated template (root conftest.py), not a fresh migration
    return await migrated_database_from_template("orders")


@pytest_asyncio.fixture(loop_scope="function")
async def engine(migrated_db: FreshDatabase) -> AsyncIterator[AsyncEngine]:
    # Function loop; created and disposed here, in the loop that uses it.
    eng = create_async_engine(migrated_db.url)
    try:
        yield eng
    finally:
        await eng.dispose()


@dataclass(frozen=True)
class Parents:
    """Ids of one currency, company, retailer and product, inserted with raw SQL (no ORM)."""

    currency: uuid.UUID
    company: uuid.UUID
    retailer: uuid.UUID
    product: uuid.UUID


NOW = datetime(2026, 10, 5, 12, 0, 0, 123000, tzinfo=UTC)


@pytest_asyncio.fixture(loop_scope="function")
async def parents(migrated_db: FreshDatabase) -> Parents:
    ids = Parents(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
    conn = await asyncpg.connect(migrated_db.dsn)
    try:
        await conn.execute(
            "INSERT INTO currencies VALUES ($1, 'EUR', '978', 'E', 2, $2, $2)", ids.currency, NOW
        )
        for table, pid in (("companies", ids.company), ("retailers", ids.retailer)):
            await conn.execute(
                f"INSERT INTO {table} VALUES "  # noqa: S608
                "($1, $2, 'name', 'ES', 'VAT', '5400000000034', $3, NULL, $4, $4)",
                pid,
                f"{table}-code",
                ids.currency,
                NOW,
            )
        await conn.execute(
            "INSERT INTO products VALUES "
            "($1, 'PRD-1', '5400000000041', 'p', 'd', 100, $2, NULL, $3, $3)",
            ids.product,
            ids.currency,
            NOW,
        )
    finally:
        await conn.close()
    return ids


# ----------------------------------------------------------------- feature 14: the write path


@pytest_asyncio.fixture(loop_scope="function")
async def sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # `expire_on_commit=False`: an aggregate read back after the commit needs no refresh round trip.
    # The sessionmaker holds no connection; the `engine` fixture disposes the pool in this loop.
    return async_sessionmaker(engine, expire_on_commit=False)


@dataclass(frozen=True)
class ReferenceData:
    """Codes of the reference rows `reference_data` inserted (the aggregate carries codes)."""

    retailer_code: str
    company_code: str
    buyer_gln: str
    supplier_gln: str
    currency: str
    product_codes: tuple[str, str, str]


@pytest_asyncio.fixture(loop_scope="function")
async def reference_data(migrated_db: FreshDatabase) -> ReferenceData:
    """One currency, one retailer, one company and three products, distinct GLNs on the two
    parties (a buyer GLN read from the supplier column would not go unnoticed)."""
    data = ReferenceData(
        retailer_code="RET-01",
        company_code="CMP-01",
        buyer_gln="4012345000009",
        supplier_gln="5412345000006",
        currency="EUR",
        product_codes=("SKU-A", "SKU-B", "SKU-C"),
    )
    currency_id = uuid.uuid4()
    conn = await asyncpg.connect(migrated_db.dsn)
    try:
        await conn.execute(
            "INSERT INTO currencies VALUES ($1, 'EUR', '978', 'E', 2, $2, $2)", currency_id, NOW
        )
        for table, code, gln in (
            ("retailers", data.retailer_code, data.buyer_gln),
            ("companies", data.company_code, data.supplier_gln),
        ):
            await conn.execute(
                f"INSERT INTO {table} VALUES "  # noqa: S608
                "($1, $2, 'name', 'ES', 'VAT', $3, $4, NULL, $5, $5)",
                uuid.uuid4(),
                code,
                gln,
                currency_id,
                NOW,
            )
        for index, code in enumerate(data.product_codes):
            await conn.execute(
                "INSERT INTO products VALUES ($1, $2, $3, 'p', 'd', 100, $4, NULL, $5, $5)",
                uuid.uuid4(),
                code,
                f"54000000001{index:02d}"[:13],
                currency_id,
                NOW,
            )
    finally:
        await conn.close()
    return data


@pytest.fixture
def clock() -> SystemClock:
    return SystemClock()


@pytest.fixture
def uow(sessions: async_sessionmaker[AsyncSession], clock: SystemClock) -> SqlAlchemyUnitOfWork:
    return SqlAlchemyUnitOfWork(sessions=sessions, outbox=OutboxWriter(clock=clock))


PlaceOrder = Callable[..., Order]


@pytest.fixture
def place_order(reference_data: ReferenceData) -> PlaceOrder:
    """`place_order(...)`: a placed EUR order over the reference rows, two lines that differ in
    product, quantity, price and discount, with non-round totals (8465 / 350 / 8115)."""

    def place(
        *,
        lines: Sequence[OrderLineInput] | None = None,
        notes: str | None = None,
        occurred_at: datetime | None = None,
        order_date: datetime | None = None,
        causation_id: UniqueId | None = None,
        order_reference: str = "ORD-000001",
    ) -> Order:
        default_lines = (
            OrderLineInput(
                product_code=reference_data.product_codes[0],
                description="Alpha pallet",
                quantity=Quantity(3),
                unit_price=Money(1999, "EUR"),
                line_discount=Money(250, "EUR"),
            ),
            OrderLineInput(
                product_code=reference_data.product_codes[1],
                description=None,
                quantity=Quantity(2),
                unit_price=Money(1234, "EUR"),
                line_discount=Money(100, "EUR"),
            ),
        )
        return Order.place(
            order_reference=OrderNumber(order_reference),
            order_date=order_date if order_date is not None else NOW,
            retailer_code=reference_data.retailer_code,
            buyer_gln=GLN(reference_data.buyer_gln),
            company_code=reference_data.company_code,
            supplier_gln=GLN(reference_data.supplier_gln),
            currency="EUR",
            lines=default_lines if lines is None else lines,
            notes=notes,
            occurred_at=occurred_at if occurred_at is not None else NOW,
            causation_id=causation_id if causation_id is not None else UniqueId.new(),
        )

    return place


# ------------------------------------------------------------- feature 14: relay, broker, planting


class KafkaServerShape(Protocol):
    """The shape of the root conftest's `KafkaServer` (not imported: see `FreshDatabase`)."""

    @property
    def bootstrap_servers(self) -> str: ...


@pytest_asyncio.fixture(loop_scope="function")
async def kafka_publisher(kafka_server: KafkaServerShape) -> AsyncIterator[KafkaFactPublisher]:
    """The production publisher, started in the test's own loop and stopped in it (L23)."""
    settings = KafkaSettings.model_validate(
        {"KAFKA_BROKERS": kafka_server.bootstrap_servers, "KAFKA_CLIENT_ID": "otc-orders-tests"}
    )
    publisher = KafkaFactPublisher(settings)
    await publisher.start()
    try:
        yield publisher
    finally:
        await publisher.stop()


@dataclass(frozen=True)
class ConsumedRecord:
    partition: int
    offset: int
    key: bytes | None
    value: bytes
    headers: tuple[tuple[str, bytes], ...]

    @property
    def event_id(self) -> uuid.UUID | None:
        try:
            parsed = json.loads(self.value)
            return uuid.UUID(parsed["eventId"])
        except ValueError, KeyError, TypeError:
            return None


ReadTopic = Callable[[], Awaitable[list[ConsumedRecord]]]


async def _partitions_of_orders_facts(bootstrap_servers: str) -> list[int]:
    """The partition ids the BROKER reports for the topic (its metadata, not a constant)."""
    admin = AIOKafkaAdminClient(bootstrap_servers=bootstrap_servers)
    await admin.start()
    try:
        described: list[dict[str, Any]] = await admin.describe_topics([ORDERS_FACTS_TOPIC])
    finally:
        await admin.close()
    return sorted(int(partition["partition"]) for partition in described[0]["partitions"])


@pytest.fixture
def read_topic(kafka_server: KafkaServerShape) -> ReadTopic:
    """`await read_topic()`: every record on `otc.orders.facts.v1` up to its end offsets as they
    are when the call starts, read from the broker (never inferred from a stamped row). Tests
    SELECT their own records by content (their event ids): the topic is shared by the session.
    Explicit partition assignment, no consumer group; the consumer lives and dies in the loop of
    the test that awaits it."""

    async def read() -> list[ConsumedRecord]:
        consumer = AIOKafkaConsumer(
            bootstrap_servers=kafka_server.bootstrap_servers,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
        )
        await consumer.start()
        found: list[ConsumedRecord] = []
        try:
            assigned = [
                TopicPartition(ORDERS_FACTS_TOPIC, partition)
                for partition in await _partitions_of_orders_facts(kafka_server.bootstrap_servers)
            ]
            consumer.assign(assigned)
            await consumer.seek_to_beginning(*assigned)
            ends: dict[Any, int] = await consumer.end_offsets(assigned)
            deadline = asyncio.get_running_loop().time() + 30
            while any([await consumer.position(tp) < ends[tp] for tp in assigned]):
                if asyncio.get_running_loop().time() > deadline:
                    raise TimeoutError("the topic could not be read to its end offsets")
                batches = await consumer.getmany(timeout_ms=500)
                for tp, records in batches.items():
                    for record in records:
                        found.append(
                            ConsumedRecord(
                                partition=tp.partition,
                                offset=record.offset,
                                key=record.key,
                                value=record.value,
                                headers=tuple((name, bytes(raw)) for name, raw in record.headers),
                            )
                        )
        finally:
            # aiokafka 0.14.0 (measured): `stop()` cancels a coordinator task that has not taken
            # its first step yet and then awaits it, which raises CancelledError out of `stop()`.
            # One loop tick lets the task start; nothing here depends on the length of the wait.
            await asyncio.sleep(0.05)
            await consumer.stop()
        return found

    return read


RelayFactory = Callable[..., OutboxRelay]


@pytest.fixture
def make_relay(sessions: async_sessionmaker[AsyncSession], clock: SystemClock) -> RelayFactory:
    """`make_relay(publisher, batch_size=100, publish_timeout=5.0, sessions=...)`: the PRODUCTION
    relay (never a re-implementation of its claim: #8's first OI13 draft did that)."""

    def make(
        publisher: FactPublisher,
        *,
        batch_size: int = 100,
        publish_timeout: float = 5.0,
        sessions_override: async_sessionmaker[AsyncSession] | None = None,
    ) -> OutboxRelay:
        return OutboxRelay(
            sessions=sessions_override if sessions_override is not None else sessions,
            publisher=publisher,
            clock=clock,
            batch_size=batch_size,
            publish_timeout=publish_timeout,
        )

    return make


GOLDEN_PLACED_PAYLOAD = (
    '{"lines":[{"quantity":6,"unitPrice":1489,"description":"5L concentrated liquid laundry '
    'detergent","productCode":"PRD-0008","lineDiscount":0}],"buyerGln":"5400000000034",'
    '"currency":"EUR","orderDate":"2026-08-30T16:20:20.442Z","companyCode":"PORTOTOOLS",'
    '"supplierGln":"5400000000386","totalAmount":8934,"retailerCode":"LeroyMerlinEs",'
    '"initialAmount":8934,"orderReference":"ORD-000011","initialDiscount":0}'
)


@dataclass(frozen=True)
class PlantedRow:
    id: uuid.UUID
    event_id: uuid.UUID
    correlation_id: uuid.UUID
    seq: int


class RowPlanter:
    """Inserts an outbox row by RAW SQL (no writer, no ORM), the way a poison payload or an
    out-of-order `occurred_at` can only be planted. `seq` comes from the identity, in insert
    order."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    async def plant(
        self,
        *,
        payload: str = GOLDEN_PLACED_PAYLOAD,
        event_type: str = "order.placed.v1",
        occurred_at: datetime = NOW,
        event_id: uuid.UUID | None = None,
        correlation_id: uuid.UUID | None = None,
        aggregate_id: uuid.UUID | None = None,
        causation_id: uuid.UUID | None = None,
        connection: asyncpg.Connection[Any] | None = None,
    ) -> PlantedRow:
        row_id, event, correlation = (
            uuid.uuid4(),
            event_id or uuid.uuid4(),
            correlation_id or uuid.uuid4(),
        )
        owned = connection is None
        conn = connection if connection is not None else await asyncpg.connect(self._dsn)
        try:
            seq: int = await conn.fetchval(
                "INSERT INTO outbox (id, event_id, event_type, aggregate_id, correlation_id, "
                "causation_id, payload, occurred_at, published_at, created_at, trace_parent) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7::json, $8, NULL, $8, NULL) RETURNING seq",
                row_id,
                event,
                event_type,
                aggregate_id or correlation,
                correlation,
                causation_id or uuid.uuid4(),
                payload,
                occurred_at,
            )
        finally:
            if owned:
                await conn.close()
        return PlantedRow(id=row_id, event_id=event, correlation_id=correlation, seq=seq)


@pytest.fixture
def row_planter(migrated_db: FreshDatabase) -> RowPlanter:
    return RowPlanter(migrated_db.dsn)


# --------------------- feature 15: NATS, the stand-in Fulfillment, the host

NATS_IMAGE = "nats:2.14.5-alpine"  # the compose pin (docker-compose.infra.yml)


@dataclass(frozen=True)
class NatsServer:
    url: str  # nats://host:port, the port assigned and held by Docker


@pytest.fixture(scope="session")
def nats_server() -> Iterator[NatsServer]:
    """ONE Docker-held NATS (core only, no JetStream: the deployed server's shape) per session.

    Sync, no loop: every client a test needs is created and closed in that test's own loop. The
    port is Docker's; the suite never talks to the composed NATS on 4222. It lives in this
    conftest, not the repository root one, because feature 15 is the first user and its brief
    bounds the files it may touch; the next service that needs it moves it up.
    """
    container = NatsContainer(NATS_IMAGE)
    with warnings.catch_warnings():
        # testcontainers 4.15.0's own `NatsContainer.start()` readiness wait calls its deprecated
        # `wait_for_logs(<str>)` (measured: DeprecationWarning from
        # testcontainers/core/waiting_utils.py, under `error::DeprecationWarning`). It is the
        # library's warning, not ours: ignored for exactly this message, exactly around `start()`.
        warnings.filterwarnings(
            "ignore",
            message="The wait_for_logs function with string or callable predicates is deprecated",
            category=DeprecationWarning,
        )
        container.start()
    try:
        yield NatsServer(url=container.nats_uri())
    finally:
        container.stop()


@pytest_asyncio.fixture(loop_scope="function")
async def nats_client(nats_server: NatsServer) -> AsyncIterator[NatsClient]:
    """A caller's connection (what the Gateway is to `orders.create`), closed in this loop."""
    client = await nats.connect(nats_server.url)
    try:
        yield client
    finally:
        await client.close()


Behaviour = Callable[[dict[str, Any]], bytes | None]


class StandInStockCheck:
    """A Fulfillment stand-in on `fulfillment.stock.check`: records every request it receives (as
    parsed JSON) and answers with `behaviour(request)`; `None` is silence (a subscribed responder
    that never replies)."""

    def __init__(self, client: NatsClient, behaviour: Behaviour) -> None:
        self._client = client
        self._behaviour = behaviour
        self.requests: list[dict[str, Any]] = []

    async def start(self) -> None:
        await self._client.subscribe("fulfillment.stock.check", cb=self._on_request)

    async def _on_request(self, message: NatsMsg) -> None:
        request = json.loads(message.data)
        self.requests.append(request)
        reply = self._behaviour(request)
        if reply is not None:
            await message.respond(reply)


StandInFactory = Callable[[Behaviour], Awaitable[StandInStockCheck]]


@pytest_asyncio.fixture(loop_scope="function")
async def stand_in_stock_check(nats_server: NatsServer) -> AsyncIterator[StandInFactory]:
    """`await stand_in_stock_check(behaviour)`: started on its own connection, closed with the
    test (so no subscription outlives the test that made it on the shared server)."""

    async with AsyncExitStack() as stack:

        async def make(behaviour: Behaviour) -> StandInStockCheck:
            client = await nats.connect(nats_server.url)
            # registered at once: a failure below, or in a sibling's close, cannot leak it
            stack.push_async_callback(client.close)
            stand_in = StandInStockCheck(client, behaviour)
            await stand_in.start()
            await client.flush()
            return stand_in

        yield make


StockReply = Callable[[Sequence[tuple[str, int, int]]], bytes]


@pytest.fixture
def stock_reply() -> StockReply:
    """`stock_reply([(productCode, requested, available), ...])`: a success reply whose overall
    `available` is true when every line is sufficient (a test module cannot import this helper
    by name under `--import-mode=importlib`, so it is a fixture)."""

    def build(lines: Sequence[tuple[str, int, int]]) -> bytes:
        body = [
            {
                "productCode": code,
                "requested": requested,
                "available": available,
                "sufficient": available >= requested,
            }
            for code, requested, available in lines
        ]
        return json.dumps(
            {"available": all(line["sufficient"] for line in body), "lines": body}
        ).encode()

    return build


@dataclass(frozen=True)
class OrdersHost:
    """A started Orders host: the app the real lifespan started, its runtime, and where to send."""

    app: FastAPI
    runtime: OrdersRuntime
    client: NatsClient


HostEnv = Callable[..., None]
HostFactory = Callable[..., AbstractAsyncContextManager[OrdersHost]]


@pytest.fixture
def host_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    migrated_db: FreshDatabase,
    nats_server: NatsServer,
    kafka_server: KafkaServerShape,
) -> HostEnv:
    """`host_environment(**overrides)`: the environment a real deployment would carry, set through
    the process environment (the only way the host reads it). The working directory is an empty
    directory, so a developer's `.env` can never supply a value. Every variable the composition
    root reads is set here, so a developer shell's value never leaks in either."""

    def apply(**overrides: str) -> None:
        monkeypatch.chdir(tmp_path)
        values = {
            "ORDERS_DATABASE_URL": migrated_db.url,
            "NATS_URL": nats_server.url,
            "STOCK_CHECK_TIMEOUT_MS": "1500",
            "KAFKA_BROKERS": kafka_server.bootstrap_servers,
            "KAFKA_CLIENT_ID": "otc-orders-tests",
            "OUTBOX_RELAY_ENABLED": "true",
            "OUTBOX_POLL_INTERVAL_MS": "50",
            "OUTBOX_BATCH_SIZE": "100",
            "OUTBOX_PUBLISH_TIMEOUT_MS": "5000",
            "WEB_CONCURRENCY": "1",
            # Feature 16: the saga's consumer is off unless a test (the saga harness) turns it on,
            # so feature 15's host tests keep booting without a consumer group on the broker.
            "SAGA_CONSUMER_ENABLED": "false",
        } | overrides
        for name, value in values.items():
            monkeypatch.setenv(name, value)
        for name in (
            "POSTGRES_APP_PASSWORD",
            "POSTGRES_APP_USER",
            "POSTGRES_DB_ORDERS",
            "POSTGRES_HOST",
            "POSTGRES_HOST_PORT",
        ):
            monkeypatch.delenv(name, raising=False)

    return apply


@pytest_asyncio.fixture(loop_scope="function")
async def orders_host_factory(host_environment: HostEnv, nats_client: NatsClient) -> HostFactory:
    """`async with orders_host_factory(OUTBOX_RELAY_ENABLED="false") as host:` drives the REAL
    `otc_orders.main.create_app()` lifespan (no argument, no injected configuration), in the test's
    loop, and stops it on exit."""

    @asynccontextmanager
    async def start(**overrides: str) -> AsyncIterator[OrdersHost]:
        host_environment(**overrides)
        app = create_app()
        async with app.router.lifespan_context(app):
            yield OrdersHost(app=app, runtime=app.state.runtime, client=nats_client)

    return start


@pytest_asyncio.fixture(loop_scope="function")
async def orders_host(
    orders_host_factory: HostFactory, reference_data: ReferenceData
) -> AsyncIterator[OrdersHost]:
    """The host over a database holding `reference_data`, relay on, stock-check budget 1.5 s."""
    async with orders_host_factory() as host:
        yield host
