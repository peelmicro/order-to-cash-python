"""Acceptance 3 and 5 - foreign keys and indexes (unit: the FK set / the index set of
`otc_fulfillment`).

Both are CLOSED sets read from the live catalog (`pg_constraint contype='f'`, `pg_index` joined to
`pg_am`) and compared for equality with a literal; the diagnostic (missing and extra, by name) is
built before any count is asserted (#8 A2). The tuples are the widened ones of backlog 206: an FK is
identified by its delete AND update action, deferrability and match type, and an index by its access
method as well as its columns.

TWO FKs, read from: Databases.EN.md section 5 (`reservations.stock_id -> stock`,
`despatch_items.despatch_id -> despatches` cascade); #8 `InitialCreate.cs` declares exactly two
(`table.ForeignKey(` at :114 and :140); #7 `apps/fulfillment/drizzle/0000_nappy_mad_thinker.sql`
has two `FOREIGN KEY` lines (75, 76). `reservations.stock_id` is NO ACTION on delete as in #7 (#8
used Restrict; the spec says nothing, and NO ACTION is what orders' FKs use too).
"""

from typing import Any

import asyncpg
import pytest

pytestmark = pytest.mark.integration

# (table, columns, referenced table, referenced columns, on delete, on update, deferrable,
# initially deferred, match type).
EXPECTED_FKS = {
    ("reservations", ("stock_id",), "stock", ("id",), "a", "a", False, False, "s"),
    ("despatch_items", ("despatch_id",), "despatches", ("id",), "c", "a", False, False, "s"),
}

FK_QUERY = """
SELECT t.relname AS tbl,
       (SELECT array_agg(a.attname::text ORDER BY k.ord)
          FROM unnest(c.conkey) WITH ORDINALITY k(attnum, ord)
          JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum) AS cols,
       rt.relname AS ref_tbl,
       (SELECT array_agg(a.attname::text ORDER BY k.ord)
          FROM unnest(c.confkey) WITH ORDINALITY k(attnum, ord)
          JOIN pg_attribute a ON a.attrelid = c.confrelid AND a.attnum = k.attnum) AS ref_cols,
       c.confdeltype::text AS on_delete, c.confupdtype::text AS on_update,
       c.condeferrable AS deferrable, c.condeferred AS deferred, c.confmatchtype::text AS match
  FROM pg_constraint c
  JOIN pg_class t ON t.oid = c.conrelid
  JOIN pg_class rt ON rt.oid = c.confrelid
 WHERE c.contype = 'f' AND t.relnamespace = 'public'::regnamespace
"""

# (table, index name, unique, columns in order, partial predicate, access method); the sort
# options and key-column count are appended by `_asc_with_every_column_a_key` below. Primary keys,
# unique constraints and plain indexes alike: pg_index lists every index the engine holds. The FK
# supporting indexes (ix_reservations_stock_id, ix_despatch_items_despatch_id) are members.
PLANNED_INDEXES = {
    ("stock", "pk_stock", True, ("id",), None, "btree"),
    (
        "stock",
        "uq_stock_company_code_product_code",
        True,
        ("company_code", "product_code"),
        None,
        "btree",
    ),
    ("reservations", "pk_reservations", True, ("id",), None, "btree"),
    ("reservations", "ix_reservations_stock_id", False, ("stock_id",), None, "btree"),
    (
        "reservations",
        "ix_reservations_order_reference_status",
        False,
        ("order_reference", "status"),
        None,
        "btree",
    ),
    ("despatches", "pk_despatches", True, ("id",), None, "btree"),
    (
        "despatches",
        "uq_despatches_despatch_reference",
        True,
        ("despatch_reference",),
        None,
        "btree",
    ),
    ("despatches", "uq_despatches_order_reference", True, ("order_reference",), None, "btree"),
    ("despatch_items", "pk_despatch_items", True, ("id",), None, "btree"),
    ("despatch_items", "ix_despatch_items_despatch_id", False, ("despatch_id",), None, "btree"),
    ("despatch_number_sequences", "pk_despatch_number_sequences", True, ("id",), None, "btree"),
    ("outbox", "pk_outbox", True, ("id",), None, "btree"),
    ("outbox", "uq_outbox_event_id", True, ("event_id",), None, "btree"),
    ("outbox", "uq_outbox_seq", True, ("seq",), None, "btree"),
    ("outbox", "ix_outbox_published_at_seq", False, ("published_at", "seq"), None, "btree"),
    (
        "outbox",
        "ix_outbox_published_at_occurred_at",
        False,
        ("published_at", "occurred_at"),
        None,
        "btree",
    ),
    ("processed_events", "pk_processed_events", True, ("id",), None, "btree"),
    (
        "processed_events",
        "uq_processed_events_event_id_consumer",
        True,
        ("event_id", "consumer"),
        None,
        "btree",
    ),
}


def _asc_with_every_column_a_key(entry: tuple[Any, ...]) -> tuple[Any, ...]:
    """Backlog 208(a): every planned index sorts every column ASC (`pg_index.indoption` 0) and has
    no INCLUDE column (`indnkeyatts` == the number of columns); the two members are appended to the
    literal, so a DESC column or a `(a) INCLUDE (b)` index in place of `(a, b)` is an extra."""
    columns = entry[3]
    return (*entry, (0,) * len(columns), len(columns))


EXPECTED_INDEXES = {_asc_with_every_column_a_key(entry) for entry in PLANNED_INDEXES}

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


def _diagnostic(expected: set[tuple[Any, ...]], live: set[tuple[Any, ...]]) -> str:
    return f"missing: {sorted(expected - live)}\nextra: {sorted(live - expected)}"


async def test_the_foreign_key_set_is_exactly_the_two_planned(migrated_db: Any) -> None:
    conn = await asyncpg.connect(migrated_db.dsn)
    try:
        rows = await conn.fetch(FK_QUERY)
    finally:
        await conn.close()
    live = {
        (
            r["tbl"],
            tuple(r["cols"]),
            r["ref_tbl"],
            tuple(r["ref_cols"]),
            r["on_delete"],
            r["on_update"],
            r["deferrable"],
            r["deferred"],
            r["match"],
        )
        for r in rows
    }
    diagnostic = _diagnostic(EXPECTED_FKS, live)
    assert live == EXPECTED_FKS, diagnostic
    assert len(rows) == len(EXPECTED_FKS) == 2, diagnostic


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
    diagnostic = _diagnostic(EXPECTED_INDEXES, live)
    assert live == EXPECTED_INDEXES, diagnostic
    assert len(rows) == len(EXPECTED_INDEXES) == 18, diagnostic
    # no index is NULLS NOT DISTINCT (the orders instrument carries the same check)
    assert [r["idx"] for r in rows if r["nulls_not_distinct"]] == []
