"""The migrated-database template (root `conftest.py`) isolates tests from each other.

`migrated_database_from_template("billing")` hands out `CREATE DATABASE ... TEMPLATE` copies of one
migrated template per service and session. Isolation is the property the optimisation must not
lose: a test's write must not be visible to the next test, nor to the template. Three claims, each
armed by handing the template itself out (or by not dropping the copy):

1. two copies requested in one test are different databases, and a write to one is invisible in
   the other;
2. a copy written to by one test is DROPPED when that test ends, and the next test's copy is empty
   (the two tests run in file order; the second reads what the first recorded);
3. the template stays pristine: a fresh copy requested after a write still has zero rows.
"""

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Protocol

import asyncpg
import pytest

pytestmark = pytest.mark.integration


class FreshDatabase(Protocol):
    """The shape of the root conftest's `FreshDatabase` (conftest modules are not importable)."""

    @property
    def name(self) -> str: ...
    @property
    def dsn(self) -> str: ...


class PostgresServer(Protocol):
    def dsn(self, database: str) -> str: ...


MigratedDatabaseFactory = Callable[[str], Awaitable[FreshDatabase]]
NOW = datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC)
INSERT = "INSERT INTO processed_events VALUES ($1, $2, 'isolation', $3, $3)"
_written_by_the_first_test: list[str] = []


async def _count(dsn: str) -> int:
    conn = await asyncpg.connect(dsn)
    try:
        return int(await conn.fetchval("SELECT count(*) FROM processed_events"))
    finally:
        await conn.close()


async def _write(db: FreshDatabase) -> None:
    conn = await asyncpg.connect(db.dsn)
    try:
        await conn.execute(INSERT, uuid.uuid4(), uuid.uuid4(), NOW)
    finally:
        await conn.close()


async def _exists(server: PostgresServer, name: str) -> bool:
    conn = await asyncpg.connect(server.dsn("postgres"))
    try:
        return bool(
            await conn.fetchval("SELECT count(*) FROM pg_database WHERE datname = $1", name)
        )
    finally:
        await conn.close()


async def test_two_copies_are_distinct_databases_and_a_write_to_one_is_invisible_in_the_other(
    migrated_database_from_template: MigratedDatabaseFactory,
) -> None:
    first = await migrated_database_from_template("billing")
    second = await migrated_database_from_template("billing")
    assert first.name != second.name
    await _write(first)
    assert await _count(first.dsn) == 1
    assert await _count(second.dsn) == 0
    third = await migrated_database_from_template("billing")  # requested AFTER the write
    assert await _count(third.dsn) == 0  # the template itself was never written to


async def test_first_a_copy_is_written_to_and_recorded(
    migrated_database_from_template: MigratedDatabaseFactory,
) -> None:
    db = await migrated_database_from_template("billing")
    assert await _count(db.dsn) == 0
    await _write(db)
    assert await _count(db.dsn) == 1
    _written_by_the_first_test.append(db.name)


async def test_then_the_next_test_gets_an_empty_copy_and_the_written_one_is_gone(
    migrated_database_from_template: MigratedDatabaseFactory, postgres_server: PostgresServer
) -> None:
    assert len(_written_by_the_first_test) == 1, "the previous test did not run first"
    db = await migrated_database_from_template("billing")
    assert db.name != _written_by_the_first_test[0]
    assert await _count(db.dsn) == 0  # the previous test's row is not here
    assert not await _exists(
        postgres_server, _written_by_the_first_test[0]
    )  # and its db is dropped
