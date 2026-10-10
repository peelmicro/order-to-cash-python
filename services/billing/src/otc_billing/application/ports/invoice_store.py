"""The ports of the invoice store: the repository, the number allocator and the lock-free reads
(`design.md` 7.2).

`InvoiceRepository` and `InvoiceNumberAllocator` are reached ONLY through the `CreditTransaction`
that `CreditTransactions.run(work)` hands `work` (they are bound to its one session), so the sharing
of a transaction by the `BuyerCredit` and the `Invoice` is in the signature (L33). `InvoiceReads`
opens its own short session, takes no lock and writes nothing (L9).
"""

from datetime import datetime
from typing import Protocol

from otc_billing.application.messages import InvoicePage
from otc_billing.domain.invoice import Invoice
from otc_billing.domain.invoice_snapshot import InvoiceSnapshot, PaymentSnapshot
from otc_billing.domain.invoice_state import InvoiceStatus
from otc_shared_kernel import InvoiceReference, UniqueId


class InvoiceRepository(Protocol):
    async def find_by_order_reference(self, order_reference: str) -> InvoiceSnapshot | None:
        """In-transaction, NO lock: after the line lock was granted this is a new statement at the
        pinned `READ COMMITTED`, so it sees what a competitor committed (L10)."""
        ...

    async def save(self, invoice: Invoice) -> None:
        """Insert the header, then the lines, then write the drained events into the outbox, all in
        this transaction. Never an update, never a delete."""
        ...

    async def find_by_id(self, invoice_id: UniqueId) -> InvoiceSnapshot | None:
        """In-transaction, NO lock: the plain re-read AFTER the credits row was locked (BI8,
        `billing.payment.register`)."""
        ...

    async def find_payment_by_reference(self, payment_reference: str) -> PaymentSnapshot | None:
        """In-transaction, NO lock: the authority dedup read after the line lock (R48)."""
        ...

    async def mark_paid(self, invoice: Invoice, payment: PaymentSnapshot) -> None:
        """The ONE update of the service's write model: `status`, `paid_at`, `updated_at` of the
        invoice (guarded `WHERE status = 'issued'`; a lost row is a transient failure), the
        `payments` insert, then the invoice's drained events into the outbox, in this order. A
        `payment_reference` already stored is `PaymentReferenceReusedError`."""
        ...


class InvoiceNumberAllocator(Protocol):
    async def next_reference(self) -> InvoiceReference:
        """`INV-######` allocated under `SELECT ... FOR UPDATE`, in the caller's transaction."""
        ...


class InvoiceReads(Protocol):
    """Reads that hold nothing and write nothing (L9, L19)."""

    async def find_by_order_reference(self, order_reference: str) -> InvoiceSnapshot | None:
        """The fast path: the invoice of the order with its lines, or `None`."""
        ...

    async def find_by_id(self, invoice_id: UniqueId) -> InvoiceSnapshot | None:
        """The identity resolution of `billing.payment.register`, outside any transaction."""
        ...

    async def find_by_invoice_reference(self, invoice_reference: str) -> InvoiceSnapshot | None:
        """The same, by `INV-######`."""
        ...

    async def find_payment_by_reference(self, payment_reference: str) -> PaymentSnapshot | None:
        """The R48 fast path: a hit answers `duplicate` and opens no transaction."""
        ...

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
        """`now` is supplied by the caller (the clock port), never read here (BI15)."""
        ...
