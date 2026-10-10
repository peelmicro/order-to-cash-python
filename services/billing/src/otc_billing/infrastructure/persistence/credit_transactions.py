"""`SqlAlchemyCreditTransactions.run(work)`: one transaction per call, `READ COMMITTED` (`design.md`
6.4; BC35, L30, L31).

Fulfillment's `stock_transactions.py` shape WITHOUT the `40P01` re-run: a hold or release locks
exactly one `credits` row, so no lock cycle can form; a deadlock victim, like every other
transient failure, becomes `StoreUnavailableError` (answered `UNAVAILABLE`, retried by the saga).
The transient set is a literal copied from Fulfillment's module, not imported (service
independence).

The isolation level is PINNED before the first statement of every call, never inherited: at
`REPEATABLE READ` the committed-exposure read after the line lock would see a stale snapshot
SILENTLY (the line row is locked, never updated, so no `40001`: measured). The session belongs to
one call and is closed with it; there is no module-level session. Events are forgotten only AFTER
the commit has returned.

Feature 21 extends the transaction object (`design.md` 6.4): the credit repository, the invoice
repository and the invoice number allocator are all built on the ONE session `work` is handed, so
the sharing of a transaction by the `BuyerCredit` and the `Invoice` is visible in the signature
(L33), and BOTH repositories forget their events only after the commit (L34).
"""

from collections.abc import Awaitable, Callable
from typing import Protocol

import sqlalchemy.exc
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from otc_billing.application.ports.clock import Clock
from otc_billing.application.ports.credit_store import CreditTransaction, StoreUnavailableError
from otc_billing.infrastructure.outbox.relay import sqlstate_of
from otc_billing.infrastructure.outbox.writer import OutboxWriter
from otc_billing.infrastructure.persistence.credit_repository import SqlAlchemyCreditRepository
from otc_billing.infrastructure.persistence.invoice_number_allocator import (
    SqlAlchemyInvoiceNumberAllocator,
)
from otc_billing.infrastructure.persistence.invoice_repository import SqlAlchemyInvoiceRepository

# SQLSTATEs that mean "try again later" (a literal set): `40P01` deadlock_detected, `40001`
# serialization_failure, `55P03` lock_not_available, `57014` query_canceled, `53300`
# too_many_connections, and the whole of class `08` (connection exceptions, below).
TRANSIENT_SQLSTATES = frozenset({"40P01", "40001", "55P03", "57014", "53300"})
CONNECTION_EXCEPTION_CLASS = "08"


class RepositoryFactory(Protocol):
    def __call__(
        self, session: AsyncSession, outbox: OutboxWriter, clock: Clock
    ) -> SqlAlchemyCreditRepository: ...


class InvoiceRepositoryFactory(Protocol):
    def __call__(
        self, session: AsyncSession, outbox: OutboxWriter, clock: Clock
    ) -> SqlAlchemyInvoiceRepository: ...


class AllocatorFactory(Protocol):
    def __call__(self, session: AsyncSession) -> SqlAlchemyInvoiceNumberAllocator: ...


class SqlAlchemyCreditTransaction:
    """Satisfies `CreditTransaction`: the credit repository, the invoice repository and the invoice
    number allocator, all bound to this call's ONE session (L33)."""

    def __init__(
        self,
        credits: SqlAlchemyCreditRepository,
        invoices: SqlAlchemyInvoiceRepository,
        invoice_numbers: SqlAlchemyInvoiceNumberAllocator,
    ) -> None:
        self._credits = credits
        self._invoices = invoices
        self._invoice_numbers = invoice_numbers

    @property
    def credits(self) -> SqlAlchemyCreditRepository:
        return self._credits

    @property
    def invoices(self) -> SqlAlchemyInvoiceRepository:
        return self._invoices

    @property
    def invoice_numbers(self) -> SqlAlchemyInvoiceNumberAllocator:
        return self._invoice_numbers


def _is_transient(state: str | None) -> bool:
    return state is not None and (
        state in TRANSIENT_SQLSTATES or state.startswith(CONNECTION_EXCEPTION_CLASS)
    )


class SqlAlchemyCreditTransactions:
    def __init__(
        self,
        *,
        sessions: async_sessionmaker[AsyncSession],
        outbox: OutboxWriter,
        clock: Clock,
        repository_factory: RepositoryFactory = SqlAlchemyCreditRepository,
        invoice_repository_factory: InvoiceRepositoryFactory = SqlAlchemyInvoiceRepository,
        allocator_factory: AllocatorFactory = SqlAlchemyInvoiceNumberAllocator,
    ) -> None:
        self._sessions = sessions
        self._outbox = outbox
        self._clock = clock
        self._repository_factory = repository_factory
        self._invoice_repository_factory = invoice_repository_factory
        self._allocator_factory = allocator_factory

    async def run[T](self, work: Callable[[CreditTransaction], Awaitable[T]]) -> T:
        try:
            async with self._sessions() as session, session.begin():
                await session.connection(execution_options={"isolation_level": "READ COMMITTED"})
                repository = self._repository_factory(session, self._outbox, self._clock)
                invoices = self._invoice_repository_factory(session, self._outbox, self._clock)
                numbers = self._allocator_factory(session)
                result = await work(SqlAlchemyCreditTransaction(repository, invoices, numbers))
            # the commit has returned: only now may either aggregate forget its events
            repository.clear_saved_events()
            invoices.clear_saved_events()
            return result
        except DBAPIError as error:
            state = sqlstate_of(error)
            if _is_transient(state):
                raise StoreUnavailableError(str(state)) from error
            raise
        except (sqlalchemy.exc.TimeoutError, OSError) as error:
            # a pool timeout, a refused or lost connection
            raise StoreUnavailableError(type(error).__name__) from error
