"""Acceptance 3 - `orders.request_id` (R62) (unit: rows).

A plain unique index on a nullable column: many NULLs insert (PostgreSQL's default NULLS DISTINCT,
unlike #8's MS-SQL, which needed a filtered index), and two equal non-null values are refused.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import asyncpg
import pytest

pytestmark = pytest.mark.integration

NOW = datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC)


async def _insert_order(
    conn: asyncpg.Connection, parents: Any, reference: str, request_id: uuid.UUID | None
) -> None:
    await conn.execute(
        "INSERT INTO orders (id, order_reference, request_id, order_date, company_id, retailer_id,"
        " currency_id, initial_amount, initial_discount, total_amount, status, created_at,"
        " updated_at) VALUES ($1, $2, $3, $4, $5, $6, $7, 1, 0, 1, 'placed', $4, $4)",
        uuid.uuid4(),
        reference,
        request_id,
        NOW,
        parents.company,
        parents.retailer,
        parents.currency,
    )


async def test_r62_two_orders_with_null_request_id_both_insert(
    migrated_db: Any, parents: Any
) -> None:
    conn = await asyncpg.connect(migrated_db.dsn)
    try:
        await _insert_order(conn, parents, "ORD-000001", None)
        await _insert_order(conn, parents, "ORD-000002", None)
        assert await conn.fetchval("SELECT count(*) FROM orders WHERE request_id IS NULL") == 2
    finally:
        await conn.close()


async def test_r62_two_equal_non_null_request_ids_violate_the_unique_index(
    migrated_db: Any, parents: Any
) -> None:
    conn = await asyncpg.connect(migrated_db.dsn)
    same = uuid.uuid4()
    try:
        await _insert_order(conn, parents, "ORD-000001", same)
        with pytest.raises(asyncpg.UniqueViolationError) as raised:
            await _insert_order(conn, parents, "ORD-000002", same)
        assert raised.value.constraint_name == "uq_orders_request_id"
        # a different non-null value is fine, so the index is not simply refusing everything
        await _insert_order(conn, parents, "ORD-000003", uuid.uuid4())
    finally:
        await conn.close()
