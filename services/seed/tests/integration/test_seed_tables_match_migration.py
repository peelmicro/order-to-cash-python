"""The seed's own table definitions equal the Alembic-migrated schema of the three services.

R-map (feature_list.json id 12; the seed may not import a service's models, so its `Table`
definitions are copies): `schema_problems` compares them with the LIVE database that the services'
own migration histories produced (the root conftest's templates), column by column. A migration
that changes a table the seed writes (a type, a nullability, a new NOT NULL column, a foreign key,
a unique key) fails here, naming the table and column. Armed below by altering the live database.
"""

from collections.abc import Awaitable, Callable
from typing import Any

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from otc_seed.infrastructure import tables
from otc_seed.infrastructure.postgres import FulfillmentTarget, SchemaDriftError
from otc_seed.infrastructure.schema_check import schema_problems

pytestmark = pytest.mark.integration

SERVICES = [
    ("orders", tables.ORDERS_METADATA),
    ("fulfillment", tables.FULFILLMENT_METADATA),
    ("billing", tables.BILLING_METADATA),
]


async def _problems(url: str, metadata: Any) -> list[str]:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            return await schema_problems(conn, metadata)
    finally:
        await engine.dispose()


@pytest.mark.parametrize(("service", "metadata"), SERVICES)
async def test_the_seed_definitions_equal_the_migrated_schema(
    service: str,
    metadata: Any,
    migrated_database_from_template: Callable[[str], Awaitable[Any]],
) -> None:
    database = await migrated_database_from_template(service)
    assert await _problems(database.url, metadata) == []


def test_the_population_of_seeded_tables_is_the_expected_literal() -> None:
    names = {s: sorted(t.name for t in m.sorted_tables) for s, m in SERVICES}
    assert names == {
        "orders": [
            "companies",
            "currencies",
            "order_items",
            "orders",
            "outbox",
            "products",
            "retailers",
        ],
        "fulfillment": ["despatch_items", "despatches", "outbox", "reservations", "stock"],
        "billing": [
            "credit_items",
            "credits",
            "invoice_items",
            "invoices",
            "outbox",
            "payments",
        ],
    }


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        # a type widened by a later migration
        ("ALTER TABLE stock ALTER COLUMN units TYPE bigint", "stock.units"),
        # a column renamed
        ("ALTER TABLE stock RENAME COLUMN low_stock_threshold TO low_threshold", "stock.low_"),
        # a nullability flipped
        ("ALTER TABLE reservations ALTER COLUMN status DROP NOT NULL", "reservations.status"),
        # a NEW NOT NULL column the seed does not know about
        (
            "ALTER TABLE despatches ADD COLUMN carrier varchar(10) NOT NULL DEFAULT 'x'",
            "despatches.carrier",
        ),
        # a varchar shortened
        ("ALTER TABLE stock ALTER COLUMN company_code TYPE varchar(10)", "stock.company_code"),
        # a unique key dropped
        (
            "ALTER TABLE despatches DROP CONSTRAINT uq_despatches_despatch_reference",
            "despatches uniques",
        ),
        # a foreign key's ON DELETE changed
        (
            "ALTER TABLE despatch_items DROP CONSTRAINT fk_despatch_items_despatch_id_despatches, "
            "ADD CONSTRAINT fk_despatch_items_despatch_id_despatches "
            "FOREIGN KEY (despatch_id) REFERENCES despatches (id)",
            "despatch_items fks",
        ),
        # a table dropped
        ("DROP TABLE despatch_items", "table despatch_items does not exist"),
    ],
)
async def test_every_kind_of_drift_in_the_live_database_is_reported_by_name(
    sql: str,
    expected: str,
    migrated_database_from_template: Callable[[str], Awaitable[Any]],
) -> None:
    database = await migrated_database_from_template("fulfillment")
    conn = await asyncpg.connect(database.dsn)
    try:
        await conn.execute(sql)
    finally:
        await conn.close()
    problems = await _problems(database.url, tables.FULFILLMENT_METADATA)
    assert problems, f"{sql!r} was not detected"
    assert any(expected in p for p in problems), problems


async def test_the_seed_refuses_to_write_into_a_diverging_database_and_writes_nothing(
    migrated_database_from_template: Callable[[str], Awaitable[Any]],
) -> None:
    database = await migrated_database_from_template("fulfillment")
    conn = await asyncpg.connect(database.dsn)
    try:
        await conn.execute("ALTER TABLE stock ALTER COLUMN units TYPE bigint")
    finally:
        await conn.close()
    engine = create_async_engine(database.url)
    try:
        with pytest.raises(SchemaDriftError, match=r"stock\.units"):
            await FulfillmentTarget(engine).verify()
    finally:
        await engine.dispose()
    conn = await asyncpg.connect(database.dsn)
    try:
        assert await conn.fetchval("SELECT count(*) FROM stock") == 0
    finally:
        await conn.close()


async def test_an_unmigrated_database_is_refused_naming_the_table(
    fresh_database: Any,
) -> None:
    engine = create_async_engine(fresh_database.url)
    try:
        with pytest.raises(SchemaDriftError, match=r"table stock does not exist"):
            await FulfillmentTarget(engine).verify()
    finally:
        await engine.dispose()
