"""Billing integration fixtures: an Alembic runner and a migrated database per test.

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
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from otc_billing.application.ports.credit_decision import CreditDecisionPort
from otc_billing.composition import BillingRuntime, load_settings, start_runtime
from otc_billing.infrastructure.clock import SystemClock
from otc_billing.infrastructure.outbox.writer import OutboxWriter
from otc_billing.infrastructure.persistence.credit_transactions import (
    SqlAlchemyCreditTransactions,
)
from otc_billing.main import create_app as create_real_app
from otc_billing.presentation.app import create_app as create_routes
from otc_contracts import from_wire_json
from otc_contracts.generated import asyncapi


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
    return await migrated_database_from_template("billing")


@pytest_asyncio.fixture(loop_scope="function")
async def engine(migrated_db: FreshDatabase) -> AsyncIterator[AsyncEngine]:
    # Function loop; created and disposed here, in the loop that uses it.
    eng = create_async_engine(migrated_db.url)
    try:
        yield eng
    finally:
        await eng.dispose()


# ------------------------------------------------------------------ feature 19: SQL, locks, rows


class RowHold:
    """A test transaction holding `SELECT ... FOR UPDATE` on a credit line (races)."""

    def __init__(self, connection: asyncpg.Connection, transaction: Any) -> None:
        self._connection = connection
        self._transaction = transaction
        self._open = True

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

    async def hold(self, retailer_code: str, company_code: str) -> RowHold:
        """Open a transaction holding `FOR UPDATE` on the credit line. The caller commits or rolls
        it back (always, in a `finally`)."""
        connection = await asyncpg.connect(self._dsn)
        transaction = connection.transaction()
        await transaction.start()
        await connection.fetch(
            "SELECT id FROM credits WHERE retailer_code = $1 AND company_code = $2 FOR UPDATE",
            retailer_code,
            company_code,
        )
        return RowHold(connection, transaction)

    async def hold_counter(self) -> RowHold:
        """Open a transaction holding `FOR UPDATE` on the invoice counter row (races)."""
        connection = await asyncpg.connect(self._dsn)
        transaction = connection.transaction()
        await transaction.start()
        await connection.fetch("SELECT id FROM invoice_number_sequences WHERE id = 1 FOR UPDATE")
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
        try:
            async with asyncio.timeout(deadline_seconds):
                while await self.lock_waiters(query_like) < count:  # noqa: ASYNC110 - polls a DB
                    await asyncio.sleep(0.02)
        except TimeoutError:
            seen = await self.lock_waiters(query_like)
            raise AssertionError(
                f"expected {count} backend(s) waiting on a lock (query LIKE {query_like!r}), "
                f"saw {seen} after {deadline_seconds} s: the request never waited on the line lock"
            ) from None

    async def seed_line(
        self,
        retailer_code: str,
        company_code: str,
        *,
        limit: int,
        code: str,
        currency: str = "EUR",
    ) -> uuid.UUID:
        credit_id = uuid.uuid4()
        now = datetime.now(UTC)
        await self.execute(
            "INSERT INTO credits (id, code, retailer_code, company_code, credit_limit,"
            " currency_code, created_at, updated_at) VALUES ($1, $2, $3, $4, $5, $6, $7, $7)",
            credit_id,
            code,
            retailer_code,
            company_code,
            limit,
            currency,
            now,
        )
        return credit_id

    async def plant_entry(
        self,
        credit_id: uuid.UUID,
        order_reference: str,
        amount: int,
        entry_type: str,
        *,
        credit_date: datetime | None = None,
    ) -> uuid.UUID:
        """A raw ledger row of ANY type token (a planted `'Hold'` included)."""
        entry_id = uuid.uuid4()
        at = credit_date or datetime.now(UTC)
        await self.execute(
            "INSERT INTO credit_items (id, credit_id, order_reference, amount, type, credit_date,"
            " created_at, updated_at) VALUES ($1, $2, $3, $4, $5, $6, $6, $6)",
            entry_id,
            credit_id,
            order_reference,
            amount,
            entry_type,
            at,
        )
        return entry_id

    async def ledger_of(self, order_reference: str) -> list[asyncpg.Record]:
        return await self.fetch(
            "SELECT * FROM credit_items WHERE order_reference = $1 ORDER BY created_at, id",
            order_reference,
        )

    async def count(self, table: str) -> int:
        [row] = await self.fetch(f"SELECT count(*) AS n FROM {table}")  # noqa: S608 - a literal
        return int(row["n"])

    async def outbox(self) -> list[dict[str, Any]]:
        """Every outbox row in `seq` order, the payload parsed from its stored text."""
        rows = await self.fetch(
            "SELECT id, event_id, event_type, aggregate_id, correlation_id, causation_id,"
            " payload::text AS payload, occurred_at, published_at, seq FROM outbox ORDER BY seq"
        )
        return [{**dict(r), "payload": json.loads(r["payload"])} for r in rows]

    async def outbox_rows_for(self, correlation_id: uuid.UUID) -> list[dict[str, Any]]:
        return [r for r in await self.outbox() if r["correlation_id"] == correlation_id]

    # ------------------------------------------------------------ feature 21: invoices

    async def invoices_of(self, order_reference: str) -> list[asyncpg.Record]:
        return await self.fetch(
            "SELECT * FROM invoices WHERE order_reference = $1", order_reference
        )

    async def invoice_items_of(self, invoice_id: uuid.UUID) -> list[asyncpg.Record]:
        return await self.fetch(
            "SELECT * FROM invoice_items WHERE invoice_id = $1 ORDER BY product_code, id",
            invoice_id,
        )

    async def invoice_counter(self) -> int | None:
        """`invoice_number_sequences.next_value`, or None while the counter row is absent."""
        rows = await self.fetch("SELECT next_value FROM invoice_number_sequences WHERE id = 1")
        return int(rows[0]["next_value"]) if rows else None

    # ------------------------------------------------------------ feature 22: payments

    async def connect(self) -> asyncpg.Connection:
        """A connection of the test's own (a competitor, a probe); the caller closes it."""
        return await asyncpg.connect(self._dsn)

    async def payments_of(self, invoice_id: uuid.UUID) -> list[asyncpg.Record]:
        return await self.fetch(
            "SELECT * FROM payments WHERE invoice_id = $1 ORDER BY created_at, id", invoice_id
        )

    async def invoice_row(self, invoice_id: uuid.UUID) -> asyncpg.Record:
        [row] = await self.fetch("SELECT * FROM invoices WHERE id = $1", invoice_id)
        return row

    async def hold_invoice(self, invoice_id: uuid.UUID) -> RowHold:
        """A test transaction holding `FOR UPDATE` on ONE invoice row (the inversion probe)."""
        connection = await asyncpg.connect(self._dsn)
        transaction = connection.transaction()
        await transaction.start()
        await connection.fetch("SELECT id FROM invoices WHERE id = $1 FOR UPDATE", invoice_id)
        return RowHold(connection, transaction)

    async def seed_invoice(
        self,
        order_reference: str,
        *,
        retailer_code: str,
        company_code: str,
        reference: str,
        lines: Sequence[tuple[str, int, int]],
        discount: int,
        invoice_date: datetime,
        status: str = "issued",
        paid_at: datetime | None = None,
        currency: str = "EUR",
    ) -> uuid.UUID:
        """A stored invoice written by SQL (no port, no aggregate), for the repeat and the list.
        `lines` are `(product_code, units, unit_price)`; `amount` and `total_amount` are DERIVED
        from them so the row satisfies the aggregate's invariants. `status` and `paid_at` are
        written as given: a test may plant a disagreeing pair on purpose."""
        invoice_id = uuid.uuid4()
        amount = sum(units * price for _, units, price in lines)
        await self.execute(
            "INSERT INTO invoices (id, invoice_reference, invoice_date, company_code,"
            " retailer_code, order_reference, amount, discount, total_amount, currency_code,"
            " status, paid_at, created_at, updated_at)"
            " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $3, $3)",
            invoice_id,
            reference,
            invoice_date,
            company_code,
            retailer_code,
            order_reference,
            amount,
            discount,
            amount - discount,
            currency,
            status,
            paid_at,
        )
        for product_code, units, price in lines:
            await self.execute(
                "INSERT INTO invoice_items (id, invoice_id, product_code, units, price,"
                " created_at, updated_at) VALUES ($1, $2, $3, $4, $5, $6, $6)",
                uuid.uuid4(),
                invoice_id,
                product_code,
                units,
                price,
                invoice_date,
            )
        return invoice_id


@pytest.fixture
def db(migrated_db: FreshDatabase) -> Db:
    return Db(migrated_db.dsn)


# ------------------------------------------------ feature 19: NATS, the host, replies


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
    """A caller's connection (what Orders and the Gateway are to Billing), closed in this loop.
    Every subscriber a test makes is closed with that test, so the shared server never carries a
    stale `billing.credit.*` subscriber into another test."""
    client = await nats.connect(nats_server.url)
    try:
        yield client
    finally:
        await client.close()


@dataclass(frozen=True)
class BillingHost:
    """A started Billing host: the app, its runtime, a caller."""

    app: FastAPI
    runtime: BillingRuntime
    client: NatsClient


HostEnv = Callable[..., None]
HostFactory = Callable[..., AbstractAsyncContextManager[BillingHost]]


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
            "BILLING_DATABASE_URL": migrated_db.url,
            "NATS_URL": nats_server.url,
            "KAFKA_BROKERS": "127.0.0.1:1",
            "BILLING_KAFKA_CLIENT_ID": "otc-billing-tests",
            "OUTBOX_RELAY_ENABLED": "false",
            "OUTBOX_POLL_INTERVAL_MS": "50",
            "OUTBOX_BATCH_SIZE": "100",
            "OUTBOX_PUBLISH_TIMEOUT_MS": "5000",
            "WEB_CONCURRENCY": "1",
            "BILLING_MAX_CONCURRENT_REQUESTS": "8",
            "CREDIT_FAILURE_RATE": "0",
        }
        if overrides.get("OUTBOX_RELAY_ENABLED") == "true" and "KAFKA_BROKERS" not in overrides:
            values["KAFKA_BROKERS"] = kafka_server.bootstrap_servers
        values |= overrides
        for name, value in values.items():
            monkeypatch.setenv(name, value)
        for name in (
            "POSTGRES_APP_PASSWORD",
            "POSTGRES_APP_USER",
            "POSTGRES_DB_BILLING",
            "POSTGRES_HOST",
            "POSTGRES_HOST_PORT",
        ):
            monkeypatch.delenv(name, raising=False)

    return apply


@pytest_asyncio.fixture(loop_scope="function")
async def billing_host_factory(host_environment: HostEnv, nats_client: NatsClient) -> HostFactory:
    """`async with billing_host_factory(OUTBOX_RELAY_ENABLED="true") as host:` drives the REAL
    `otc_billing.main.create_app()` lifespan (no argument, no injected configuration), in the
    test's loop, and stops it on exit: every engine and client it opened is closed in this loop.

    `billing_host_factory(credit_decision=port)` boots the real `start_runtime` with that port
    bound instead (#7's D1 was unreachable at integration level because every harness bound the
    approving adapter): the same composition root, one binding different."""

    @asynccontextmanager
    async def start(
        *, credit_decision: CreditDecisionPort | None = None, **overrides: str
    ) -> AsyncIterator[BillingHost]:
        host_environment(**overrides)
        if credit_decision is None:
            app = create_real_app()
            async with app.router.lifespan_context(app):
                yield BillingHost(app=app, runtime=app.state.runtime, client=nats_client)
            return
        runtime = await start_runtime(load_settings(), credit_decision=credit_decision)
        app = create_routes()
        app.state.runtime = runtime
        try:
            yield BillingHost(app=app, runtime=runtime, client=nats_client)
        finally:
            app.state.runtime = None
            await runtime.stop()

    return start


@pytest_asyncio.fixture(loop_scope="function")
async def billing_host(billing_host_factory: HostFactory) -> AsyncIterator[BillingHost]:
    """The host over the migrated database, relay off, the default (simulator, rate 0) adapter."""
    async with billing_host_factory() as host:
        yield host


CENTS_RULE_SUFFIX = 99


def refuse_cents_rule(
    subject: str, body: dict[str, Any] | bytes, *, allow_cents_rule: bool
) -> None:
    """The fixture guard (#7 `cents-rule-fixture-guard.ts`, #8 `CentsRuleFixtureGuard.cs`; #8
    feature 20's N2: inherit the guard, not the search): a hold amount ending in 99 minor units is
    refused unless the test says it expects feature 20's `.99` rule, so the simulator cannot
    silently change a feature-19 fixture."""
    if allow_cents_rule or subject != "billing.credit.hold":
        return
    parsed = json.loads(body) if isinstance(body, bytes) else body
    amount = parsed.get("amount", {}).get("amount") if isinstance(parsed, dict) else None
    if isinstance(amount, int) and amount % 100 == CENTS_RULE_SUFFIX:
        raise AssertionError(
            f"the fixture amount {amount} ends in {CENTS_RULE_SUFFIX}: feature 20's simulator "
            "refuses it; pass allow_cents_rule=True if that is the point of the test"
        )


RpcCall = Callable[..., Awaitable[dict[str, Any]]]


@pytest.fixture
def rpc(nats_client: NatsClient) -> RpcCall:
    """`await rpc("billing.credit.hold", {...}, headers={...})` -> the reply, parsed JSON. Refuses
    a hold amount ending in 99 unless `allow_cents_rule=True`."""

    async def call(
        subject: str,
        body: dict[str, Any] | bytes,
        *,
        headers: dict[str, str] | None = None,
        allow_cents_rule: bool = False,
        timeout: float = 15,  # noqa: ASYNC109 - nats-py's own request parameter
    ) -> dict[str, Any]:
        refuse_cents_rule(subject, body, allow_cents_rule=allow_cents_rule)
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        reply = await nats_client.request(subject, data, timeout=timeout, headers=headers)
        parsed: dict[str, Any] = json.loads(reply.data)
        return parsed

    return call


class Decode:
    """Reply decoders that assert the reply's OWN discriminating field BEFORE touching any
    collection, so a wrong-shaped or error-shaped reply fails on a named assertion (BC32)."""

    @staticmethod
    def error(reply: dict[str, Any]) -> asyncapi.RpcError:
        assert "code" in reply, f"BC32: expected an RpcError (a `code`), got {reply}"
        return from_wire_json(asyncapi.RpcError, json.dumps(reply).encode())

    @staticmethod
    def hold(reply: dict[str, Any]) -> asyncapi.CreditHoldReplyPayload:
        assert "outcome" in reply, f"BC32: expected a hold reply (an `outcome`), got {reply}"
        return from_wire_json(asyncapi.CreditHoldReplyPayload, json.dumps(reply).encode())

    @staticmethod
    def release(reply: dict[str, Any]) -> asyncapi.CreditReleaseReplyPayload:
        assert "released" in reply, f"BC32: expected a release reply (`released`), got {reply}"
        return from_wire_json(asyncapi.CreditReleaseReplyPayload, json.dumps(reply).encode())

    @staticmethod
    def invoice_issue(reply: dict[str, Any]) -> asyncapi.InvoiceIssueReplyPayload:
        assert "created" in reply, f"BC32: expected an invoice-issue reply (`created`), got {reply}"
        return from_wire_json(asyncapi.InvoiceIssueReplyPayload, json.dumps(reply).encode())

    @staticmethod
    def payment_register(reply: dict[str, Any]) -> asyncapi.PaymentRegisterReplyPayload:
        assert "outcome" in reply, f"BC32: expected a payment reply (an `outcome`), got {reply}"
        return from_wire_json(asyncapi.PaymentRegisterReplyPayload, json.dumps(reply).encode())

    @staticmethod
    def invoice_list(reply: dict[str, Any]) -> asyncapi.InvoiceListReplyPayload:
        assert "page" in reply, f"BC32: expected an invoice list reply (a `page`), got {reply}"
        assert "total" in reply["page"], f"BC32: the page carries no total: {reply['page']}"
        return from_wire_json(asyncapi.InvoiceListReplyPayload, json.dumps(reply).encode())

    @staticmethod
    def list(reply: dict[str, Any]) -> asyncapi.CreditListReplyPayload:
        assert "page" in reply, f"BC32: expected a list reply (a `page`), got {reply}"
        assert "total" in reply["page"], f"BC32: the page carries no total: {reply['page']}"
        return from_wire_json(asyncapi.CreditListReplyPayload, json.dumps(reply).encode())


@pytest.fixture
def decode() -> type[Decode]:
    return Decode


# ---------------------------------------------------- feature 21: the issue fixture and its guard


@dataclass(frozen=True)
class IssueFixture:
    """A built `billing.invoice.issue` request and the figures derived from its lines."""

    body: dict[str, Any]
    amount: int
    discount: int
    total: int


def build_issue_fixture(
    lines: Sequence[tuple[str, int, int]],
    discount: int,
    *,
    order_reference: str,
    retailer_code: str,
    company_code: str,
    currency: str = "EUR",
    zero_discount_on_purpose: bool = False,
    zero_total_on_purpose: bool = False,
) -> IssueFixture:
    """Every issue fixture is built from LINES, never from a total: `amount = sum(units x
    unit_price)` and `total = amount - discount` are computed here. The fixture is REFUSED at build
    time unless `amount`, `discount` and `total` are pairwise distinct, non-zero and none contains
    another as a decimal substring (a zero figure is always refused through this: with no flag set
    it equals another figure, and equal values contain one another), so a mutation that drops,
    zeroes or swaps the discount cannot leave a test green by accident (BI38; #8's D2: zeroing the
    discount left 273 tests green because every request carried a zero discount). The two
    exceptions are `BI35`'s own zero total (`zero_total_on_purpose`) and an explicit
    `zero_discount_on_purpose`. `lines` are `(product_code, units, unit_price)`, sent in the order
    given (tests pass a non-canonical one).
    """
    amount = sum(units * unit_price for _, units, unit_price in lines)
    total = amount - discount
    figures = {"amount": amount, "discount": discount, "total": total}
    if amount == 0:
        raise AssertionError(f"fixture refused: the lines sum to zero: {figures}")
    names = list(figures)
    for index, first in enumerate(names):
        for second in names[index + 1 :]:
            a, b = figures[first], figures[second]
            if a == 0 or b == 0:
                continue  # a zero on purpose: the pair is not a coincidence
            if {first, second} == {"amount", "total"} and zero_discount_on_purpose:
                continue  # no discount: the total IS the amount
            if {first, second} == {"amount", "discount"} and zero_total_on_purpose:
                continue  # the discount equals the gross: the total is zero
            if str(a) in str(b) or str(b) in str(a):  # equal values contain one another
                raise AssertionError(
                    f"fixture refused: {first} ({a}) and {second} ({b}) are equal or contain one "
                    f"another as decimal substrings, so a mutation swapping, dropping or zeroing "
                    f"one could leave a test green: {figures}"
                )
    if zero_discount_on_purpose and discount != 0:
        raise AssertionError("fixture refused: zero_discount_on_purpose with a non-zero discount")
    if zero_total_on_purpose and total != 0:
        raise AssertionError("fixture refused: zero_total_on_purpose with a non-zero total")
    body: dict[str, Any] = {
        "orderReference": order_reference,
        "retailerCode": retailer_code,
        "companyCode": company_code,
        "currency": currency,
        "lines": [
            {"productCode": code, "units": units, "unitPrice": price}
            for code, units, price in lines
        ],
        "discount": discount,
    }
    return IssueFixture(body=body, amount=amount, discount=discount, total=total)


IssueBody = Callable[..., IssueFixture]


@pytest.fixture
def issue_body() -> IssueBody:
    return build_issue_fixture


@dataclass
class InvoiceStore:
    """The real transactions object over a session factory built in THIS test's loop."""

    transactions: SqlAlchemyCreditTransactions
    sessions: async_sessionmaker[AsyncSession]
    engine: AsyncEngine


MakeInvoiceStore = Callable[..., InvoiceStore]


@pytest_asyncio.fixture(loop_scope="function")
async def make_invoice_store(migrated_db: FreshDatabase) -> AsyncIterator[MakeInvoiceStore]:
    """`make_invoice_store(server_settings={...})`: an engine built in THIS test's loop and
    disposed here, with the real `SqlAlchemyCreditTransactions` over it."""
    engines: list[AsyncEngine] = []

    def make(*, server_settings: dict[str, str] | None = None) -> InvoiceStore:
        engine = create_async_engine(
            migrated_db.url,
            connect_args={"server_settings": server_settings} if server_settings else {},
        )
        engines.append(engine)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        transactions = SqlAlchemyCreditTransactions(
            sessions=sessions, outbox=OutboxWriter(clock=SystemClock()), clock=SystemClock()
        )
        return InvoiceStore(transactions=transactions, sessions=sessions, engine=engine)

    try:
        yield make
    finally:
        for engine in engines:
            await engine.dispose()


# ----------------------------------------------------- feature 22: an issued invoice, the real way


@dataclass(frozen=True)
class IssuedWorld:
    """One order taken through `billing.credit.hold` and `billing.invoice.issue` by the REAL host:
    the credit line, an invoice in status `issued`, and the figures it was built from."""

    order_reference: str
    retailer_code: str
    company_code: str
    line_id: uuid.UUID
    invoice_id: uuid.UUID
    invoice_reference: str
    correlation: str  # the order id: the saga's x-correlation-id
    amount: int
    discount: int
    total: int
    limit: int
    other_hold: int

    @property
    def available_before(self) -> int:
        return self.limit - self.other_hold - self.total

    @property
    def available_after(self) -> int:
        return self.limit - self.other_hold


MakeWorld = Callable[..., Awaitable[IssuedWorld]]


@pytest.fixture
def make_world(db: Db, rpc: RpcCall, decode: type[Decode], issue_body: IssueBody) -> MakeWorld:
    """`await make_world()`: the default world (RETAIL-77 / SUPPLY-CO, order ORD-000101, lines
    3 x 1999 + 2 x 1234, discount 350, net 8115, a limit of 250 000 and ANOTHER order's hold of
    20 021 on the same line). `await make_world(second=True)` builds a different, independent
    world on another credit line (other lines, discount and totals, so no figure of one satisfies
    an assertion about the other); `same_total=True` gives the second world the FIRST world's net
    (8115, from a gross of 9321 and a discount of 1206) so a test about identity cannot be
    satisfied by the amounts differing. Both go through the real host the TEST started (this fixture
    starts none: two hosts would share the queue group); nothing is planted but the line and the
    other order's hold."""

    async def build(*, second: bool = False, same_total: bool = False) -> IssuedWorld:
        if second:
            order, retailer, company, code = "ORD-000404", "RETAIL-88", "SUPPLY-88", "CR-000654"
            lines, discount, other_order = (
                [("PRD-BB", 4, 2111), ("PRD-CC", 1, 877)],
                1206 if same_total else 411,  # same_total: the net of the default world
                "ORD-000505",
            )
            limit, other_hold = 300_000, 31_337
        else:
            order, retailer, company, code = "ORD-000101", "RETAIL-77", "SUPPLY-CO", "CR-000321"
            lines, discount, other_order = (
                [("PRD-ZZ", 3, 1999), ("PRD-AA", 2, 1234)],
                350,
                "ORD-000202",
            )
            limit, other_hold = 250_000, 20_021
        line_id = await db.seed_line(retailer, company, limit=limit, code=code)
        await db.plant_entry(line_id, other_order, other_hold, "hold")
        built = issue_body(
            lines, discount, order_reference=order, retailer_code=retailer, company_code=company
        )
        correlation = str(uuid.uuid4())
        held = await rpc(
            "billing.credit.hold",
            {
                "orderReference": order,
                "retailerCode": retailer,
                "companyCode": company,
                "amount": {"amount": built.total, "currency": "EUR"},
            },
            headers={"x-correlation-id": correlation, "x-request-id": str(uuid.uuid4())},
        )
        assert decode.hold(held).outcome.value == "approved"
        issued = decode.invoice_issue(
            await rpc(
                "billing.invoice.issue",
                built.body,
                headers={"x-correlation-id": correlation, "x-request-id": str(uuid.uuid4())},
            )
        )
        assert issued.created is True
        assert issued.status.value == "issued"
        assert issued.invoice_id is not None
        return IssuedWorld(
            order_reference=order,
            retailer_code=retailer,
            company_code=company,
            line_id=line_id,
            invoice_id=issued.invoice_id,
            invoice_reference=issued.invoice_reference,
            correlation=correlation,
            amount=built.amount,
            discount=built.discount,
            total=built.total,
            limit=limit,
            other_hold=other_hold,
        )

    return build
