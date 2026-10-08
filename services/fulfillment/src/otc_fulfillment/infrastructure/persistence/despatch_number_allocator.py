"""`SqlAlchemyDespatchNumberAllocator`: `DES-######` allocated under `SELECT ... FOR UPDATE`.

The Orders allocator's shape (`otc_orders/infrastructure/persistence/order_number_allocator.py`),
substituting the counter table: three statements in the caller's transaction (`sequences.py` carries
the SQL and the reasoning): seed the counter row if it does not exist (a `WHERE NOT EXISTS`
one-time filter, one atomic statement: #8 ids 45 and 47), read it `FOR UPDATE`, advance it. The lock
is held until the caller's transaction ends, so concurrent allocations serialise on the row and a
rolled-back despatch burns no number. The session is the transaction's: the allocator never opens
one and never commits.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from otc_fulfillment.infrastructure.persistence.sequences import (
    ADVANCE_DESPATCH_SEQUENCE,
    LOCK_DESPATCH_SEQUENCE,
    SEED_DESPATCH_SEQUENCE,
)
from otc_shared_kernel import DespatchReference


class SqlAlchemyDespatchNumberAllocator:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def next_reference(self) -> DespatchReference:
        await self._session.execute(text(SEED_DESPATCH_SEQUENCE))
        allocated = (await self._session.execute(text(LOCK_DESPATCH_SEQUENCE))).scalar_one()
        await self._session.execute(text(ADVANCE_DESPATCH_SEQUENCE))
        return DespatchReference.from_sequence(allocated)
