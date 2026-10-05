"""Acceptance 5 - the schema of `processed_events` in `otc_notifications` (unit: the table), read
from the LIVE catalog: every column's type, nullability and default, the closed index set (widened:
access method, sort options, key-column count), the absence of foreign keys, and the behaviour that
is the table's reason to exist: a second (event_id, consumer) row is refused by the engine.

The expected values are literals, never SQLAlchemy metadata. `consumer` is `varchar(50)`, #7's
width (`apps/notifications/drizzle/0000_sharp_rattler.sql:4`) and #8's (`nvarchar(50)`,
`20260901110547_InitialCreate.cs`).
"""

import uuid
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import asyncpg
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from otc_notifications.infrastructure.persistence.models import ProcessedEvent

pytestmark = pytest.mark.integration

EXPECTED_COLUMNS = {
    "id": ("uuid", False, ""),
    "event_id": ("uuid", False, ""),
    "consumer": ("character varying(50)", False, ""),
    "processed_at": ("timestamp(3) with time zone", False, ""),
    "created_at": ("timestamp(3) with time zone", False, ""),
}

# (table, index name, unique, columns in order, partial predicate, access method, indoption,
# indnkeyatts)
EXPECTED_INDEXES = {
    ("processed_events", "pk_processed_events", True, ("id",), None, "btree", (0,), 1),
    (
        "processed_events",
        "uq_processed_events_event_id_consumer",
        True,
        ("event_id", "consumer"),
        None,
        "btree",
        (0, 0),
        2,
    ),
}

CATALOG_QUERY = """
SELECT c.column_name, format_type(a.atttypid, a.atttypmod) AS type,
       c.is_nullable, c.is_identity, c.identity_generation, c.column_default
  FROM information_schema.columns c
  JOIN pg_class cl ON cl.relname = c.table_name AND cl.relnamespace = 'public'::regnamespace
  JOIN pg_attribute a ON a.attrelid = cl.oid AND a.attname = c.column_name
 WHERE c.table_schema = 'public' AND c.table_name = 'processed_events'
"""

INDEX_QUERY = """
SELECT t.relname AS tbl, i.relname AS idx, x.indisunique AS uniq,
       (SELECT array_agg(a.attname::text ORDER BY k.ord)
          FROM unnest(x.indkey::int2[]) WITH ORDINALITY k(attnum, ord)
          JOIN pg_attribute a ON a.attrelid = x.indrelid AND a.attnum = k.attnum) AS cols,
       pg_get_expr(x.indpred, x.indrelid) AS predicate, x.indnullsnotdistinct AS nulls_not_distinct,
       am.amname AS method, x.indoption::int2[] AS options, x.indnkeyatts::int AS key_columns
  FROM pg_index x
  JOIN pg_class i ON i.oid = x.indexrelid
  JOIN pg_am am ON am.oid = i.relam
  JOIN pg_class t ON t.oid = x.indrelid
 WHERE t.relnamespace = 'public'::regnamespace AND t.relname <> 'alembic_version'
"""


async def test_every_column_of_processed_events_has_the_planned_type(migrated_db: Any) -> None:
    conn = await asyncpg.connect(migrated_db.dsn)
    try:
        rows = await conn.fetch(CATALOG_QUERY)
        fks = await conn.fetchval("SELECT count(*) FROM pg_constraint WHERE contype = 'f'")
    finally:
        await conn.close()
    live = {
        r["column_name"]: (
            r["type"],
            r["is_nullable"] == "YES",
            f"identity:{r['identity_generation']}"
            if r["is_identity"] == "YES"
            else (r["column_default"] or ""),
        )
        for r in rows
    }
    differences = [
        f"{c}: expected {EXPECTED_COLUMNS.get(c)}, live {live.get(c)}"
        for c in sorted(set(EXPECTED_COLUMNS) | set(live))
        if EXPECTED_COLUMNS.get(c) != live.get(c)
    ]
    assert differences == []
    assert fks == 0  # this database has no foreign key at all


async def test_the_index_set_is_exactly_the_planned_one(migrated_db: Any) -> None:
    conn = await asyncpg.connect(migrated_db.dsn)
    try:
        rows = await conn.fetch(INDEX_QUERY)
    finally:
        await conn.close()
    live = {
        (
            r["tbl"],
            r["idx"],
            r["uniq"],
            tuple(r["cols"]),
            r["predicate"],
            r["method"],
            tuple(r["options"]),
            r["key_columns"],
        )
        for r in rows
    }
    diagnostic = (
        f"missing: {sorted(EXPECTED_INDEXES - live)}\nextra: {sorted(live - EXPECTED_INDEXES)}"
    )
    assert live == EXPECTED_INDEXES, diagnostic
    assert len(rows) == len(EXPECTED_INDEXES) == 2, diagnostic
    assert [r["idx"] for r in rows if r["nulls_not_distinct"]] == []


def _ts(n: int) -> datetime:
    return datetime(2026, 10, 5, 12, n, n, n * 1000 + 7000, tzinfo=UTC)


async def test_processed_events_round_trips_and_a_duplicate_event_for_a_consumer_is_refused(
    engine: AsyncEngine, migrated_db: Any
) -> None:
    row: dict[str, Any] = {
        "id": uuid.UUID(int=0xA1),
        "event_id": uuid.UUID(int=0xA2),
        "consumer": "notifications.invoice-issued",
        "processed_at": _ts(1),
        "created_at": _ts(2),
    }
    written = {**row, "processed_at": row["processed_at"].astimezone(timezone(timedelta(hours=2)))}
    async with AsyncSession(engine) as session, session.begin():
        session.add(ProcessedEvent(**written))
    conn = await asyncpg.connect(migrated_db.dsn)
    try:
        record = await conn.fetchrow("SELECT * FROM processed_events")
        assert record is not None
        via_sql = dict(record)
    finally:
        await conn.close()
    assert via_sql == row
    async with AsyncSession(engine) as session:
        loaded = (await session.execute(select(ProcessedEvent))).scalar_one()
        via_orm = {a.key: getattr(loaded, a.key) for a in ProcessedEvent.__mapper__.column_attrs}
    assert via_orm == row

    # the durable ledger: the same fact for the same consumer cannot be recorded twice, another
    # consumer can record it
    with pytest.raises(IntegrityError, match="uq_processed_events_event_id_consumer"):
        async with AsyncSession(engine) as session, session.begin():
            session.add(ProcessedEvent(**{**row, "id": uuid.UUID(int=0xA3)}))
    async with AsyncSession(engine) as session, session.begin():
        session.add(ProcessedEvent(**{**row, "id": uuid.UUID(int=0xA4), "consumer": "other"}))
