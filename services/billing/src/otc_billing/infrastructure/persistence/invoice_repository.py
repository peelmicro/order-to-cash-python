"""`SqlAlchemyInvoiceRepository`: the invoice, its lines and its fact (R45; B7; design 6.3, 9.1).

* `find_by_order_reference` is a plain SELECT. Called INSIDE the transaction after the `credits`
  line lock it is B7's in-lock re-read: the transaction is pinned `READ COMMITTED`
  (`credit_transactions.run`), so each statement takes a fresh snapshot and sees what a concurrent
  issue committed while this one waited for the line (L10). Called outside a transaction through
  `SqlAlchemyInvoiceReads.find_by_order_reference` it is the fast path. Never locks.
* `find_by_id` and `find_payment_by_reference` are plain SELECTs
  too: called inside the transaction after the `credits` line lock they are the re-reads of
  `billing.payment.register` (BI8, R48), fresh statements at the pinned `READ COMMITTED`; they
  never lock.
* `mark_paid` is the service's ONE `UPDATE` (feature 22): `status`, `paid_at` and `updated_at`
  of the invoice `WHERE id = :id AND status = 'issued'`, so a row that is no longer `issued`
  (impossible under the line lock) updates nothing and is a transient failure rather than a
  silent overwrite; then the `payments` INSERT, flushed, then the invoice's drained events into
  the outbox. The `payments.payment_reference` UNIQUE constraint is R48's backstop for a
  competitor on ANOTHER credit line (which the line lock does not serialise): `23505` on that
  constraint is `PaymentReferenceReusedError`.
* `save` is plain INSERTs (never an upsert): an invoice is created once and issuing never updates
  it. The `invoices.order_reference` UNIQUE constraint is B7's last line of defence: a second
  invoice for one order fails with `23505`, rolls the whole transaction back and surfaces as
  `INTERNAL_ERROR` (transient: the caller asks again and the fast path answers).
* The invoice's events become outbox rows through the writer in THIS session and transaction (R13).
"""

from typing import Any, cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from otc_billing.application.errors import PaymentReferenceReusedError
from otc_billing.application.ports.clock import Clock
from otc_billing.application.ports.credit_store import StoreUnavailableError
from otc_billing.domain.invoice import Invoice
from otc_billing.domain.invoice_snapshot import InvoiceSnapshot, PaymentSnapshot
from otc_billing.domain.invoice_state import paid_at_of, state_token
from otc_billing.infrastructure.outbox.relay import sqlstate_of
from otc_billing.infrastructure.outbox.writer import OutboxWriter
from otc_billing.infrastructure.persistence import invoice_mapper
from otc_billing.infrastructure.persistence.models import Invoice as InvoiceRow
from otc_billing.infrastructure.persistence.models import InvoiceItem as InvoiceItemRow
from otc_billing.infrastructure.persistence.models import Payment as PaymentRow
from otc_shared_kernel import UniqueId

UNIQUE_VIOLATION = "23505"
PAYMENT_REFERENCE_UNIQUE = "uq_payments_payment_reference"


async def _snapshot_of(session: AsyncSession, row: InvoiceRow | None) -> InvoiceSnapshot | None:
    if row is None:
        return None
    items = list(
        await session.scalars(select(InvoiceItemRow).where(InvoiceItemRow.invoice_id == row.id))
    )
    return invoice_mapper.invoice_snapshot(row, items)


async def load_invoice(session: AsyncSession, order_reference: str) -> InvoiceSnapshot | None:
    """The invoice of the order with its lines, or None: ONE statement for the header, one for the
    lines, on the caller's session (the repository's in-lock re-read and the reads' fast path)."""
    return await _snapshot_of(
        session,
        await session.scalar(
            select(InvoiceRow).where(InvoiceRow.order_reference == order_reference)
        ),
    )


async def load_invoice_by_id(session: AsyncSession, invoice_id: UniqueId) -> InvoiceSnapshot | None:
    return await _snapshot_of(
        session, await session.scalar(select(InvoiceRow).where(InvoiceRow.id == invoice_id.value))
    )


async def load_invoice_by_reference(
    session: AsyncSession, invoice_reference: str
) -> InvoiceSnapshot | None:
    return await _snapshot_of(
        session,
        await session.scalar(
            select(InvoiceRow).where(InvoiceRow.invoice_reference == invoice_reference)
        ),
    )


async def load_payment_by_reference(
    session: AsyncSession, payment_reference: str
) -> PaymentSnapshot | None:
    row = await session.scalar(
        select(PaymentRow).where(PaymentRow.payment_reference == payment_reference)
    )
    return None if row is None else invoice_mapper.payment_snapshot(row)


class SqlAlchemyInvoiceRepository:
    def __init__(self, session: AsyncSession, outbox: OutboxWriter, clock: Clock) -> None:
        self._session = session
        self._outbox = outbox
        self._clock = clock
        self._saved: list[Invoice] = []

    async def find_by_order_reference(self, order_reference: str) -> InvoiceSnapshot | None:
        return await load_invoice(self._session, order_reference)

    async def save(self, invoice: Invoice) -> None:
        now = self._clock.now()
        self._session.add(invoice_mapper.new_invoice_row(invoice, now))
        await self._session.flush()  # the header first: the lines' foreign key needs it
        for line in invoice.lines:
            self._session.add(invoice_mapper.new_item_row(line, invoice.id, now))
        await self._session.flush()
        # The outbox rows join THIS session and transaction (R13); the writer flushes per row.
        await self._outbox.write(self._session, invoice.domain_events)
        self._saved.append(invoice)

    async def find_by_id(self, invoice_id: UniqueId) -> InvoiceSnapshot | None:
        return await load_invoice_by_id(self._session, invoice_id)

    async def find_payment_by_reference(self, payment_reference: str) -> PaymentSnapshot | None:
        return await load_payment_by_reference(self._session, payment_reference)

    async def mark_paid(self, invoice: Invoice, payment: PaymentSnapshot) -> None:
        now = self._clock.now()
        # An UPDATE yields a CursorResult at runtime; `execute` is typed as the base `Result`.
        result = cast(
            "CursorResult[Any]",
            await self._session.execute(
                update(InvoiceRow)
                .where(InvoiceRow.id == invoice.id.value, InvoiceRow.status == "issued")
                .values(
                    status=state_token(invoice.state).value,
                    paid_at=paid_at_of(invoice.state),
                    updated_at=now,
                )
            ),
        )
        if result.rowcount != 1:
            raise StoreUnavailableError("the invoice was not issued when it was marked paid")
        self._session.add(invoice_mapper.new_payment_row(payment, now))
        try:
            await self._session.flush()
        except IntegrityError as error:
            if sqlstate_of(error) == UNIQUE_VIOLATION and PAYMENT_REFERENCE_UNIQUE in str(
                error.orig
            ):
                raise PaymentReferenceReusedError(payment.payment_reference) from error
            raise
        # The outbox rows join THIS session and transaction (R13); the writer flushes per row.
        await self._outbox.write(self._session, invoice.domain_events)
        self._saved.append(invoice)

    def clear_saved_events(self) -> None:
        """Forget the events of every saved invoice. Called by `run()` only AFTER the commit."""
        for invoice in self._saved:
            invoice.clear_domain_events()
