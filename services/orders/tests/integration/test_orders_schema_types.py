"""Acceptance 2 - the types (unit: every column of every table), read from the LIVE database.

The expected map is a literal. It is never derived from SQLAlchemy metadata: a test that asks the
ORM what the ORM believes proves nothing about the engine. Sources: the plan's type-delta table
(uuid, timestamptz(3), varchar states, bigint money, identity outbox.seq, json payloads) and
`Order To Cash - Databases.EN.md` section 4 for names, lengths and nullability.

Each entry is (format_type(), nullable, extra). `extra` is "" or "identity:ALWAYS" or the column
default as the catalog prints it. `format_type` comes from pg_attribute, so it carries the
`timestamp(3) with time zone` precision that information_schema reports separately.
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
TEXT = "text"


def V(n: int) -> str:
    return f"character varying({n})"


EXPECTED: dict[str, dict[str, tuple[str, bool, str]]] = {
    "currencies": {
        "id": (UUID, False, ""),
        "code": (V(3), False, ""),
        "iso_number": (V(3), False, ""),
        "symbol": (V(5), False, ""),
        "decimal_points": (INT, False, ""),
        "created_at": (TS3, False, ""),
        "updated_at": (TS3, False, ""),
    },
    "products": {
        "id": (UUID, False, ""),
        "code": (V(30), False, ""),
        "ean": (V(13), False, ""),
        "name": (V(100), False, ""),
        "description": (V(255), False, ""),
        "price": (BIGINT, False, ""),
        "currency_id": (UUID, False, ""),
        "disabled_at": (TS3, True, ""),
        "created_at": (TS3, False, ""),
        "updated_at": (TS3, False, ""),
    },
    "retailers": {
        "id": (UUID, False, ""),
        "code": (V(20), False, ""),
        "name": (V(100), False, ""),
        "country": (V(2), False, ""),
        "vat": (V(15), False, ""),
        "gln": (V(13), False, ""),
        "currency_id": (UUID, False, ""),
        "disabled_at": (TS3, True, ""),
        "created_at": (TS3, False, ""),
        "updated_at": (TS3, False, ""),
    },
    "companies": {
        "id": (UUID, False, ""),
        "code": (V(20), False, ""),
        "name": (V(100), False, ""),
        "country": (V(2), False, ""),
        "vat": (V(15), False, ""),
        "gln": (V(13), False, ""),
        "currency_id": (UUID, False, ""),
        "disabled_at": (TS3, True, ""),
        "created_at": (TS3, False, ""),
        "updated_at": (TS3, False, ""),
    },
    "orders": {
        "id": (UUID, False, ""),
        "order_reference": (V(20), False, ""),
        "request_id": (UUID, True, ""),
        "order_date": (TS3, False, ""),
        "company_id": (UUID, False, ""),
        "retailer_id": (UUID, False, ""),
        "currency_id": (UUID, False, ""),
        "initial_amount": (BIGINT, False, ""),
        "initial_discount": (BIGINT, False, ""),
        "total_amount": (BIGINT, False, ""),
        "status": (V(20), False, ""),
        "cancellation_reason": (V(100), True, ""),
        "notes": (TEXT, True, ""),
        "created_at": (TS3, False, ""),
        "updated_at": (TS3, False, ""),
    },
    "order_items": {
        "id": (UUID, False, ""),
        "order_id": (UUID, False, ""),
        "product_id": (UUID, False, ""),
        "description": (V(255), False, ""),
        "price": (BIGINT, False, ""),
        "quantity": (INT, False, ""),
        "discount": (BIGINT, False, ""),
        "created_at": (TS3, False, ""),
        "updated_at": (TS3, False, ""),
    },
    "order_number_sequences": {
        "id": (INT, False, ""),
        "next_value": (INT, False, ""),
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
    "saga_commands": {
        "id": (UUID, False, ""),
        "order_id": (UUID, False, ""),
        "order_reference": (V(20), False, ""),
        "command": (V(30), False, ""),
        "payload": (JSON, False, ""),
        "triggering_event_id": (UUID, False, ""),
        "status": (V(10), False, "'pending'::character varying"),
        "attempts": (INT, False, "0"),
        "last_error": (TEXT, True, ""),
        "next_attempt_at": (TS3, True, ""),
        "created_at": (TS3, False, ""),
        "updated_at": (TS3, False, ""),
        "sent_at": (TS3, True, ""),
    },
    "saga_ignored_facts": {
        "id": (UUID, False, ""),
        "event_id": (UUID, False, ""),
        "event_type": (V(60), False, ""),
        "order_id": (UUID, True, ""),
        "correlation_id": (UUID, False, ""),
        "observed_status": (V(20), True, ""),
        "expected_status": (V(20), True, ""),
        "marker": (V(20), False, ""),
        "recorded_at": (TS3, False, ""),
    },
}

# The money columns (minor units). Derived with:
#   sed -n 41,150p "Order To Cash - Databases.EN.md" | grep -n "cents"
# which returns exactly these six rows of otc_orders (products.price; orders.initial_amount,
# initial_discount, total_amount; order_items.price, discount). A seventh would be a new row there.
MONEY_COLUMNS = [
    ("products", "price"),
    ("orders", "initial_amount"),
    ("orders", "initial_discount"),
    ("orders", "total_amount"),
    ("order_items", "price"),
    ("order_items", "discount"),
]

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


async def test_money_columns_are_bigint(migrated_db: Any) -> None:
    """#8 id 44 (money shipped as `int`): the literal money population is `bigint` in the engine."""
    rows = {(r["table_name"], r["column_name"]): r for r in await _live(migrated_db.dsn)}
    assert len(set(MONEY_COLUMNS)) == 6
    wrong = {
        pair: rows[pair]["data_type"]
        for pair in MONEY_COLUMNS
        if rows[pair]["data_type"] != "bigint"
    }
    assert wrong == {}


async def test_payload_columns_are_json_not_jsonb(migrated_db: Any) -> None:
    rows = {
        (r["table_name"], r["column_name"]): r["data_type"] for r in await _live(migrated_db.dsn)
    }
    assert {k: v for k, v in rows.items() if v in ("json", "jsonb")} == {
        ("outbox", "payload"): "json",
        ("saga_commands", "payload"): "json",
    }
