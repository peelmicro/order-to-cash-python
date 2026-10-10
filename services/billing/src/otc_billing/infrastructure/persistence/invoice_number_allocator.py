"""`SqlAlchemyInvoiceNumberAllocator`: `INV-######` allocated under `SELECT ... FOR UPDATE`.

A copy of `services/fulfillment/src/otc_fulfillment/infrastructure/persistence/
despatch_number_allocator.py`'s shape with the three constants substituted (service independence:
no service imports another's package; each allocator names its own table and prefix, so none is
added to a parity guard, the shape is three statements). `sequences.py` carries the SQL and the
reasoning: seed the counter row if it does not exist (a `WHERE NOT EXISTS` one-time filter, one
atomic statement: #8 ids 45 and 47, backlog 211), read it `FOR UPDATE`, advance it. The lock is
held until the caller's transaction ends, so concurrent allocations serialise on the row and a
rolled-back invoice burns no number. The session is the transaction's: the allocator never opens
one and never commits.

These are the only textual DML statements in the Billing service (L26): raw SQL bypasses the ORM
range guard on `next_value`, the residual `range_guards.py` and `sequences.py` already name; the
engine refuses an overflow.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from otc_billing.infrastructure.persistence.sequences import (
    ADVANCE_INVOICE_SEQUENCE,
    LOCK_INVOICE_SEQUENCE,
    SEED_INVOICE_SEQUENCE,
)
from otc_shared_kernel import InvoiceReference


class SqlAlchemyInvoiceNumberAllocator:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def next_reference(self) -> InvoiceReference:
        await self._session.execute(text(SEED_INVOICE_SEQUENCE))
        allocated = (await self._session.execute(text(LOCK_INVOICE_SEQUENCE))).scalar_one()
        await self._session.execute(text(ADVANCE_INVOICE_SEQUENCE))
        return InvoiceReference.from_sequence(allocated)
