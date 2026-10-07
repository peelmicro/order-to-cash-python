"""`OrderNumberAllocator`: the next `ORD-######`, allocated inside the caller's transaction.

It is reached only through `OrdersTransaction.order_numbers`, so an allocation and the order it
numbers share one transaction: a rollback returns the number instead of burning it.
"""

from typing import Protocol

from otc_shared_kernel import OrderNumber


class OrderNumberAllocator(Protocol):
    async def next_number(self) -> OrderNumber: ...
