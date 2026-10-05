"""Acceptance 4 (range guard) - every integer column's range is enforced at the write boundary
(unit: the 11 integer columns of `otc_billing`).

The population of integer columns is read from the LIVE catalog (not from metadata) and compared
with a literal; each one, looked up through the mapped class, must refuse max + 1 with a
`DomainError`, and `invoice_items.units` alone must refuse it with the QUANTITY code. Then
`invoice_items.units` (int32) and the money columns (int64) are driven through a real session: max
is stored and read back, max + 1 raises the domain refusal and never reaches asyncpg.

Classification of the 11 integer columns (feature 11):
* QUANTITY (code `quantity.out_of_range`): `invoice_items.units`, the only unit count.
* MONEY, minor units, `bigint` (generic `storage.integer_out_of_range`): `credits.credit_limit`,
  `credit_items.amount`, `invoices.amount/discount/total_amount`, `invoice_items.price`,
  `payments.amount`. The domain's `Money` is bounded to int64; the guard is the column's own width.
* COUNTER (generic code): `invoice_number_sequences.id/next_value`, `outbox.seq`.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import asyncpg
import pytest
from sqlalchemy import insert, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from otc_billing.infrastructure.persistence.models import (
    Base,
    Invoice,
    InvoiceItem,
)
from otc_billing.infrastructure.persistence.range_guards import (
    IntegerOutOfRangeError,
    QuantityOutOfRangeError,
)
from otc_shared_kernel import DomainError

pytestmark = pytest.mark.integration

INT_COLUMNS = {
    ("credits", "credit_limit", "bigint"),
    ("credit_items", "amount", "bigint"),
    ("invoices", "amount", "bigint"),
    ("invoices", "discount", "bigint"),
    ("invoices", "total_amount", "bigint"),
    ("invoice_items", "units", "integer"),
    ("invoice_items", "price", "bigint"),
    ("invoice_number_sequences", "id", "integer"),
    ("invoice_number_sequences", "next_value", "integer"),
    ("payments", "amount", "bigint"),
    ("outbox", "seq", "bigint"),
}
QUANTITY_COLUMNS = {("invoice_items", "units")}
LIMITS = {"integer": 2**31 - 1, "bigint": 2**63 - 1}
NOW = datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC)
MAX = 2**31 - 1
MAX64 = 2**63 - 1


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
    assert len(live) == 11

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


def _invoice(invoice_id: uuid.UUID, amount: int = 1) -> Invoice:
    return Invoice(
        id=invoice_id,
        invoice_reference="INV-000001",
        invoice_date=NOW,
        company_code="CO",
        retailer_code="RET",
        order_reference="ORD-000001",
        amount=amount,
        discount=0,
        total_amount=amount,
        currency_code="EUR",
        status="issued",
        created_at=NOW,
        updated_at=NOW,
    )


def _item(invoice_id: uuid.UUID, units: int, price: int = 1) -> InvoiceItem:
    return InvoiceItem(
        id=uuid.uuid4(),
        invoice_id=invoice_id,
        product_code="PRD",
        units=units,
        price=price,
        created_at=NOW,
        updated_at=NOW,
    )


async def test_units_max_round_trips_and_max_plus_one_is_a_domain_error(
    engine: AsyncEngine,
) -> None:
    invoice_id = uuid.uuid4()
    async with AsyncSession(engine) as session, session.begin():
        session.add(_invoice(invoice_id))
        await session.flush()
        session.add(_item(invoice_id, MAX))
    async with engine.connect() as conn:
        stored = (await conn.execute(text("SELECT units FROM invoice_items"))).scalar_one()
    assert stored == MAX

    caught: Any = None
    try:
        async with AsyncSession(engine) as session, session.begin():
            session.add(_item(invoice_id, MAX + 1))
    except Exception as exc:
        caught = exc
    assert type(caught) is QuantityOutOfRangeError, (
        f"got {type(caught).__module__}.{type(caught).__name__}: {caught}"
    )
    assert isinstance(caught, DomainError)
    assert caught.code == "quantity.out_of_range"
    assert "invoice_items.units" in str(caught)


async def test_money_max_round_trips_as_bigint_and_max_plus_one_is_a_generic_domain_error(
    engine: AsyncEngine,
) -> None:
    invoice_id = uuid.uuid4()
    async with AsyncSession(engine) as session, session.begin():
        session.add(_invoice(invoice_id, amount=MAX64))
        await session.flush()
        session.add(_item(invoice_id, units=1, price=MAX64))
    async with engine.connect() as conn:
        stored = (await conn.execute(text("SELECT amount, total_amount FROM invoices"))).one()
        price = (await conn.execute(text("SELECT price FROM invoice_items"))).scalar_one()
    assert (stored[0], stored[1], price) == (MAX64, MAX64, MAX64)  # beyond int32: a bigint column

    caught: Any = None
    try:
        async with AsyncSession(engine) as session, session.begin():
            session.add(_invoice(uuid.uuid4(), amount=MAX64 + 1))
    except Exception as exc:
        caught = exc
    assert type(caught) is IntegerOutOfRangeError, (
        f"got {type(caught).__module__}.{type(caught).__name__}: {caught}"
    )
    assert caught.code == "storage.integer_out_of_range"
    assert "invoices.amount" in str(caught)


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
    invoice_id = uuid.uuid4()
    async with AsyncSession(engine) as session, session.begin():
        session.add(_invoice(invoice_id))
        await session.flush()
        session.add(_item(invoice_id, 1))
    row = {
        "id": uuid.uuid4(),
        "invoice_id": invoice_id,
        "product_code": "PRD",
        "units": MAX + 1,
        "price": 1,
        "created_at": NOW,
        "updated_at": NOW,
    }

    async def attempt() -> None:
        async with AsyncSession(engine) as session, session.begin():
            if path == "insert_values":
                await session.execute(insert(InvoiceItem).values(**row))
            elif path == "insert_list_of_dicts":
                await session.execute(insert(InvoiceItem), [row])
            elif path == "update_model":
                await session.execute(update(InvoiceItem).values(units=MAX + 1))
            else:
                await session.run_sync(lambda sync: sync.bulk_insert_mappings(InvoiceItem, [row]))

    with pytest.raises(DBAPIError) as raised:
        await attempt()
    assert not isinstance(raised.value, DomainError)
    assert "out of int32 range" in str(raised.value.orig)
