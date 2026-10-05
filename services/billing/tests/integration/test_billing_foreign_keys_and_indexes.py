"""Acceptance 4 (FK set, index set) - unit: the FK set / the index set of `otc_billing`.

Both are CLOSED sets read from the live catalog (`pg_constraint contype='f'`, `pg_index` joined to
`pg_am`) and compared for equality with a literal; the diagnostic (missing and extra, by name) is
built before any count is asserted (#8 A2). The tuples are the widened ones of backlog 206 and 208:
an FK is identified by its delete AND update action, deferrability and match type; an index by its
access method, its per-column sort options (`pg_index.indoption`: DESC, NULLS FIRST) and its number
of KEY columns (`pg_index.indnkeyatts`: `(a, b)` and `(a) INCLUDE (b)` list the same columns).

THREE FKs, read from: Databases.EN.md section 6 (`credit_items.credit_id -> credits`,
`invoice_items.invoice_id -> invoices` cascade, `payments.invoice_id -> invoices`), the plan's
"8 / 2 / 3" (line 971); #8 `Billing/.../20260901110439_InitialCreate.cs` declares exactly three
(`table.ForeignKey(` at :122, :145, :169 of that file: Restrict, Cascade, Restrict); #7
`apps/billing/drizzle/0000_brown_hammerhead.sql:94-96` has three `FOREIGN KEY` lines (NO ACTION,
CASCADE, NO ACTION). As in feature 10 (review N1) `credit_items`/`payments` are NO ACTION on
delete: #7's value, and what the live catalog of #8's Restrict is anyway.
"""

from typing import Any

import asyncpg
import pytest

pytestmark = pytest.mark.integration

# (table, columns, referenced table, referenced columns, on delete, on update, deferrable,
# initially deferred, match type).
EXPECTED_FKS = {
    ("credit_items", ("credit_id",), "credits", ("id",), "a", "a", False, False, "s"),
    ("invoice_items", ("invoice_id",), "invoices", ("id",), "c", "a", False, False, "s"),
    ("payments", ("invoice_id",), "invoices", ("id",), "a", "a", False, False, "s"),
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

# (table, index name, unique, columns in order, partial predicate, access method). Primary keys,
# unique constraints and plain indexes alike: pg_index lists every index the engine holds. The two
# FK supporting indexes (ix_invoice_items_invoice_id, ix_payments_invoice_id) are members;
# credit_items.credit_id is supported by the leading column of the spec's own composite index.
PLANNED_INDEXES = {
    ("credits", "pk_credits", True, ("id",), None, "btree"),
    ("credits", "uq_credits_code", True, ("code",), None, "btree"),
    (
        "credits",
        "uq_credits_retailer_code_company_code",
        True,
        ("retailer_code", "company_code"),
        None,
        "btree",
    ),
    ("credit_items", "pk_credit_items", True, ("id",), None, "btree"),
    (
        "credit_items",
        "ix_credit_items_credit_id_order_reference",
        False,
        ("credit_id", "order_reference"),
        None,
        "btree",
    ),
    ("invoices", "pk_invoices", True, ("id",), None, "btree"),
    ("invoices", "uq_invoices_invoice_reference", True, ("invoice_reference",), None, "btree"),
    ("invoices", "uq_invoices_order_reference", True, ("order_reference",), None, "btree"),
    (
        "invoices",
        "ix_invoices_status_invoice_date",
        False,
        ("status", "invoice_date"),
        None,
        "btree",
    ),
    ("invoice_items", "pk_invoice_items", True, ("id",), None, "btree"),
    ("invoice_items", "ix_invoice_items_invoice_id", False, ("invoice_id",), None, "btree"),
    ("invoice_number_sequences", "pk_invoice_number_sequences", True, ("id",), None, "btree"),
    ("payments", "pk_payments", True, ("id",), None, "btree"),
    ("payments", "uq_payments_payment_reference", True, ("payment_reference",), None, "btree"),
    ("payments", "ix_payments_invoice_id", False, ("invoice_id",), None, "btree"),
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
    """Backlog 208(a): every planned index sorts every column ASC (indoption 0) and has no INCLUDE
    column (indnkeyatts == the number of columns); the two members are appended to the literal."""
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


async def test_the_foreign_key_set_is_exactly_the_three_planned(migrated_db: Any) -> None:
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
    assert len(rows) == len(EXPECTED_FKS) == 3, diagnostic


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
    assert len(rows) == len(EXPECTED_INDEXES) == 22, diagnostic
    # no index is NULLS NOT DISTINCT
    assert [r["idx"] for r in rows if r["nulls_not_distinct"]] == []
