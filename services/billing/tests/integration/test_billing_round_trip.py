"""Acceptance 4 (round trip) - a round trip per table (unit: each of the 8 tables of `otc_billing`).

Every column of one row per table is written through the ORM with a value DISTINCT from every other
column's (distinct uuids, distinct strings, distinct integers, distinct whole-millisecond instants),
then read back by an independent asyncpg connection (not the ORM that wrote it) and compared with
the literal that was written, and read back through the ORM too. A column the model maps to the
wrong attribute or swaps with another cannot pass: no two columns hold the same value. Money
values are above 2**32 so a narrowed column cannot hold them.

Instants: the engine returns aware UTC and keeps millisecond precision (measured in feature 9;
the rounding of a sub-millisecond input is pinned in `test_billing_json_and_timestamps.py`).
One instant is written with a +02:00 offset and must come back as the same instant in UTC.
`outbox.seq` is GENERATED ALWAYS (the engine assigns it), so it is asserted separately.
"""

import uuid
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import asyncpg
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from otc_billing.infrastructure.persistence.models import (
    Base,
    Credit,
    CreditItem,
    Invoice,
    InvoiceItem,
    InvoiceNumberSequence,
    Outbox,
    Payment,
    ProcessedEvent,
)

pytestmark = pytest.mark.integration


def _id(n: int) -> uuid.UUID:
    return uuid.UUID(int=0xB111000 + n)


def _ts(n: int) -> datetime:
    """A whole-millisecond UTC instant that no other `n` shares."""
    return datetime(2026, 10, 5, 12, n, n, n * 1000 + 7000, tzinfo=UTC)


BIG = 2**32  # every money value is above the int32 range

PAYLOAD = '{"zeta":1,"alpha":{"b":"ñ","a":[1,2]}}'

# table -> (model, the row as the application writes it). `seq` is excluded for outbox.
ROWS: dict[str, tuple[type[Base], dict[str, Any]]] = {
    "credits": (
        Credit,
        {
            "id": _id(1),
            "code": "CRL-0001",
            "retailer_code": "RET-C",
            "company_code": "CO-C",
            "credit_limit": BIG + 1101,
            "currency_code": "EUR",
            "created_at": _ts(1),
            "updated_at": _ts(2),
        },
    ),
    "credit_items": (
        CreditItem,
        {
            "id": _id(2),
            "credit_id": _id(1),
            "order_reference": "ORD-000042",
            "amount": BIG + 2202,
            "type": "hold",
            "credit_date": _ts(3),
            "created_at": _ts(4),
            "updated_at": _ts(5),
        },
    ),
    "invoices": (
        Invoice,
        {
            "id": _id(3),
            "invoice_reference": "INV-000007",
            "invoice_date": _ts(6),
            "company_code": "CO-I",
            "retailer_code": "RET-I",
            "order_reference": "ORD-000099",
            "amount": BIG + 3303,
            "discount": BIG + 3404,
            "total_amount": BIG + 3505,
            "currency_code": "USD",
            "status": "issued",
            "paid_at": _ts(7),
            "created_at": _ts(8),
            "updated_at": _ts(9),
        },
    ),
    "invoice_items": (
        InvoiceItem,
        {
            "id": _id(4),
            "invoice_id": _id(3),
            "product_code": "PRD-I",
            "units": 4606,
            "price": BIG + 4707,
            "created_at": _ts(10),
            "updated_at": _ts(11),
        },
    ),
    "invoice_number_sequences": (InvoiceNumberSequence, {"id": 1, "next_value": 5808}),
    "payments": (
        Payment,
        {
            "id": _id(5),
            "payment_reference": "PAY-0001",
            "invoice_id": _id(3),
            "amount": BIG + 6909,
            "currency_code": "GBP",
            "value_date": _ts(12),
            "source": "robot",
            "created_at": _ts(13),
        },
    ),
    "outbox": (
        Outbox,
        {
            "id": _id(6),
            "event_id": _id(7),
            "event_type": "invoice.issued.v1",
            "aggregate_id": _id(8),
            "correlation_id": _id(9),
            "causation_id": _id(10),
            "payload": PAYLOAD,
            "occurred_at": _ts(14),
            "published_at": _ts(15),
            "created_at": _ts(16),
            "trace_parent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",
        },
    ),
    "processed_events": (
        ProcessedEvent,
        {
            "id": _id(11),
            "event_id": _id(12),
            "consumer": "billing.invoice-issue",
            "processed_at": _ts(17),
            "created_at": _ts(18),
        },
    ),
}

# parent rows a table's foreign keys need, written (and flushed) first: no relationship() is mapped,
# so the unit of work cannot order the inserts
PARENTS = {
    "credit_items": ("credits",),
    "invoice_items": ("invoices",),
    "payments": ("invoices",),
}


def test_the_literal_rows_cover_every_mapped_table_and_use_distinct_values() -> None:
    assert set(ROWS) == {m.class_.__tablename__ for m in Base.registry.mappers}
    for table, (model, row) in ROWS.items():
        mapped = {a.key for a in model.__mapper__.column_attrs} - {"seq"}
        assert set(row) == mapped, table  # no column left unwritten, none invented
    # distinct within a row: no two string or instant values are equal
    for table, (_, row) in ROWS.items():
        text_like = [v for k, v in row.items() if isinstance(v, str | datetime) and k != "id"]
        assert len(text_like) == len(set(text_like)), table


@pytest.mark.parametrize("table", sorted(ROWS))
async def test_every_column_of_the_table_round_trips(
    table: str, engine: AsyncEngine, migrated_db: Any
) -> None:
    model, row = ROWS[table]
    written = dict(row)
    if table == "outbox":
        # one instant written in another offset must come back as the same instant, UTC
        written["occurred_at"] = row["occurred_at"].astimezone(timezone(timedelta(hours=2)))
    async with AsyncSession(engine) as session, session.begin():
        for parent in PARENTS.get(table, ()):
            session.add(ROWS[parent][0](**ROWS[parent][1]))
            await session.flush()
        session.add(model(**written))

    conn = await asyncpg.connect(migrated_db.dsn)
    try:
        record = await conn.fetchrow(
            f"SELECT *, payload::text AS payload_text FROM {table} WHERE id = $1"  # noqa: S608
            if table == "outbox"
            else f"SELECT * FROM {table} WHERE id = $1",  # noqa: S608
            row["id"],
        )
    finally:
        await conn.close()
    assert record is not None
    via_sql = dict(record)
    if table == "outbox":
        assert isinstance(via_sql.pop("seq"), int)
        via_sql["payload"] = via_sql.pop("payload_text")
    assert via_sql == row

    async with AsyncSession(engine) as session:
        loaded = (
            await session.execute(select(model).where(model.__table__.c.id == row["id"]))
        ).scalar_one()
        via_orm = {a.key: getattr(loaded, a.key) for a in model.__mapper__.column_attrs}
    via_orm.pop("seq", None)
    assert via_orm == row
    for value in via_orm.values():
        if isinstance(value, datetime):
            assert value.utcoffset() == timedelta(0)


async def test_outbox_seq_is_assigned_by_the_engine_and_strictly_increases(
    engine: AsyncEngine,
) -> None:
    model, row = ROWS["outbox"]
    async with AsyncSession(engine) as session, session.begin():
        for n in (1, 2, 3):
            session.add(model(**{**row, "id": _id(100 + n), "event_id": _id(200 + n)}))
    async with AsyncSession(engine) as session:
        seqs = (await session.execute(select(Outbox.seq).order_by(Outbox.seq))).scalars().all()
    assert list(seqs) == [1, 2, 3]
