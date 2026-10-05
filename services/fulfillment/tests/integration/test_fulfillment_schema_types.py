"""Acceptance 4 - the types (unit: every column of every table), read from the LIVE database.

The expected map is a literal. It is never derived from SQLAlchemy metadata: a test that asks the
ORM what the ORM believes proves nothing about the engine. Sources: the plan's type-delta table
(uuid, timestamptz(3), varchar states, identity outbox.seq, json payloads) and
`Order To Cash - Databases.EN.md` section 5 for names, lengths and nullability.

Each entry is (format_type(), nullable, extra). `extra` is "" or "identity:ALWAYS" or the column
default as the catalog prints it. `format_type` comes from pg_attribute, so it carries the
`timestamp(3) with time zone` precision that information_schema reports separately.

`reservations.retailer_code` has no length in section 5 ("varchar"): `varchar(20)` follows #8
(`InitialCreate.cs`) and #7 (`0000_nappy_mad_thinker.sql`), which agree. `despatches.despatch_date`
is `timestamptz(3)` like every instant (the document says `datetime`).
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


def V(n: int) -> str:
    return f"character varying({n})"


EXPECTED: dict[str, dict[str, tuple[str, bool, str]]] = {
    "stock": {
        "id": (UUID, False, ""),
        "company_code": (V(20), False, ""),
        "product_code": (V(30), False, ""),
        "units": (INT, False, ""),
        "reserved_units": (INT, False, ""),
        "low_stock_threshold": (INT, False, ""),
        "created_at": (TS3, False, ""),
        "updated_at": (TS3, False, ""),
    },
    "reservations": {
        "id": (UUID, False, ""),
        "stock_id": (UUID, False, ""),
        "company_code": (V(20), False, ""),
        "retailer_code": (V(20), False, ""),
        "product_code": (V(30), False, ""),
        "order_reference": (V(20), False, ""),
        "units": (INT, False, ""),
        "status": (V(20), False, ""),
        "created_at": (TS3, False, ""),
        "updated_at": (TS3, False, ""),
    },
    "despatches": {
        "id": (UUID, False, ""),
        "despatch_reference": (V(20), False, ""),
        "despatch_date": (TS3, False, ""),
        "company_code": (V(20), False, ""),
        "retailer_code": (V(20), False, ""),
        "order_reference": (V(20), False, ""),
        "created_at": (TS3, False, ""),
        "updated_at": (TS3, False, ""),
    },
    "despatch_items": {
        "id": (UUID, False, ""),
        "despatch_id": (UUID, False, ""),
        "product_code": (V(30), False, ""),
        "units": (INT, False, ""),
        "created_at": (TS3, False, ""),
        "updated_at": (TS3, False, ""),
    },
    "despatch_number_sequences": {
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
}

# The money columns (minor units) of otc_fulfillment: NONE. Derived with:
#   sed -n 194,240p "Order To Cash - Databases.EN.md" | grep -c -i "cents"
# which prints 0 (section 5 is lines 194-240, before `## 6`; the same grep over lines
# 41-150, the otc_orders section, finds the six orders rows). So the only `bigint` column of this
# database is the outbox sequence, and a `bigint` anywhere else is a type this test refuses.
MONEY_COLUMNS: list[tuple[str, str]] = []
BIGINT_COLUMNS = {("outbox", "seq")}

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


async def test_fulfillment_has_no_money_columns_and_one_bigint(migrated_db: Any) -> None:
    rows = {(r["table_name"], r["column_name"]): r for r in await _live(migrated_db.dsn)}
    assert MONEY_COLUMNS == []
    assert {pair for pair, r in rows.items() if r["data_type"] == "bigint"} == BIGINT_COLUMNS


async def test_payload_columns_are_json_not_jsonb(migrated_db: Any) -> None:
    rows = {
        (r["table_name"], r["column_name"]): r["data_type"] for r in await _live(migrated_db.dsn)
    }
    assert {k: v for k, v in rows.items() if v in ("json", "jsonb")} == {
        ("outbox", "payload"): "json",
    }
