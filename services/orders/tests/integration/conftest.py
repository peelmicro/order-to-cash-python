"""Orders integration fixtures: an Alembic runner and a migrated database per test.

The shared container and `fresh_database` live in the repository-root `conftest.py`.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import asyncpg
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


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
