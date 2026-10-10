"""`SqlAlchemyInvoiceReads`: the issue fast path and the paged invoice list (`design.md` 9.4).

Each call opens and closes its own short session pinned `READ COMMITTED`. A plain `SELECT` never
waits for a row lock and takes none (L9, L19); nothing here writes (BI15).

* `find_by_order_reference` is `load_invoice` on that session: the issue path's fast path;
  `find_by_id`, `find_by_invoice_reference` and `find_payment_by_reference` are the payment path's
  identity resolution and R48 fast path (feature 22), the same shape.
* `list`: the optional exact, case-sensitive filters; `invoice_date <= now - issued_before_minutes`
  (inclusive) against the `now` the CALLER supplies, never read here; `ORDER BY invoice_date DESC,
  invoice_reference DESC`; and one `count()` over the same filters. Lines are not read.
* **G1 (`BI37`).** A page whose offset exceeds `2**63 - 1` is clamped to it (asyncpg refuses an
  offset of `2**63` with SQLSTATE `22000`; `2**63 - 1` returns no rows: measured), and a cutoff
  before year 1 (`OverflowError`, caught at the one statement that raises it) means no invoice can
  qualify: the page has no items and the true total of zero matching rows.
"""

from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, false, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from otc_billing.application.messages import InvoicePage
from otc_billing.domain.invoice_snapshot import InvoiceSnapshot, PaymentSnapshot
from otc_billing.domain.invoice_state import InvoiceStatus
from otc_billing.infrastructure.persistence import invoice_mapper
from otc_billing.infrastructure.persistence.invoice_repository import (
    load_invoice,
    load_invoice_by_id,
    load_invoice_by_reference,
    load_payment_by_reference,
)
from otc_billing.infrastructure.persistence.models import Invoice as InvoiceRow
from otc_shared_kernel import UniqueId

MAX_OFFSET = (1 << 63) - 1  # PostgreSQL's bigint OFFSET; asyncpg refuses anything above


class SqlAlchemyInvoiceReads:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def find_by_order_reference(self, order_reference: str) -> InvoiceSnapshot | None:
        async with self._sessions() as session:
            await session.connection(execution_options={"isolation_level": "READ COMMITTED"})
            return await load_invoice(session, order_reference)

    async def find_by_id(self, invoice_id: UniqueId) -> InvoiceSnapshot | None:
        async with self._sessions() as session:
            await session.connection(execution_options={"isolation_level": "READ COMMITTED"})
            return await load_invoice_by_id(session, invoice_id)

    async def find_by_invoice_reference(self, invoice_reference: str) -> InvoiceSnapshot | None:
        async with self._sessions() as session:
            await session.connection(execution_options={"isolation_level": "READ COMMITTED"})
            return await load_invoice_by_reference(session, invoice_reference)

    async def find_payment_by_reference(self, payment_reference: str) -> PaymentSnapshot | None:
        async with self._sessions() as session:
            await session.connection(execution_options={"isolation_level": "READ COMMITTED"})
            return await load_payment_by_reference(session, payment_reference)

    async def list(
        self,
        *,
        page: int,
        page_size: int,
        status: InvoiceStatus | None,
        retailer_code: str | None,
        company_code: str | None,
        order_reference: str | None,
        issued_before_minutes: int | None,
        now: datetime,
    ) -> InvoicePage:
        filters: list[ColumnElement[bool]] = []
        if status is not None:
            filters.append(InvoiceRow.status == status.value)
        if retailer_code is not None:
            filters.append(InvoiceRow.retailer_code == retailer_code)
        if company_code is not None:
            filters.append(InvoiceRow.company_code == company_code)
        if order_reference is not None:
            filters.append(InvoiceRow.order_reference == order_reference)
        if issued_before_minutes is not None:
            try:
                cutoff = now - timedelta(minutes=issued_before_minutes)
            except OverflowError:
                # before year 1 (or beyond a C int): no invoice can qualify
                filters.append(false())
            else:
                filters.append(InvoiceRow.invoice_date <= cutoff)
        async with self._sessions() as session:
            await session.connection(execution_options={"isolation_level": "READ COMMITTED"})
            total = await session.scalar(
                select(func.count()).select_from(InvoiceRow).where(*filters)
            )
            rows = (
                await session.scalars(
                    select(InvoiceRow)
                    .where(*filters)
                    .order_by(InvoiceRow.invoice_date.desc(), InvoiceRow.invoice_reference.desc())
                    .offset(min((page - 1) * page_size, MAX_OFFSET))
                    .limit(page_size)
                )
            ).all()
        return InvoicePage(
            items=tuple(invoice_mapper.invoice_view(row) for row in rows),
            page=page,
            page_size=page_size,
            total=total or 0,
        )
