"""Acceptance 7 - every integer column's range is enforced at the write boundary (unit: columns).

The population of integer columns is read from the LIVE catalog (not from metadata) and compared
with a literal; each one, looked up through the mapped class, must refuse max + 1 with a
`DomainError`, and the five unit-count columns must refuse it with the QUANTITY code. Then
`stock.units`, `reservations.units` and `despatch_items.units` are driven through a real session:
max is stored and read back, max + 1 raises the domain refusal and never reaches asyncpg.

Classification of `stock.low_stock_threshold`: a QUANTITY (code `quantity.out_of_range`). It is a
unit level, compared against `stock.units` and `reserved_units` by the replenishment rule, and it
overflows as units do; `despatch_number_sequences.*` and `outbox.seq` are counters, not
quantities, so they carry the generic `storage.integer_out_of_range`.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import asyncpg
import pytest
from sqlalchemy import insert, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from otc_fulfillment.infrastructure.persistence.models import (
    Base,
    Despatch,
    DespatchItem,
    Reservation,
    Stock,
)
from otc_fulfillment.infrastructure.persistence.range_guards import (
    IntegerOutOfRangeError,
    QuantityOutOfRangeError,
)
from otc_shared_kernel import DomainError

pytestmark = pytest.mark.integration

INT_COLUMNS = {
    ("stock", "units", "integer"),
    ("stock", "reserved_units", "integer"),
    ("stock", "low_stock_threshold", "integer"),
    ("reservations", "units", "integer"),
    ("despatch_items", "units", "integer"),
    ("despatch_number_sequences", "id", "integer"),
    ("despatch_number_sequences", "next_value", "integer"),
    ("outbox", "seq", "bigint"),
}
QUANTITY_COLUMNS = {
    ("stock", "units"),
    ("stock", "reserved_units"),
    ("stock", "low_stock_threshold"),
    ("reservations", "units"),
    ("despatch_items", "units"),
}
LIMITS = {"integer": 2**31 - 1, "bigint": 2**63 - 1}
NOW = datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC)
MAX = 2**31 - 1


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
    wrong_code = []
    for table, column, data_type in sorted(live):
        high = LIMITS[data_type]
        probe = classes[table]()
        setattr(probe, column, high)  # the column's own max is accepted
        try:
            setattr(probe, column, high + 1)
        except IntegerOutOfRangeError as refusal:
            is_quantity = isinstance(refusal, QuantityOutOfRangeError)
            if is_quantity != ((table, column) in QUANTITY_COLUMNS):
                wrong_code.append(f"{table}.{column}: {refusal.code}")
            continue
        unguarded.append(f"{table}.{column}")
    assert unguarded == []
    assert wrong_code == []


def _stock(stock_id: uuid.UUID, units: int = 1) -> Stock:
    return Stock(
        id=stock_id,
        company_code="CO",
        product_code="PRD",
        units=units,
        reserved_units=0,
        low_stock_threshold=0,
        created_at=NOW,
        updated_at=NOW,
    )


def _reservation(stock_id: uuid.UUID, units: int) -> Reservation:
    return Reservation(
        id=uuid.uuid4(),
        stock_id=stock_id,
        company_code="CO",
        retailer_code="RET",
        product_code="PRD",
        order_reference="ORD-000001",
        units=units,
        status="reserved",
        created_at=NOW,
        updated_at=NOW,
    )


async def test_units_max_round_trips_and_max_plus_one_is_a_domain_error(
    engine: AsyncEngine,
) -> None:
    stock_id = uuid.uuid4()
    async with AsyncSession(engine) as session, session.begin():
        session.add(_stock(stock_id, units=MAX))
        await session.flush()
        session.add(_reservation(stock_id, MAX))
    async with engine.connect() as conn:
        stored = (await conn.execute(text("SELECT units FROM reservations"))).scalar_one()
        stock_units = (await conn.execute(text("SELECT units FROM stock"))).scalar_one()
    assert (stored, stock_units) == (MAX, MAX)

    caught: Any = None
    try:
        async with AsyncSession(engine) as session, session.begin():
            session.add(_reservation(stock_id, MAX + 1))
    except Exception as exc:
        caught = exc
    assert type(caught) is QuantityOutOfRangeError, (
        f"got {type(caught).__module__}.{type(caught).__name__}: {caught}"
    )
    assert isinstance(caught, DomainError)
    assert caught.code == "quantity.out_of_range"
    assert "reservations.units" in str(caught)


ORM_ENABLED_BYPASSES = (
    "insert_values",
    "insert_list_of_dicts",
    "update_model",
    "bulk_insert_mappings",
)


@pytest.mark.parametrize("path", ORM_ENABLED_BYPASSES)
async def test_residual_orm_enabled_dml_paths_bypass_the_guard_and_only_the_engine_refuses(
    path: str, engine: AsyncEngine
) -> None:
    """Pins the RESIDUAL named in `range_guards.py` (see its docstring): the guard is an ORM
    attribute event, so every ORM-enabled DML path that takes the mapped class bypasses it and
    surfaces as a driver error. This test fails if a bypass is ever closed."""
    despatch_id = uuid.uuid4()
    async with AsyncSession(engine) as session, session.begin():
        session.add(
            Despatch(
                id=despatch_id,
                despatch_reference="DES-000001",
                despatch_date=NOW,
                company_code="CO",
                retailer_code="RET",
                order_reference="ORD-000001",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await session.flush()
        session.add(
            DespatchItem(
                id=uuid.UUID(int=7),
                despatch_id=despatch_id,
                product_code="PRD",
                units=1,
                created_at=NOW,
                updated_at=NOW,
            )
        )
    row = {
        "id": uuid.uuid4(),
        "despatch_id": despatch_id,
        "product_code": "PRD",
        "units": MAX + 1,
        "created_at": NOW,
        "updated_at": NOW,
    }

    async def attempt() -> None:
        async with AsyncSession(engine) as session, session.begin():
            if path == "insert_values":
                await session.execute(insert(DespatchItem).values(**row))
            elif path == "insert_list_of_dicts":
                await session.execute(insert(DespatchItem), [row])
            elif path == "update_model":
                await session.execute(update(DespatchItem).values(units=MAX + 1))
            else:
                await session.run_sync(lambda sync: sync.bulk_insert_mappings(DespatchItem, [row]))

    with pytest.raises(DBAPIError) as raised:
        await attempt()
    assert not isinstance(raised.value, DomainError)
    assert "out of int32 range" in str(raised.value.orig)
