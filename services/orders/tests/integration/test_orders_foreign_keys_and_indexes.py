"""Acceptance 4 - foreign keys and indexes (unit: the FK set / the index set of `otc_orders`).

Both are CLOSED sets read from the live catalog (`pg_constraint contype='f'`, `pg_index`) and
compared for equality with a literal. #8 shipped 7 of its 8 FKs undeclared with a green suite
because the test asked for the one it had; here a missing member and an extra member both fail, and
the diagnostic (missing and extra, by name) is built before any count is asserted.

Eight FKs, from Databases.EN.md section 4: products.currency_id, retailers.currency_id,
companies.currency_id (lines 68, 82 and the companies shape), orders.company_id/retailer_id/
currency_id (lines 95-97), order_items.order_id/product_id (lines 113-114); #8's InitialCreate.cs
declares the same eight, and #7's 0000_bizarre_champions.sql:114-121 the same eight.
"""

from typing import Any

import asyncpg
import pytest

pytestmark = pytest.mark.integration

# (table, columns, referenced table, referenced columns, on delete, on update, deferrable,
# initially deferred, match type). 206: update action, deferrability and match type are part of the
# identity of an FK, so a substitution of any of them fails (F3).
EXPECTED_FKS = {
    ("products", ("currency_id",), "currencies", ("id",), "a", "a", False, False, "s"),
    ("retailers", ("currency_id",), "currencies", ("id",), "a", "a", False, False, "s"),
    ("companies", ("currency_id",), "currencies", ("id",), "a", "a", False, False, "s"),
    ("orders", ("company_id",), "companies", ("id",), "a", "a", False, False, "s"),
    ("orders", ("retailer_id",), "retailers", ("id",), "a", "a", False, False, "s"),
    ("orders", ("currency_id",), "currencies", ("id",), "a", "a", False, False, "s"),
    ("order_items", ("order_id",), "orders", ("id",), "c", "a", False, False, "s"),
    ("order_items", ("product_id",), "products", ("id",), "a", "a", False, False, "s"),
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
# unique constraints and plain indexes alike: pg_index lists every index the engine holds.
PLANNED_INDEXES = {
    ("currencies", "pk_currencies", True, ("id",), None, "btree"),
    ("currencies", "uq_currencies_code", True, ("code",), None, "btree"),
    ("products", "pk_products", True, ("id",), None, "btree"),
    ("products", "uq_products_code", True, ("code",), None, "btree"),
    ("products", "uq_products_ean", True, ("ean",), None, "btree"),
    ("products", "ix_products_currency_id", False, ("currency_id",), None, "btree"),
    ("retailers", "pk_retailers", True, ("id",), None, "btree"),
    ("retailers", "uq_retailers_code", True, ("code",), None, "btree"),
    ("retailers", "ix_retailers_currency_id", False, ("currency_id",), None, "btree"),
    ("companies", "pk_companies", True, ("id",), None, "btree"),
    ("companies", "uq_companies_code", True, ("code",), None, "btree"),
    ("companies", "ix_companies_currency_id", False, ("currency_id",), None, "btree"),
    ("orders", "pk_orders", True, ("id",), None, "btree"),
    ("orders", "uq_orders_order_reference", True, ("order_reference",), None, "btree"),
    ("orders", "uq_orders_request_id", True, ("request_id",), None, "btree"),
    ("orders", "ix_orders_company_id", False, ("company_id",), None, "btree"),
    ("orders", "ix_orders_retailer_id", False, ("retailer_id",), None, "btree"),
    ("orders", "ix_orders_currency_id", False, ("currency_id",), None, "btree"),
    ("orders", "ix_orders_retailer_id_status", False, ("retailer_id", "status"), None, "btree"),
    ("orders", "ix_orders_status_order_date", False, ("status", "order_date"), None, "btree"),
    ("order_items", "pk_order_items", True, ("id",), None, "btree"),
    ("order_items", "ix_order_items_order_id", False, ("order_id",), None, "btree"),
    ("order_items", "ix_order_items_product_id", False, ("product_id",), None, "btree"),
    ("order_number_sequences", "pk_order_number_sequences", True, ("id",), None, "btree"),
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
    ("saga_commands", "pk_saga_commands", True, ("id",), None, "btree"),
    (
        "saga_commands",
        "uq_saga_commands_order_id_command",
        True,
        ("order_id", "command"),
        None,
        "btree",
    ),
    (
        "saga_commands",
        "ix_saga_commands_status_created_at",
        False,
        ("status", "created_at"),
        None,
        "btree",
    ),
    (
        "saga_commands",
        "ix_saga_commands_status_next_attempt_at",
        False,
        ("status", "next_attempt_at"),
        None,
        "btree",
    ),
    ("saga_ignored_facts", "pk_saga_ignored_facts", True, ("id",), None, "btree"),
    (
        "saga_ignored_facts",
        "ix_saga_ignored_facts_correlation_id",
        False,
        ("correlation_id",),
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


async def test_the_foreign_key_set_is_exactly_the_eight_planned(migrated_db: Any) -> None:
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
    # diagnostic first (#8 A2): the missing/extra members, before any count is compared
    diagnostic = _diagnostic(EXPECTED_FKS, live)
    assert live == EXPECTED_FKS, diagnostic
    assert len(rows) == len(EXPECTED_FKS) == 8, diagnostic


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
    assert len(rows) == len(EXPECTED_INDEXES) == 37, diagnostic
    # no index is NULLS NOT DISTINCT: orders.request_id must accept many NULLs (R62)
    assert [r["idx"] for r in rows if r["nulls_not_distinct"]] == []
