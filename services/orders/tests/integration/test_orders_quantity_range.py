"""Acceptance 5 - every integer column's range is enforced at the write boundary (unit: columns).

The population of integer columns is read from the LIVE catalog (not from metadata) and each one,
looked up through the mapped class, must refuse max + 1 with a `DomainError`. Then the quantity
column itself is driven through a real session: max is stored and read back, max + 1 raises the
domain refusal and never reaches asyncpg (no `DataError`, no `StatementError`).
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import asyncpg
import pytest
from sqlalchemy import insert, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from otc_orders.infrastructure.persistence.models import Base, Order, OrderItem
from otc_orders.infrastructure.persistence.range_guards import (
    IntegerOutOfRangeError,
    QuantityOutOfRangeError,
)
from otc_shared_kernel import DomainError

pytestmark = pytest.mark.integration

INT_COLUMNS = {
    ("orders", "initial_amount", "bigint"),
    ("orders", "initial_discount", "bigint"),
    ("orders", "total_amount", "bigint"),
    ("products", "price", "bigint"),
    ("outbox", "seq", "bigint"),
    ("currencies", "decimal_points", "integer"),
    ("order_items", "price", "bigint"),
    ("order_items", "quantity", "integer"),
    ("order_items", "discount", "bigint"),
    ("order_number_sequences", "id", "integer"),
    ("order_number_sequences", "next_value", "integer"),
    ("saga_commands", "attempts", "integer"),
}
LIMITS = {"integer": 2**31 - 1, "bigint": 2**63 - 1}
NOW = datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC)


async def test_every_integer_column_of_the_live_database_is_guarded(migrated_db: Any) -> None:
    conn = await asyncpg.connect(migrated_db.dsn)
    try:
        rows = await conn.fetch(
            "SELECT table_name, column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'public' AND data_type IN ('integer', 'bigint', 'smallint')"
        )
    finally:
        await conn.close()
    live = {(r["table_name"], r["column_name"], r["data_type"]) for r in rows}
    assert live == INT_COLUMNS, f"missing {INT_COLUMNS - live}, extra {live - INT_COLUMNS}"

    classes = {m.class_.__tablename__: m.class_ for m in Base.registry.mappers}
    unguarded = []
    for table, column, data_type in sorted(live):
        high = LIMITS[data_type]
        probe = classes[table]()
        setattr(probe, column, high)  # the column's own max is accepted
        try:
            setattr(probe, column, high + 1)
        except IntegerOutOfRangeError:
            continue
        unguarded.append(f"{table}.{column}")
    assert unguarded == []


async def test_quantity_max_round_trips_and_max_plus_one_is_a_domain_error(
    engine: AsyncEngine, parents: Any
) -> None:
    order_id, item_id = uuid.uuid4(), uuid.uuid4()
    async with AsyncSession(engine) as session, session.begin():
        session.add(
            Order(
                id=order_id,
                order_reference="ORD-000001",
                order_date=NOW,
                company_id=parents.company,
                retailer_id=parents.retailer,
                currency_id=parents.currency,
                initial_amount=1,
                initial_discount=0,
                total_amount=1,
                status="placed",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.add(
            OrderItem(
                id=item_id,
                order_id=order_id,
                product_id=parents.product,
                description="d",
                price=1,
                quantity=2**31 - 1,
                discount=0,
                created_at=NOW,
                updated_at=NOW,
            )
        )
    async with engine.connect() as conn:
        stored = (await conn.execute(text("SELECT quantity FROM order_items"))).scalar_one()
    assert stored == 2**31 - 1

    caught: Any = None
    try:
        async with AsyncSession(engine) as session, session.begin():
            session.add(
                OrderItem(
                    id=uuid.uuid4(),
                    order_id=order_id,
                    product_id=parents.product,
                    description="d",
                    price=1,
                    quantity=2**31,
                    discount=0,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
    except Exception as exc:
        caught = exc
    assert type(caught) is QuantityOutOfRangeError, (
        f"got {type(caught).__module__}.{type(caught).__name__}: {caught}"
    )
    assert isinstance(caught, DomainError)
    assert caught.code == "quantity.out_of_range"


ORM_ENABLED_BYPASSES = (
    "insert_values",
    "insert_list_of_dicts",
    "update_model",
    "bulk_insert_mappings",
)


@pytest.mark.parametrize("path", ORM_ENABLED_BYPASSES)
async def test_residual_orm_enabled_dml_paths_bypass_the_guard_and_only_the_engine_refuses(
    path: str, engine: AsyncEngine, parents: Any
) -> None:
    """Pins the RESIDUAL named in `range_guards.py`: the guard is an ORM attribute event, so every
    ORM-enabled DML path that takes the mapped class bypasses it and surfaces as a driver error
    (not only "Core": `insert(Model)`, `insert(Model)` with a list of dicts, `update(Model)` and
    `bulk_insert_mappings` all take the mapped class). A Phase 8 writer on one of these paths is a
    review finding; this test fails if a bypass is ever closed (then the residual text must go)."""
    order_id = uuid.uuid4()
    async with AsyncSession(engine) as session, session.begin():
        session.add(
            Order(
                id=order_id,
                order_reference="ORD-000001",
                order_date=NOW,
                company_id=parents.company,
                retailer_id=parents.retailer,
                currency_id=parents.currency,
                initial_amount=1,
                initial_discount=0,
                total_amount=1,
                status="placed",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.add(
            OrderItem(
                id=uuid.UUID(int=7),
                order_id=order_id,
                product_id=parents.product,
                description="d",
                price=1,
                quantity=1,
                discount=0,
                created_at=NOW,
                updated_at=NOW,
            )
        )
    row = {
        "id": uuid.uuid4(),
        "order_id": order_id,
        "product_id": parents.product,
        "description": "d",
        "price": 1,
        "quantity": 2**31,
        "discount": 0,
        "created_at": NOW,
        "updated_at": NOW,
    }

    async def attempt() -> None:
        async with AsyncSession(engine) as session, session.begin():
            if path == "insert_values":
                await session.execute(insert(OrderItem).values(**row))
            elif path == "insert_list_of_dicts":
                await session.execute(insert(OrderItem), [row])
            elif path == "update_model":
                await session.execute(update(OrderItem).values(quantity=2**31))
            else:
                await session.run_sync(lambda sync: sync.bulk_insert_mappings(OrderItem, [row]))

    with pytest.raises(DBAPIError) as raised:
        await attempt()
    assert not isinstance(raised.value, DomainError)
    assert "out of int32 range" in str(raised.value.orig)
