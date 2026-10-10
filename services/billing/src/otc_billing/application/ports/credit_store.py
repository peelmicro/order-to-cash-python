"""The ports of the credit store: transactions, the repository, and the lock-free reads.

`CreditTransactions.run(work)` opens ONE transaction per call and hands `work` a
`CreditTransaction`. There is NO in-process re-run (L31): a hold or release locks exactly one row,
so no lock cycle can form and a deadlock victim is `UNAVAILABLE`, retried by the saga. `work` still
receives everything through `tx` and its own arguments and does no I/O outside the transaction.

No SQLAlchemy type crosses into `application` or `presentation`: a transient store failure is the
application-level `StoreUnavailableError`.
"""

from collections.abc import Awaitable, Callable
from typing import Protocol

from otc_billing.application.messages import CreditPage
from otc_billing.application.ports.invoice_store import InvoiceNumberAllocator, InvoiceRepository
from otc_billing.domain.buyer_credit import BuyerCredit


class StoreUnavailableError(Exception):
    """A transient store failure (a deadlock victim, a lost connection, a lock or statement timeout,
    a pool timeout): answered `UNAVAILABLE`, which the caller retries (BC27)."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"the credit store is temporarily unavailable ({reason})")
        self.reason = reason


class CreditRepository(Protocol):
    async def lock_for_order(
        self, retailer_code: str, company_code: str, order_reference: str
    ) -> BuyerCredit | None:
        """The lock protocol (`design.md` 6.2 steps 1 - 3): the line `FOR UPDATE` first, then the
        committed-exposure scalar, then the order's entries, in this order and no other. `None`
        when no line exists for the pair."""
        ...

    async def save(self, credit: BuyerCredit) -> None:
        """Insert the entries the aggregate appended and write its drained events into the outbox,
        in emission order, all in this transaction. Never an update, never a delete."""
        ...


class CreditTransaction(Protocol):
    @property
    def credits(self) -> CreditRepository: ...

    @property
    def invoices(self) -> InvoiceRepository: ...

    @property
    def invoice_numbers(self) -> InvoiceNumberAllocator: ...


class CreditTransactions(Protocol):
    async def run[T](self, work: Callable[[CreditTransaction], Awaitable[T]]) -> T: ...


class CreditReads(Protocol):
    """Reads that hold nothing and write nothing (L13)."""

    async def list(
        self,
        *,
        page: int,
        page_size: int,
        retailer_code: str | None,
        company_code: str | None,
    ) -> CreditPage: ...
