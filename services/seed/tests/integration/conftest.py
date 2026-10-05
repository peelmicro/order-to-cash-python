"""Seed integration fixtures: the three migrated databases and a MongoDB database, per test.

The container servers and the migrated TEMPLATES live in the repository-root `conftest.py`
(`postgres_server`, `migrated_database_from_template`, `mongo_server`, `fresh_mongo_database`): the
seed never creates a schema of its own, it writes into the very databases the three services'
Alembic histories produced. Loop scope of every async fixture here: `function` (the pytest default
of this repository, written next to each one): the engines and the Mongo client a test builds are
created and closed inside the loop that uses them, by `runtime`'s own teardown.
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

import asyncpg
import pytest
import pytest_asyncio

from otc_seed.composition import SeedRuntime, build_runtime
from otc_seed.infrastructure.settings import SeedSettings


class FreshDatabase(Protocol):
    """The shape of the root conftest's `FreshDatabase` (conftest modules are not importable)."""

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


@dataclass(frozen=True)
class Stack:
    orders: FreshDatabase
    fulfillment: FreshDatabase
    billing: FreshDatabase
    mongo: FreshMongoDatabase

    def env(self) -> dict[str, str]:
        return {
            "ORDERS_DATABASE_URL": self.orders.url,
            "FULFILLMENT_DATABASE_URL": self.fulfillment.url,
            "BILLING_DATABASE_URL": self.billing.url,
            "MONGO_URI": self.mongo.uri,
            "MONGO_DB_READMODEL": self.mongo.name,
        }


@pytest_asyncio.fixture(loop_scope="function")
async def stack(
    migrated_database_from_template: Callable[[str], Awaitable[FreshDatabase]],
    fresh_mongo_database: FreshMongoDatabase,
) -> Stack:
    """Private, migrated copies of the orders, fulfillment and billing databases (templates built
    once per session from each service's own Alembic history) and an unused MongoDB database."""
    return Stack(
        orders=await migrated_database_from_template("orders"),
        fulfillment=await migrated_database_from_template("fulfillment"),
        billing=await migrated_database_from_template("billing"),
        mongo=fresh_mongo_database,
    )


@pytest.fixture
def settings(stack: Stack, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> SeedSettings:
    monkeypatch.chdir(tmp_path)  # no developer `.env` can reach the settings
    for name, value in stack.env().items():
        monkeypatch.setenv(name, value)
    return SeedSettings(_env_file=None)  # type: ignore[call-arg]


@pytest_asyncio.fixture(loop_scope="function")
async def runtime(settings: SeedSettings) -> AsyncIterator[SeedRuntime]:
    built = build_runtime(settings)
    try:
        yield built
    finally:
        await built.aclose()


async def _dump(dsn: str) -> dict[str, list[tuple[str, str]]]:
    """EVERY row of EVERY table of a database, as `(row text, xmin)`, ordered by primary key.

    The row text is PostgreSQL's own rendering of the whole row (every column, `json` as stored);
    `xmin` is the id of the transaction that wrote the row version, so a row that was REWRITTEN with
    identical content still changes. Compared before and after a second run, a count is not enough:
    this is."""
    conn = await asyncpg.connect(dsn)
    try:
        names = [
            r["table_name"]
            for r in await conn.fetch(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY 1"
            )
        ]
        dump: dict[str, list[tuple[str, str]]] = {}
        for name in names:
            rows = await conn.fetch(
                f'SELECT t::text AS body, t.xmin::text AS xmin FROM "{name}" t ORDER BY t.id'  # noqa: S608
                if name not in ("alembic_version",)
                else 'SELECT t::text AS body, t.xmin::text AS xmin FROM "alembic_version" t'
            )
            dump[name] = [(r["body"], r["xmin"]) for r in rows]
        return dump
    finally:
        await conn.close()


@pytest.fixture
def dump_database() -> Callable[[str], Awaitable[dict[str, list[tuple[str, str]]]]]:
    return _dump
