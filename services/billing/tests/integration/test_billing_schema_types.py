"""Acceptance 4 (types) - unit: every column of every table of `otc_billing`, read from the LIVE
database.

The expected map is a literal. It is never derived from SQLAlchemy metadata: a test that asks the
ORM what the ORM believes proves nothing about the engine. Sources: the plan's type-delta table
(uuid, timestamptz(3), varchar states, identity outbox.seq, json payloads, bigint money) and
`Order To Cash - Databases.EN.md` section 6 for names, lengths and nullability.

Each entry is (format_type(), nullable, extra). `extra` is "" or "identity:ALWAYS" or the column
default as the catalog prints it. `format_type` comes from pg_attribute, so it carries the
`timestamp(3) with time zone` precision that information_schema reports separately.

Deviations from section 6 (each also in progress/impl_db_billing.md): ids `uuid` not `char(36)`;
every `datetime` is `timestamptz(3)`; every `int` money column is `bigint` (the plan's delta table);
`currency_code` is `character(3)`, as `char(3)`; `invoice_number_sequences.id` is `integer` (section
6 gives no type, #7 used `tinyint`, which PostgreSQL does not have); `outbox.seq` is an identity,
not "bigint unsigned autoincrement"; `outbox.causation_id`/`trace_parent` are in (the section 4.3
definition).
"""

from typing import Any

import asyncpg
import pytest

pytestmark = pytest.mark.integration

UUID = "uuid"
TS3 = "timestamp(3) with time zone"
BIGINT = "bigint"
INT = "integer"
JSON = "json"
CHAR3 = "character(3)"


def V(n: int) -> str:
    return f"character varying({n})"


EXPECTED: dict[str, dict[str, tuple[str, bool, str]]] = {
    "credits": {
        "id": (UUID, False, ""),
        "code": (V(30), False, ""),
        "retailer_code": (V(20), False, ""),
        "company_code": (V(20), False, ""),
        "credit_limit": (BIGINT, False, ""),
        "currency_code": (CHAR3, False, ""),
        "created_at": (TS3, False, ""),
        "updated_at": (TS3, False, ""),
    },
    "credit_items": {
        "id": (UUID, False, ""),
        "credit_id": (UUID, False, ""),
        "order_reference": (V(20), False, ""),
        "amount": (BIGINT, False, ""),
        "type": (V(20), False, ""),
        "credit_date": (TS3, False, ""),
        "created_at": (TS3, False, ""),
        "updated_at": (TS3, False, ""),
    },
    "invoices": {
        "id": (UUID, False, ""),
        "invoice_reference": (V(20), False, ""),
        "invoice_date": (TS3, False, ""),
        "company_code": (V(20), False, ""),
        "retailer_code": (V(20), False, ""),
        "order_reference": (V(20), False, ""),
        "amount": (BIGINT, False, ""),
        "discount": (BIGINT, False, ""),
        "total_amount": (BIGINT, False, ""),
        "currency_code": (CHAR3, False, ""),
        "status": (V(20), False, ""),
        "paid_at": (TS3, True, ""),
        "created_at": (TS3, False, ""),
        "updated_at": (TS3, False, ""),
    },
    "invoice_items": {
        "id": (UUID, False, ""),
        "invoice_id": (UUID, False, ""),
        "product_code": (V(30), False, ""),
        "units": (INT, False, ""),
        "price": (BIGINT, False, ""),
        "created_at": (TS3, False, ""),
        "updated_at": (TS3, False, ""),
    },
    "invoice_number_sequences": {
        "id": (INT, False, ""),
        "next_value": (INT, False, ""),
    },
    "payments": {
        "id": (UUID, False, ""),
        "payment_reference": (V(30), False, ""),
        "invoice_id": (UUID, False, ""),
        "amount": (BIGINT, False, ""),
        "currency_code": (CHAR3, False, ""),
        "value_date": (TS3, False, ""),
        "source": (V(20), False, ""),
        "created_at": (TS3, False, ""),  # append-only: no updated_at
    },
    "outbox": {
        "id": (UUID, False, ""),
        "event_id": (UUID, False, ""),
        "event_type": (V(60), False, ""),
        "aggregate_id": (UUID, False, ""),
        "correlation_id": (UUID, False, ""),
        "causation_id": (UUID, False, ""),
        "payload": (JSON, False, ""),
        "occurred_at": (TS3, False, ""),
        "published_at": (TS3, True, ""),
        "created_at": (TS3, False, ""),
        "seq": (BIGINT, False, "identity:ALWAYS"),
        "trace_parent": (V(64), True, ""),
    },
    "processed_events": {
        "id": (UUID, False, ""),
        "event_id": (UUID, False, ""),
        "consumer": (V(50), False, ""),
        "processed_at": (TS3, False, ""),
        "created_at": (TS3, False, ""),
    },
}

# The money columns (minor units) of otc_billing: SEVEN columns on FIVE spec lines. Derived with
#   sed -n 241,305p "Order To Cash - Databases.EN.md" | grep -n -i cents
# which prints 5 lines (the `credit_limit`, `credit_items.amount`, `invoices` amount/discount/
# total_amount, `invoice_items.price` and `payments.amount` rows; the invoices line names three
# columns). Section 6 is lines 241-305 (`grep -n "^## "`: `## 6` at 241, `## 7` at 306). Orders has
# 6 (`sed -n 41,193p ... | grep -c -i cents` = 6), fulfillment 0, so 6 + 7 + 0 = 13, #8 id 44's
# "all 13 money columns".
MONEY_COLUMNS = {
    ("credits", "credit_limit"),
    ("credit_items", "amount"),
    ("invoices", "amount"),
    ("invoices", "discount"),
    ("invoices", "total_amount"),
    ("invoice_items", "price"),
    ("payments", "amount"),
}
BIGINT_COLUMNS = MONEY_COLUMNS | {("outbox", "seq")}

CATALOG_QUERY = """
SELECT c.table_name, c.column_name, format_type(a.atttypid, a.atttypmod) AS type,
       c.is_nullable, c.is_identity, c.identity_generation, c.column_default, c.data_type
  FROM information_schema.columns c
  JOIN pg_class cl ON cl.relname = c.table_name AND cl.relnamespace = 'public'::regnamespace
  JOIN pg_attribute a ON a.attrelid = cl.oid AND a.attname = c.column_name
 WHERE c.table_schema = 'public' AND c.table_name <> 'alembic_version'
"""


async def _live(dsn: str) -> list[asyncpg.Record]:
    conn = await asyncpg.connect(dsn)
    try:
        return await conn.fetch(CATALOG_QUERY)
    finally:
        await conn.close()


def _extra(row: asyncpg.Record) -> str:
    if row["is_identity"] == "YES":
        return f"identity:{row['identity_generation']}"
    return row["column_default"] or ""


async def test_every_column_of_every_table_has_the_planned_type(migrated_db: Any) -> None:
    rows = await _live(migrated_db.dsn)
    live: dict[str, dict[str, tuple[str, bool, str]]] = {}
    for r in rows:
        live.setdefault(r["table_name"], {})[r["column_name"]] = (
            r["type"],
            r["is_nullable"] == "YES",
            _extra(r),
        )
    assert set(live) == set(EXPECTED), "table set differs"
    differences = []
    for table in sorted(EXPECTED):
        for column in sorted(set(EXPECTED[table]) | set(live[table])):
            want, got = EXPECTED[table].get(column), live[table].get(column)
            if want != got:
                differences.append(f"{table}.{column}: expected {want}, live {got}")
    assert differences == []


async def test_the_seven_money_columns_are_bigint_and_no_other_column_is(
    migrated_db: Any,
) -> None:
    rows = {(r["table_name"], r["column_name"]): r for r in await _live(migrated_db.dsn)}
    assert len(MONEY_COLUMNS) == 7
    narrowed = {pair: rows[pair]["data_type"] for pair in MONEY_COLUMNS if pair in rows}
    assert {pair: t for pair, t in narrowed.items() if t != "bigint"} == {}
    assert {pair for pair, r in rows.items() if r["data_type"] == "bigint"} == BIGINT_COLUMNS


async def test_payload_columns_are_json_not_jsonb(migrated_db: Any) -> None:
    rows = {
        (r["table_name"], r["column_name"]): r["data_type"] for r in await _live(migrated_db.dsn)
    }
    assert {k: v for k, v in rows.items() if v in ("json", "jsonb")} == {
        ("outbox", "payload"): "json",
    }
