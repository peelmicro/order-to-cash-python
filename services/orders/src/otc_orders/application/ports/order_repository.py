"""`OrderRepository`: the persistence port of the Order aggregate.

Obtained only through an `OrdersTransaction` (`unit_of_work.py`), so a repository and the
transaction it writes in cannot be separated.
"""

from typing import Protocol

from otc_orders.domain.order import Order
from otc_shared_kernel import OrderNumber, UniqueId


class OrderRepository(Protocol):
    async def save(self, order: Order) -> None:
        """Insert the order if this repository did not load it, else update it, and write one
        outbox record per domain event the aggregate holds (R13: the same transaction)."""
        ...

    async def get_by_id(self, order_id: UniqueId) -> Order | None: ...

    async def get_by_id_for_update(self, order_id: UniqueId) -> Order | None:
        """Load the order and hold its row until the transaction ends (SO17): a second transaction
        that loads the same order for update waits, then reads what the first committed. Only the
        order's own row is locked, never a reference-data row read with it."""
        ...

    async def get_by_reference(self, reference: OrderNumber) -> Order | None: ...
