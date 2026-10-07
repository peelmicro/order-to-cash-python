"""`SqlAlchemyOrderNumberAllocator`: `ORD-######` allocated under `SELECT ... FOR UPDATE`.

Three statements in the caller's transaction (`sequences.py` carries the SQL and the reasoning):
seed the counter row if it does not exist (a `WHERE NOT EXISTS` one-time filter: the `MAX` over
`orders` is evaluated only then, never on an ordinary allocation: #8 id 47), read it `FOR UPDATE`,
advance it. The lock is held until the caller's transaction ends, so concurrent allocations
serialise on the row and a rolled-back order burns no number. The session is the transaction's:
the allocator never opens one and never commits.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from otc_orders.infrastructure.persistence.sequences import (
    ADVANCE_ORDER_SEQUENCE,
    LOCK_ORDER_SEQUENCE,
    SEED_ORDER_SEQUENCE,
)
from otc_shared_kernel import OrderNumber


class SqlAlchemyOrderNumberAllocator:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def next_number(self) -> OrderNumber:
        await self._session.execute(text(SEED_ORDER_SEQUENCE))
        allocated = (await self._session.execute(text(LOCK_ORDER_SEQUENCE))).scalar_one()
        await self._session.execute(text(ADVANCE_ORDER_SEQUENCE))
        return OrderNumber.from_sequence(allocated)
