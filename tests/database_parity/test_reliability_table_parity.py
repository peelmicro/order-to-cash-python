"""Acceptance 2 - `outbox` and `processed_events` are identical across the four databases.

WHERE THIS LIVES, AND WHY (#8 review_db_billing A4): in `tests/database_parity/`, a neutral place
that no service owns. #8 put its equivalent inside the last service's suite, which therefore had to
reference three other services; #7 put it in the neutral `apps/seed/src/outbox-parity.spec.ts`.
This file imports no service package: it drives each service's own `alembic.ini` (a path) and reads
the result from PostgreSQL.

WHAT IT READS: the live catalogs only, never SQLAlchemy metadata (a test that asks the ORM what the
ORM believes proves nothing about the engine). Per table: every column from `information_schema`
joined to `pg_attribute` (type with its length and precision through `format_type`, nullability,
IDENTITY kind and its sequence parameters, default, generated, collation), every index from
`pg_indexes` (the whole `indexdef`: name, uniqueness, method, columns, DESC, INCLUDE, predicate) and
`pg_index` (primary, nulls-not-distinct, sort options, key-column count), every constraint from
`pg_constraint`. #8 A2: IDENTITY is in the shape, so a `seq` that loses its identity is a difference
even though its type, nullability and unique index are unchanged.

THE POPULATIONS ARE CLOSED LITERALS: `outbox` exists in exactly 3 databases (orders, fulfillment,
billing; notifications emits no fact) and `processed_events` in exactly 4. A parity guard over a
population of one is green by construction (#8 Phase 14), so the sizes are asserted as literals and
the populations are re-derived from the live catalogs, not from the list the test iterates.

HOW IT IS ARMED, PERMANENTLY: the `test_arm_*` tests below alter one LIVE database (a copy made with
`CREATE DATABASE ... TEMPLATE`, so the four reference databases stay untouched) and assert that the
comparison reports the difference by name: a changed outbox column type, a dropped identity, a
database missing from the population, a processed_events change in the fourth database, an extra
index. If the comparison ever stopped reading one of those facts, its arm would go red here.

LOOP/SCOPE: the four template databases are migrated ONCE per module by a sync fixture (each
`asyncio.run` and each Alembic run owns its loop and engine, disposed before it returns); tests are
function-loop async and open short-lived asyncpg connections.
"""

import asyncio
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Protocol

import asyncpg
import pytest
from alembic import command
from alembic.config import Config

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]

# the four databases, in migration order; the first is the reference of every comparison
DATABASES = ("orders", "fulfillment", "billing", "notifications")
OUTBOX_POPULATION = ("orders", "fulfillment", "billing")  # exactly 3
PROCESSED_EVENTS_POPULATION = DATABASES  # exactly 4
REFERENCE = "orders"


class PostgresServer(Protocol):
    """The shape of the root conftest's `PostgresServer` (not importable by name)."""

    def dsn(self, database: str) -> str: ...
    def sqlalchemy_url(self, database: str) -> str: ...


# ---------------------------------------------------------------- the catalog reads

COLUMNS_QUERY = """
SELECT c.ordinal_position::int AS ordinal, c.column_name::text AS name,
       format_type(a.atttypid, a.atttypmod) AS type, a.attnotnull AS not_null,
       a.attidentity::text AS identity, a.attgenerated::text AS generated,
       c.column_default::text AS col_default, c.is_nullable::text AS is_nullable,
       c.data_type::text AS data_type, c.character_maximum_length AS max_length,
       c.datetime_precision AS precision, c.is_identity::text AS is_identity,
       c.identity_generation::text AS identity_generation,
       c.identity_start::text AS identity_start, c.identity_increment::text AS identity_increment,
       c.identity_maximum::text AS identity_maximum, c.identity_minimum::text AS identity_minimum,
       c.identity_cycle::text AS identity_cycle,
       (SELECT collname::text FROM pg_collation WHERE oid = a.attcollation) AS collation
  FROM information_schema.columns c
  JOIN pg_class cl ON cl.relname = c.table_name AND cl.relnamespace = 'public'::regnamespace
  JOIN pg_attribute a ON a.attrelid = cl.oid AND a.attname = c.column_name
 WHERE c.table_schema = 'public' AND c.table_name = $1
 ORDER BY c.ordinal_position
"""

INDEXES_QUERY = """
SELECT ix.indexname::text AS name, ix.indexdef::text AS definition, x.indisunique AS uniq,
       x.indisprimary AS is_primary, x.indnullsnotdistinct AS nulls_not_distinct,
       x.indoption::int2[] AS options, x.indnkeyatts::int AS key_columns,
       am.amname::text AS method,
       (SELECT array_agg(a.attname::text ORDER BY k.ord)
          FROM unnest(x.indkey::int2[]) WITH ORDINALITY k(attnum, ord)
          JOIN pg_attribute a ON a.attrelid = x.indrelid AND a.attnum = k.attnum) AS cols
  FROM pg_indexes ix
  JOIN pg_class i ON i.relname = ix.indexname AND i.relnamespace = 'public'::regnamespace
  JOIN pg_index x ON x.indexrelid = i.oid
  JOIN pg_am am ON am.oid = i.relam
 WHERE ix.schemaname = 'public' AND ix.tablename = $1
 ORDER BY ix.indexname
"""

CONSTRAINTS_QUERY = """
SELECT c.conname::text AS name, c.contype::text AS kind, pg_get_constraintdef(c.oid) AS definition
  FROM pg_constraint c
 WHERE c.conrelid = ('public.' || quote_ident($1))::regclass
 ORDER BY c.conname
"""

TABLES_QUERY = """
SELECT c.relname::text AS name FROM pg_class c
 WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r' ORDER BY c.relname
"""


Shape = dict[str, dict[str, dict[str, Any]]]  # table -> section -> name -> facts


async def _read_shape(dsn: str, table: str) -> dict[str, dict[str, dict[str, Any]]]:
    conn = await asyncpg.connect(dsn)
    try:
        columns = {r["name"]: dict(r) for r in await conn.fetch(COLUMNS_QUERY, table)}
        indexes = {r["name"]: dict(r) for r in await conn.fetch(INDEXES_QUERY, table)}
        constraints = {r["name"]: dict(r) for r in await conn.fetch(CONSTRAINTS_QUERY, table)}
    finally:
        await conn.close()
    return {"columns": columns, "indexes": indexes, "constraints": constraints}


async def _tables(dsn: str) -> set[str]:
    conn = await asyncpg.connect(dsn)
    try:
        return {r["name"] for r in await conn.fetch(TABLES_QUERY)}
    finally:
        await conn.close()


def _differences(
    reference: dict[str, dict[str, dict[str, Any]]],
    other: dict[str, dict[str, dict[str, Any]]],
    where: str,
) -> list[str]:
    """Every difference between two shapes of one table, one line each, naming `where`."""
    found: list[str] = []
    for section, noun in (
        ("columns", "column"),
        ("indexes", "index"),
        ("constraints", "constraint"),
    ):
        ref, oth = reference[section], other[section]
        for name in sorted(set(ref) - set(oth)):
            found.append(f"{where}: {noun} {name} is missing")
        for name in sorted(set(oth) - set(ref)):
            found.append(f"{where}: {noun} {name} is extra")
        for name in sorted(set(ref) & set(oth)):
            for fact in sorted(ref[name]):
                if ref[name][fact] != oth[name][fact]:
                    found.append(
                        f"{where}: {noun} {name}: {fact} is {oth[name][fact]!r}, "
                        f"the reference has {ref[name][fact]!r}"
                    )
    return found


async def check_parity(dsns: dict[str, str]) -> list[str]:
    """Compare `outbox` (3 databases) and `processed_events` (4) with the reference database.

    Raises `AssertionError` when a population is not the literal one, when a population member is
    absent from `dsns`, or when a reference shape is empty (a comparison over nothing). Returns the
    differences (empty when every member equals the reference).
    """
    populations = {
        "outbox": OUTBOX_POPULATION,
        "processed_events": PROCESSED_EVENTS_POPULATION,
    }
    sizes = {"outbox": 3, "processed_events": 4}
    found: list[str] = []
    for table, members in populations.items():
        assert len(members) == sizes[table], f"{table}: the population literal changed"
        holders: list[str] = []
        for db in DATABASES:
            if db in dsns and table in await _tables(dsns[db]):
                holders.append(db)
        present = tuple(holders)
        assert present == members, (
            f"{table}: population is {present}, the plan says {members}: a parity guard over a "
            "smaller population is green by construction"
        )
        shapes = {db: await _read_shape(dsns[db], table) for db in members}
        reference = shapes[REFERENCE]
        assert len(reference["columns"]) > 0, f"{table}: the reference has no columns"
        assert len(reference["indexes"]) > 0, f"{table}: the reference has no indexes"
        for db in members:
            if db != REFERENCE:
                found += _differences(reference, shapes[db], f"{db}.{table}")
    return found


# ---------------------------------------------------------------- the fixtures


def _run_sync(coro: Any) -> Any:
    return asyncio.run(coro)


async def _admin(server: PostgresServer, sql: str) -> None:
    conn = await asyncpg.connect(server.dsn("postgres"))
    try:
        await conn.execute(sql)
    finally:
        await conn.close()


def _alembic_upgrade(service: str, url: str) -> None:
    config = Config(str(REPO_ROOT / "services" / service / "alembic.ini"))
    config.attributes["url"] = url
    command.upgrade(config, "head")  # env.py runs its own asyncio.run: no loop is running here


@pytest.fixture(scope="module")
def migrated_templates(postgres_server: PostgresServer) -> Iterator[dict[str, str]]:
    """Four FRESH databases, one per service, migrated to head by that service's own Alembic
    history. Read-only for the tests; the arms work on copies."""
    run = uuid.uuid4().hex[:12]
    names = {service: f"otc_parity_{run}_{service}" for service in DATABASES}
    try:
        for service, name in names.items():
            _run_sync(_admin(postgres_server, f'CREATE DATABASE "{name}"'))
            _alembic_upgrade(service, postgres_server.sqlalchemy_url(name))
        yield {service: postgres_server.dsn(name) for service, name in names.items()}
    finally:
        for name in names.values():
            _run_sync(_admin(postgres_server, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


@pytest.fixture
def copies(
    postgres_server: PostgresServer, migrated_templates: dict[str, str]
) -> Iterator[dict[str, str]]:
    """A private copy of each migrated database (`CREATE DATABASE ... TEMPLATE`), which an arm may
    break without touching the references. The templates must have no open session: every read
    above closes its connection."""
    run = uuid.uuid4().hex[:12]
    names: dict[str, str] = {}
    try:
        for service, dsn in migrated_templates.items():
            template = dsn.rsplit("/", 1)[1]
            names[service] = f"otc_parity_copy_{run}_{service}"
            _run_sync(
                _admin(postgres_server, f'CREATE DATABASE "{names[service]}" TEMPLATE "{template}"')
            )
        yield {service: postgres_server.dsn(name) for service, name in names.items()}
    finally:
        for name in names.values():
            _run_sync(_admin(postgres_server, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


async def _execute(dsn: str, sql: str) -> None:
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(sql)
    finally:
        await conn.close()


# ---------------------------------------------------------------- the guard itself


async def test_outbox_and_processed_events_are_identical_across_the_four_databases(
    migrated_templates: dict[str, str],
) -> None:
    assert tuple(migrated_templates) == DATABASES
    assert len(DATABASES) == 4
    assert len(OUTBOX_POPULATION) == 3
    assert await check_parity(migrated_templates) == []


async def test_the_populations_are_derived_from_the_live_catalogs_and_are_literally_3_and_4(
    migrated_templates: dict[str, str],
) -> None:
    has_outbox = {db for db, dsn in migrated_templates.items() if "outbox" in await _tables(dsn)}
    has_processed = {
        db for db, dsn in migrated_templates.items() if "processed_events" in await _tables(dsn)
    }
    assert has_outbox == {"orders", "fulfillment", "billing"}
    assert len(has_outbox) == 3
    assert has_processed == {"orders", "fulfillment", "billing", "notifications"}
    assert len(has_processed) == 4


async def test_the_reference_shape_includes_identity_and_the_two_outbox_indexes(
    migrated_templates: dict[str, str],
) -> None:
    shape = await _read_shape(migrated_templates[REFERENCE], "outbox")
    assert len(shape["columns"]) == 12
    seq = shape["columns"]["seq"]
    assert (seq["identity"], seq["is_identity"], seq["identity_generation"]) == (
        "a",
        "YES",
        "ALWAYS",
    )
    assert seq["type"] == "bigint"
    names = set(shape["indexes"])
    assert {"ix_outbox_published_at_seq", "ix_outbox_published_at_occurred_at"} <= names
    assert len(shape["indexes"]) == 5
    processed = await _read_shape(migrated_templates[REFERENCE], "processed_events")
    assert (len(processed["columns"]), len(processed["indexes"])) == (5, 2)


# ---------------------------------------------------------------- the permanent arms


async def test_arm_one_databases_outbox_column_type_is_a_named_difference(
    copies: dict[str, str],
) -> None:
    assert await check_parity(copies) == []  # green before the change
    await _execute(copies["billing"], "ALTER TABLE outbox ALTER COLUMN event_type TYPE varchar(61)")
    found = await check_parity(copies)
    assert any(
        line.startswith("billing.outbox: column event_type: type is 'character varying(61)'")
        for line in found
    ), found


async def test_arm_dropping_identity_on_one_seq_is_a_named_difference(
    copies: dict[str, str],
) -> None:
    assert await check_parity(copies) == []
    await _execute(copies["fulfillment"], "ALTER TABLE outbox ALTER COLUMN seq DROP IDENTITY")
    found = await check_parity(copies)
    # type, nullability and the unique index of `seq` are all unchanged: only identity differs
    assert any("fulfillment.outbox: column seq: identity is ''" in line for line in found), found
    assert not any("column seq: type" in line for line in found), found
    assert not any("index uq_outbox_seq" in line for line in found), found


async def test_arm_removing_one_database_from_the_population_fails_loudly(
    copies: dict[str, str],
) -> None:
    assert await check_parity(copies) == []
    without_billing = {db: dsn for db, dsn in copies.items() if db != "billing"}
    assert len(without_billing) == 3
    with pytest.raises(AssertionError, match=r"outbox: population is .* the plan says"):
        await check_parity(without_billing)


async def test_arm_the_fourth_database_is_in_the_processed_events_population(
    copies: dict[str, str],
) -> None:
    assert await check_parity(copies) == []
    await _execute(
        copies["notifications"],
        "ALTER TABLE processed_events ALTER COLUMN consumer TYPE varchar(51)",
    )
    found = await check_parity(copies)
    assert any(
        line.startswith("notifications.processed_events: column consumer: type") for line in found
    ), found


async def test_arm_an_extra_or_changed_index_is_a_named_difference(
    copies: dict[str, str],
) -> None:
    assert await check_parity(copies) == []
    await _execute(
        copies["orders"],
        "DROP INDEX ix_outbox_published_at_seq; "
        "CREATE INDEX ix_outbox_published_at_seq ON outbox (published_at DESC, seq)",
    )
    await _execute(copies["billing"], "CREATE INDEX ix_stray ON processed_events (consumer)")
    found = await check_parity(copies)
    # the reference itself was altered, so every other member differs from it by the DESC column
    assert any("index ix_outbox_published_at_seq: options" in line for line in found), found
    assert any("billing.processed_events: index ix_stray is extra" in line for line in found), found
