"""Gateway integration fixtures: a seeded stack of REAL hosts, the read model and the Gateway.

What is real: PostgreSQL (the three services' migrated templates, loaded by the REAL seed), MongoDB,
NATS, the Orders, Fulfillment and Billing hosts (their own `main.create_app()` lifespans, in this
test's loop, relays and the saga consumer off so no Kafka is needed), and the Gateway host
(`otc_gateway.main.create_app()`). Nothing the Gateway talks to is a stub: the seam that #7's first
gateway rejection was about (`docs/lessons.md:123`, a stub that shares the Gateway's assumption of
the wire) cannot hide here.

Loop scope: every async fixture is `loop_scope="function"` (written next to it); the hosts, the
clients and the engines are created in the test's own loop and closed in it, in reverse order.
The container servers and the migrated templates are the repository-root conftest's.
"""

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import asyncpg
import httpx
import nats
import pytest
import pytest_asyncio
from nats.aio.client import Client as NatsClient

from otc_seed.application import run_seed
from otc_seed.composition import build_runtime
from otc_seed.infrastructure.settings import SeedSettings

OPERATOR_PASSWORD = "integration-operator-password"
JWT_SECRET = "integration-jwt-secret-0123456789abcdef-0123456789"


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


@dataclass(frozen=True)
class SeededDatabases:
    orders: FreshDatabase
    fulfillment: FreshDatabase
    billing: FreshDatabase
    mongo: FreshMongoDatabase


@pytest_asyncio.fixture(loop_scope="function")
async def seeded(
    migrated_database_from_template: Callable[[str], Awaitable[FreshDatabase]],
    fresh_mongo_database: FreshMongoDatabase,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> SeededDatabases:
    """Private, migrated copies of the three databases and an unused MongoDB database, loaded by the
    REAL seed (6 sagas: 5 completed, 1 cancelled; 154 credit lines; 215 stock rows)."""
    databases = SeededDatabases(
        orders=await migrated_database_from_template("orders"),
        fulfillment=await migrated_database_from_template("fulfillment"),
        billing=await migrated_database_from_template("billing"),
        mongo=fresh_mongo_database,
    )
    monkeypatch.chdir(tmp_path)  # no developer `.env` can reach a settings class
    for name, value in {
        "ORDERS_DATABASE_URL": databases.orders.url,
        "FULFILLMENT_DATABASE_URL": databases.fulfillment.url,
        "BILLING_DATABASE_URL": databases.billing.url,
        "MONGO_URI": databases.mongo.uri,
        "MONGO_DB_READMODEL": databases.mongo.name,
    }.items():
        monkeypatch.setenv(name, value)
    runtime = build_runtime(SeedSettings(_env_file=None))  # type: ignore[call-arg]
    try:
        await run_seed(runtime.targets)
    finally:
        await runtime.aclose()
    return databases


@dataclass
class Stack:
    http: httpx.AsyncClient  # the Gateway, in-process ASGI
    nats: NatsClient  # a caller of the responders directly (to compare, never to replace)
    databases: SeededDatabases
    gateway_app: Any
    token: str

    @property
    def auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    async def rows(self, database: str, sql: str, *args: Any) -> list[asyncpg.Record]:
        dsn = getattr(self.databases, database).dsn
        connection = await asyncpg.connect(dsn)
        try:
            return await connection.fetch(sql, *args)
        finally:
            await connection.close()

    async def ask(self, subject: str, body: dict[str, Any], headers: dict[str, str]) -> Any:
        reply = await self.nats.request(
            subject, json.dumps(body).encode(), timeout=5, headers=headers
        )
        return json.loads(reply.data)


@pytest_asyncio.fixture(loop_scope="function")
async def stack(
    seeded: SeededDatabases,
    nats_server: NatsServerShape,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[Stack]:
    from otc_billing.main import create_app as create_billing
    from otc_fulfillment.main import create_app as create_fulfillment
    from otc_gateway.main import create_app as create_gateway
    from otc_orders.main import create_app as create_orders

    def environment(**values: str) -> None:
        for name, value in values.items():
            monkeypatch.setenv(name, value)

    common = {
        "NATS_URL": nats_server.url,
        "KAFKA_BROKERS": "127.0.0.1:1",  # every relay is off: contacting Kafka would fail the boot
        "OUTBOX_RELAY_ENABLED": "false",
        "WEB_CONCURRENCY": "1",
    }
    async with AsyncExitStack() as hosts:
        environment(
            **common,
            KAFKA_CLIENT_ID="otc-orders-gateway-tests",
            STOCK_CHECK_TIMEOUT_MS="3000",
            SAGA_CONSUMER_ENABLED="false",
            SAGA_SWEEPER_ENABLED="false",
        )
        orders = create_orders()
        await hosts.enter_async_context(orders.router.lifespan_context(orders))
        environment(
            **common,
            FULFILLMENT_KAFKA_CLIENT_ID="otc-fulfillment-gateway-tests",
            FULFILLMENT_MAX_CONCURRENT_REQUESTS="8",
        )
        fulfillment = create_fulfillment()
        await hosts.enter_async_context(fulfillment.router.lifespan_context(fulfillment))
        environment(
            **common,
            BILLING_KAFKA_CLIENT_ID="otc-billing-gateway-tests",
            BILLING_MAX_CONCURRENT_REQUESTS="8",
            CREDIT_FAILURE_RATE="0",
        )
        billing = create_billing()
        await hosts.enter_async_context(billing.router.lifespan_context(billing))
        environment(
            NATS_URL=nats_server.url,
            JWT_SECRET=JWT_SECRET,
            GATEWAY_OPERATOR_PASSWORD=OPERATOR_PASSWORD,
            GATEWAY_RPC_TIMEOUT_MS="5000",
        )
        gateway = create_gateway()
        await hosts.enter_async_context(gateway.router.lifespan_context(gateway))
        caller = await nats.connect(nats_server.url)
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=gateway), base_url="http://gateway.test"
            ) as client:
                login = await client.post(
                    "/auth/login", json={"username": "operator", "password": OPERATOR_PASSWORD}
                )
                assert login.status_code == 200, login.text
                yield Stack(
                    http=client,
                    nats=caller,
                    databases=seeded,
                    gateway_app=gateway,
                    token=login.json()["accessToken"],
                )
        finally:
            await caller.close()


# ------------------------------------------------------------------------------ a read model only


def _saga_facts(saga: Any) -> list[Any]:
    from otc_contracts import format_instant, parse_fact

    facts = []
    for row in (*saga.orders_outbox, *saga.fulfillment_outbox, *saga.billing_outbox):
        facts.append(
            parse_fact(
                json.dumps(
                    {
                        "eventId": row.event_id,
                        "eventType": row.event_type,
                        "aggregateId": row.aggregate_id,
                        "correlationId": row.correlation_id,
                        "causationId": row.causation_id,
                        "occurredAt": format_instant(row.occurred_at),
                        "payload": dict(row.payload),
                    }
                )
            )
        )
    return facts


@pytest_asyncio.fixture(loop_scope="function")
async def projected_sagas(fresh_mongo_database: FreshMongoDatabase) -> FreshMongoDatabase:
    """The six seeded sagas' facts projected by the REAL projector writer into a fresh MongoDB
    database: a read model and nothing else (no PostgreSQL, no Kafka, no responder exists)."""
    from pymongo import AsyncMongoClient

    from otc_projector.application.projection import project
    from otc_projector.infrastructure.messaging.idempotent_consumer import IdempotentConsumer
    from otc_projector.infrastructure.persistence.mongo_read_model_writer import (
        MongoReadModelWriter,
    )
    from otc_projector.infrastructure.persistence.read_model_document import COLLECTION
    from otc_projector.infrastructure.persistence.read_model_indexes import ensure_indexes
    from otc_seed.domain.data.sagas import SAGAS

    async def no_signal(applied: Any) -> None:
        return None

    client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(fresh_mongo_database.uri)
    try:
        collection = client.get_database(fresh_mongo_database.name).get_collection(COLLECTION)
        await ensure_indexes(collection)
        writer = MongoReadModelWriter(collection, IdempotentConsumer(collection))
        for saga in SAGAS:
            for fact in _saga_facts(saga):
                await writer.apply(project(fact), after_applied=no_signal)
    finally:
        await client.close()
    return fresh_mongo_database
