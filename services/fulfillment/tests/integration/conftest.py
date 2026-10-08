"""Fulfillment integration fixtures: an Alembic runner and a migrated database per test.

The shared container and `fresh_database` live in the repository-root `conftest.py`.
"""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import asyncpg
import nats
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from nats.aio.client import Client as NatsClient
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from otc_fulfillment.composition import FulfillmentRuntime
from otc_fulfillment.main import create_app


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
    return await migrated_database_from_template("fulfillment")


@pytest_asyncio.fixture(loop_scope="function")
async def engine(migrated_db: FreshDatabase) -> AsyncIterator[AsyncEngine]:
    # Function loop; created and disposed here, in the loop that uses it.
    eng = create_async_engine(migrated_db.url)
    try:
        yield eng
    finally:
        await eng.dispose()


# ----------------------------------------------------------- feature 17: NATS, the host, the data


class NatsServerShape(Protocol):
    """The shape of the root conftest's `NatsServer` (not imported: see `FreshDatabase`)."""

    @property
    def url(self) -> str: ...


class KafkaServerShape(Protocol):
    """The shape of the root conftest's `KafkaServer` (not imported: see `FreshDatabase`)."""

    @property
    def bootstrap_servers(self) -> str: ...


@pytest_asyncio.fixture(loop_scope="function")
async def nats_client(nats_server: NatsServerShape) -> AsyncIterator[NatsClient]:
    """A caller's connection (what Orders and the Gateway are to Fulfillment), closed in this
    loop. Every subscriber a test makes is closed with that test, so the shared server never
    carries a stale `fulfillment.stock.*` subscriber into another test."""
    client = await nats.connect(nats_server.url)
    try:
        yield client
    finally:
        await client.close()


@dataclass(frozen=True)
class FulfillmentHost:
    """A started Fulfillment host: the app the real lifespan started, its runtime, a caller."""

    app: FastAPI
    runtime: FulfillmentRuntime
    client: NatsClient


HostEnv = Callable[..., None]
HostFactory = Callable[..., AbstractAsyncContextManager[FulfillmentHost]]


@pytest.fixture
def host_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    migrated_db: FreshDatabase,
    nats_server: NatsServerShape,
    kafka_server: KafkaServerShape,
) -> HostEnv:
    """`host_environment(**overrides)`: the environment a real deployment would carry, set through
    the process environment (the only way the host reads it). The working directory is an empty
    directory, so a developer's `.env` can never supply a value, and every variable the composition
    root reads is set here, so a developer shell's value never leaks in either.

    The relay is DISABLED unless a test asks (`OUTBOX_RELAY_ENABLED="true"`): then the Docker-held
    Kafka's address is used. With the relay off, `KAFKA_BROKERS` points at a port nothing listens
    on, so Kafka being contacted would fail the boot. `kafka_server` is a plain sync session
    fixture (it runs its own `asyncio.run`), so it must be requested here, before any loop runs;
    the container is started once per session, by the first test that needs a host."""

    def apply(**overrides: str) -> None:
        monkeypatch.chdir(tmp_path)
        values = {
            "FULFILLMENT_DATABASE_URL": migrated_db.url,
            "NATS_URL": nats_server.url,
            "KAFKA_BROKERS": "127.0.0.1:1",
            "FULFILLMENT_KAFKA_CLIENT_ID": "otc-fulfillment-tests",
            "OUTBOX_RELAY_ENABLED": "false",
            "OUTBOX_POLL_INTERVAL_MS": "50",
            "OUTBOX_BATCH_SIZE": "100",
            "OUTBOX_PUBLISH_TIMEOUT_MS": "5000",
            "WEB_CONCURRENCY": "1",
            "FULFILLMENT_MAX_CONCURRENT_REQUESTS": "8",
        }
        if overrides.get("OUTBOX_RELAY_ENABLED") == "true" and "KAFKA_BROKERS" not in overrides:
            values["KAFKA_BROKERS"] = kafka_server.bootstrap_servers
        values |= overrides
        for name, value in values.items():
            monkeypatch.setenv(name, value)
        for name in (
            "POSTGRES_APP_PASSWORD",
            "POSTGRES_APP_USER",
            "POSTGRES_DB_FULFILLMENT",
            "POSTGRES_HOST",
            "POSTGRES_HOST_PORT",
        ):
            monkeypatch.delenv(name, raising=False)

    return apply


@pytest_asyncio.fixture(loop_scope="function")
async def fulfillment_host_factory(
    host_environment: HostEnv, nats_client: NatsClient
) -> HostFactory:
    """`async with fulfillment_host_factory(OUTBOX_RELAY_ENABLED="true") as host:` drives the REAL
    `otc_fulfillment.main.create_app()` lifespan (no argument, no injected configuration), in the
    test's loop, and stops it on exit: every engine and client it opened is closed in this loop."""

    @asynccontextmanager
    async def start(**overrides: str) -> AsyncIterator[FulfillmentHost]:
        host_environment(**overrides)
        app = create_app()
        async with app.router.lifespan_context(app):
            yield FulfillmentHost(app=app, runtime=app.state.runtime, client=nats_client)

    return start


@pytest_asyncio.fixture(loop_scope="function")
async def fulfillment_host(fulfillment_host_factory: HostFactory) -> AsyncIterator[FulfillmentHost]:
    """The host over the migrated, empty database, relay off."""
    async with fulfillment_host_factory() as host:
        yield host


class RowHold:
    """A test transaction holding `SELECT ... FOR UPDATE` on stock rows (the constructed races)."""

    def __init__(self, connection: asyncpg.Connection, transaction: Any) -> None:
        self._connection = connection
        self._transaction = transaction
        self._open = True

    async def execute(self, sql: str, *args: object) -> None:
        await self._connection.execute(sql, *args)

    async def fetch(self, sql: str, *args: object) -> list[asyncpg.Record]:
        return list(await self._connection.fetch(sql, *args))

    async def commit(self) -> None:
        if self._open:
            self._open = False
            await self._transaction.commit()
            await self._connection.close()

    async def rollback(self) -> None:
        if self._open:
            self._open = False
            await self._transaction.rollback()
            await self._connection.close()


class Db:
    """Direct SQL against the test database, for seeding and for reading rows back. Each call
    opens and closes its own connection in the calling test's loop."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    async def fetch(self, sql: str, *args: object) -> list[asyncpg.Record]:
        connection = await asyncpg.connect(self._dsn)
        try:
            return list(await connection.fetch(sql, *args))
        finally:
            await connection.close()

    async def execute(self, sql: str, *args: object) -> None:
        connection = await asyncpg.connect(self._dsn)
        try:
            await connection.execute(sql, *args)
        finally:
            await connection.close()

    async def hold(self, keys: Sequence[tuple[str, str]]) -> RowHold:
        """Open a transaction that holds `FOR UPDATE` on the stock rows of `keys`, in the order
        given. The caller commits or rolls it back (always, in a `finally`)."""
        connection = await asyncpg.connect(self._dsn)
        transaction = connection.transaction()
        await transaction.start()
        for company_code, product_code in keys:
            await connection.fetch(
                "SELECT id FROM stock WHERE company_code = $1 AND product_code = $2 FOR UPDATE",
                company_code,
                product_code,
            )
        return RowHold(connection, transaction)

    async def lock_waiters(self, query_like: str) -> int:
        """How many backends of THIS database are waiting on a lock with a query matching the
        pattern (`pg_stat_activity.wait_event_type = 'Lock'`): a request seen UNGRANTED."""
        [row] = await self.fetch(
            "SELECT count(*) AS n FROM pg_stat_activity WHERE datname = current_database()"
            " AND wait_event_type = 'Lock' AND query LIKE $1",
            query_like,
        )
        return int(row["n"])

    async def wait_for_lock_waiters(
        self, query_like: str, count: int, *, deadline_seconds: float = 15.0
    ) -> None:
        """Wait until `count` backends wait on a lock with a matching query: a TERMINAL condition
        (a lock request is observed ungranted), never a sleep standing in for one. The poll is paced
        at 20 ms and bounded."""
        async with asyncio.timeout(deadline_seconds):
            while await self.lock_waiters(query_like) < count:  # noqa: ASYNC110 - polls a DB state
                await asyncio.sleep(0.02)

    async def seed_stock(
        self, company_code: str, rows: Sequence[tuple[str, int, int, int]]
    ) -> dict[str, uuid.UUID]:
        """`(product_code, units, reserved_units, low_stock_threshold)` -> product -> stock id."""
        ids: dict[str, uuid.UUID] = {}
        now = datetime.now(UTC)
        for product_code, units, reserved, threshold in rows:
            ids[product_code] = uuid.uuid4()
            await self.execute(
                "INSERT INTO stock (id, company_code, product_code, units, reserved_units,"
                " low_stock_threshold, created_at, updated_at)"
                " VALUES ($1, $2, $3, $4, $5, $6, $7, $7)",
                ids[product_code],
                company_code,
                product_code,
                units,
                reserved,
                threshold,
                now,
            )
        return ids

    async def stock(self, company_code: str, product_code: str) -> asyncpg.Record:
        [row] = await self.fetch(
            "SELECT * FROM stock WHERE company_code = $1 AND product_code = $2",
            company_code,
            product_code,
        )
        return row

    async def reservations(self, order_reference: str) -> list[asyncpg.Record]:
        return await self.fetch(
            "SELECT * FROM reservations WHERE order_reference = $1 ORDER BY created_at, id",
            order_reference,
        )

    async def outbox(self) -> list[dict[str, Any]]:
        """Every outbox row in `seq` order, the payload parsed from its stored text."""
        rows = await self.fetch(
            "SELECT id, event_id, event_type, aggregate_id, correlation_id, causation_id,"
            " payload::text AS payload, occurred_at, published_at, seq FROM outbox ORDER BY seq"
        )
        return [{**dict(r), "payload": json.loads(r["payload"])} for r in rows]


@pytest.fixture
def db(migrated_db: FreshDatabase) -> Db:
    return Db(migrated_db.dsn)


RpcCall = Callable[..., Awaitable[dict[str, Any]]]


@pytest.fixture
def rpc(nats_client: NatsClient) -> RpcCall:
    """`await rpc("fulfillment.stock.check", {...}, headers={...})` -> the reply, parsed JSON."""

    async def call(
        subject: str,
        body: dict[str, Any] | bytes,
        *,
        headers: dict[str, str] | None = None,
        timeout: float = 15,  # noqa: ASYNC109 - nats-py's own request parameter
    ) -> dict[str, Any]:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        reply = await nats_client.request(subject, data, timeout=timeout, headers=headers)
        parsed: dict[str, Any] = json.loads(reply.data)
        return parsed

    return call
