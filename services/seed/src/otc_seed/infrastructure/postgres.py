"""The three relational targets: orders, fulfillment and billing.

Idempotence mechanism (per table, identical for all of them): rows are keyed by their
DETERMINISTIC primary key; a row whose id is already present is NOT written again (existing ids are
read first, and the insert is still `ON CONFLICT (id) DO NOTHING` so a concurrent seed cannot make
it fail). "Do nothing" rather than "update": stock units, credit limits and order status are live
state after the first live order, and re-running the seed must not reset them. A second run
therefore executes no INSERT at all, and `outbox.seq` (an identity column) is not burned either.

Write path of every integer: ONE statement builder, `insert_missing`, below; each row passes
`ensure_row_in_range` before any statement exists (`range_check.py`).

Each target writes in ONE transaction: a database ends up fully seeded or untouched.
"""

import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import MetaData, Table, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from otc_seed.application.dataset import SeedDataset
from otc_seed.domain.clock import MASTER_DATA_TIMESTAMP
from otc_seed.domain.data.companies import company_by_code
from otc_seed.domain.data.currencies import currency_id_by_code
from otc_seed.domain.data.products import product_by_code
from otc_seed.domain.data.retailers import retailer_by_code
from otc_seed.domain.data.sagas import OutboxFixture, stock_row_id
from otc_seed.domain.deterministic import deterministic_id
from otc_seed.infrastructure import tables
from otc_seed.infrastructure.payloads import payload_json
from otc_seed.infrastructure.range_check import ensure_row_in_range
from otc_seed.infrastructure.schema_check import schema_problems

type Row = dict[str, Any]


class SchemaDriftError(RuntimeError):
    """The database is not what the seed's table definitions say it is."""


def _u(value: str) -> uuid.UUID:
    return uuid.UUID(value)


async def insert_missing(conn: Any, table: Table, rows: Sequence[Row]) -> int:
    """Insert the rows whose `id` is not present yet; return how many were missing.

    THE ONLY INSERT of the seed: every integer it writes was range-checked here first.
    """
    if not rows:
        return 0
    for row in rows:
        ensure_row_in_range(table, row)
    ids = [row["id"] for row in rows]
    present = set((await conn.execute(select(table.c.id).where(table.c.id.in_(ids)))).scalars())
    missing = [row for row in rows if row["id"] not in present]
    if missing:
        await conn.execute(pg_insert(table).on_conflict_do_nothing(index_elements=["id"]), missing)
    return len(missing)


def _outbox_row(fixture: OutboxFixture) -> Row:
    return {
        "id": _u(fixture.id),
        "event_id": _u(fixture.event_id),
        "event_type": fixture.event_type,
        "aggregate_id": _u(fixture.aggregate_id),
        "correlation_id": _u(fixture.correlation_id),
        "causation_id": _u(fixture.causation_id),
        "payload": payload_json(fixture.event_type, fixture.payload),
        "occurred_at": fixture.occurred_at,
        "published_at": fixture.published_at,
        "created_at": fixture.occurred_at,
    }


def _stamped(created: datetime, updated: datetime | None = None) -> Row:
    return {"created_at": created, "updated_at": created if updated is None else updated}


class _PostgresTarget:
    name: str
    _metadata: MetaData

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def verify(self) -> None:
        async with self._engine.connect() as conn:
            problems = await schema_problems(conn, self._metadata)
        if problems:
            raise SchemaDriftError(f"{self.name}: " + "; ".join(problems))

    async def seed(self, dataset: SeedDataset) -> Mapping[str, int]:
        added: dict[str, int] = {}
        async with self._engine.begin() as conn:
            for table, rows in self._rows(dataset):
                added[table.name] = await insert_missing(conn, table, rows)
        return added

    def _rows(self, dataset: SeedDataset) -> list[tuple[Table, list[Row]]]:
        raise NotImplementedError


class OrdersTarget(_PostgresTarget):
    name = "orders"
    _metadata = tables.ORDERS_METADATA

    def _rows(self, dataset: SeedDataset) -> list[tuple[Table, list[Row]]]:
        ts = MASTER_DATA_TIMESTAMP
        currencies = [
            {
                "id": _u(c.id),
                "code": c.code,
                "iso_number": c.iso_number,
                "symbol": c.symbol,
                "decimal_points": c.decimal_points,
                **_stamped(ts),
            }
            for c in dataset.currencies
        ]
        products = [
            {
                "id": _u(p.id),
                "code": p.code,
                "ean": p.ean,
                "name": p.name,
                "description": p.description,
                "price": p.price,
                "currency_id": _u(currency_id_by_code(p.currency_code)),
                "disabled_at": None,
                **_stamped(ts),
            }
            for p in dataset.products
        ]

        def party(p: Any) -> Row:
            return {
                "id": _u(p.id),
                "code": p.code,
                "name": p.name,
                "country": p.country,
                "vat": p.vat,
                "gln": p.gln,
                "currency_id": _u(currency_id_by_code(p.currency_code)),
                "disabled_at": None,
                **_stamped(ts),
            }

        orders: list[Row] = []
        items: list[Row] = []
        outbox: list[Row] = []
        for saga in dataset.sagas:
            orders.append(
                {
                    "id": _u(saga.order_id),
                    "order_reference": saga.order_reference,
                    "order_date": saga.order_date,
                    "company_id": _u(company_by_code(saga.company_code).id),
                    "retailer_id": _u(retailer_by_code(saga.retailer_code).id),
                    "currency_id": _u(currency_id_by_code(saga.currency)),
                    "initial_amount": saga.initial_amount,
                    "initial_discount": saga.initial_discount,
                    "total_amount": saga.total_amount,
                    "status": saga.status,
                    "cancellation_reason": saga.cancellation_reason,
                    "notes": saga.notes,
                    **_stamped(saga.order_date, saga.updated_at),
                }
            )
            items.extend(
                {
                    "id": _u(deterministic_id(f"order:{saga.sequence}:item:{line.product_code}")),
                    "order_id": _u(saga.order_id),
                    "product_id": _u(product_by_code(line.product_code).id),
                    "description": line.description,
                    "price": line.unit_price,
                    "quantity": line.quantity,
                    "discount": line.line_discount,
                    **_stamped(saga.order_date),
                }
                for line in saga.lines
            )
            outbox.extend(_outbox_row(f) for f in saga.orders_outbox)
        return [
            (tables.CURRENCIES, currencies),
            (tables.PRODUCTS, products),
            (tables.RETAILERS, [party(r) for r in dataset.retailers]),
            (tables.COMPANIES, [party(c) for c in dataset.companies]),
            (tables.ORDERS, orders),
            (tables.ORDER_ITEMS, items),
            (tables.ORDERS_OUTBOX, outbox),
        ]


class FulfillmentTarget(_PostgresTarget):
    name = "fulfillment"
    _metadata = tables.FULFILLMENT_METADATA

    def _rows(self, dataset: SeedDataset) -> list[tuple[Table, list[Row]]]:
        stock = [
            {
                "id": _u(s.id),
                "company_code": s.company_code,
                "product_code": s.product_code,
                "units": s.units,
                "reserved_units": s.reserved_units,
                "low_stock_threshold": s.low_stock_threshold,
                **_stamped(MASTER_DATA_TIMESTAMP),
            }
            for s in dataset.stock
        ]
        reservations: list[Row] = []
        despatches: list[Row] = []
        despatch_items: list[Row] = []
        outbox: list[Row] = []
        for saga in dataset.sagas:
            reservations.extend(
                {
                    "id": _u(r.id),
                    "stock_id": _u(stock_row_id(r.company_code, r.product_code)),
                    "company_code": r.company_code,
                    "retailer_code": r.retailer_code,
                    "product_code": r.product_code,
                    "order_reference": saga.order_reference,
                    "units": r.units,
                    "status": r.status,
                    **_stamped(r.created_at, r.updated_at),
                }
                for r in saga.reservations
            )
            if saga.despatch is not None:
                d = saga.despatch
                despatches.append(
                    {
                        "id": _u(d.id),
                        "despatch_reference": d.despatch_reference,
                        "despatch_date": d.despatch_date,
                        "company_code": d.company_code,
                        "retailer_code": d.retailer_code,
                        "order_reference": saga.order_reference,
                        **_stamped(d.despatch_date),
                    }
                )
                despatch_items.extend(
                    {
                        "id": _u(
                            deterministic_id(
                                f"order:{saga.sequence}:despatch-item:{item.product_code}"
                            )
                        ),
                        "despatch_id": _u(d.id),
                        "product_code": item.product_code,
                        "units": item.units,
                        **_stamped(d.despatch_date),
                    }
                    for item in d.items
                )
            outbox.extend(_outbox_row(f) for f in saga.fulfillment_outbox)
        return [
            (tables.STOCK, stock),
            (tables.RESERVATIONS, reservations),
            (tables.DESPATCHES, despatches),
            (tables.DESPATCH_ITEMS, despatch_items),
            (tables.FULFILLMENT_OUTBOX, outbox),
        ]


class BillingTarget(_PostgresTarget):
    name = "billing"
    _metadata = tables.BILLING_METADATA

    def _rows(self, dataset: SeedDataset) -> list[tuple[Table, list[Row]]]:
        credits = [
            {
                "id": _u(c.id),
                "code": c.code,
                "retailer_code": c.retailer_code,
                "company_code": c.company_code,
                "credit_limit": c.credit_limit,
                "currency_code": c.currency_code,
                **_stamped(MASTER_DATA_TIMESTAMP),
            }
            for c in dataset.credits
        ]
        credit_items: list[Row] = []
        invoices: list[Row] = []
        invoice_items: list[Row] = []
        payments: list[Row] = []
        outbox: list[Row] = []
        for saga in dataset.sagas:
            credit_items.extend(
                {
                    "id": _u(e.id),
                    "credit_id": _u(e.credit_id),
                    "order_reference": e.order_reference,
                    "amount": e.amount,
                    "type": e.type,
                    "credit_date": e.credit_date,
                    **_stamped(e.credit_date),
                }
                for e in saga.credit_ledger_entries
            )
            if saga.invoice is not None:
                inv = saga.invoice
                invoices.append(
                    {
                        "id": _u(inv.id),
                        "invoice_reference": inv.invoice_reference,
                        "invoice_date": inv.invoice_date,
                        "company_code": saga.company_code,
                        "retailer_code": saga.retailer_code,
                        "order_reference": saga.order_reference,
                        "amount": inv.amount,
                        "discount": inv.discount,
                        "total_amount": inv.total_amount,
                        "currency_code": saga.currency,
                        "status": inv.status,
                        "paid_at": inv.paid_at,
                        **_stamped(inv.invoice_date, inv.paid_at),
                    }
                )
                invoice_items.extend(
                    {
                        "id": _u(
                            deterministic_id(
                                f"order:{saga.sequence}:invoice-item:{item.product_code}"
                            )
                        ),
                        "invoice_id": _u(inv.id),
                        "product_code": item.product_code,
                        "units": item.units,
                        "price": item.price,
                        **_stamped(inv.invoice_date),
                    }
                    for item in inv.items
                )
                payments.append(
                    {
                        "id": _u(inv.payment.id),
                        "payment_reference": inv.payment.payment_reference,
                        "invoice_id": _u(inv.id),
                        "amount": inv.payment.amount,
                        "currency_code": saga.currency,
                        "value_date": inv.payment.value_date,
                        "source": inv.payment.source,
                        "created_at": inv.payment.value_date,
                    }
                )
            outbox.extend(_outbox_row(f) for f in saga.billing_outbox)
        return [
            (tables.CREDITS, credits),
            (tables.CREDIT_ITEMS, credit_items),
            (tables.INVOICES, invoices),
            (tables.INVOICE_ITEMS, invoice_items),
            (tables.PAYMENTS, payments),
            (tables.BILLING_OUTBOX, outbox),
        ]
