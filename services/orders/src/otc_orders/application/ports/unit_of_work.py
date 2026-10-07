"""`UnitOfWork`: one transaction over every write a use case makes (R13).

`begin()` commits on a clean exit, rolls back on any exception and re-raises it unchanged; it never
swallows one and never retries (`outbox_and_idempotency/design.md` 4.2, gate point G2).
"""

from contextlib import AbstractAsyncContextManager
from typing import Protocol

from otc_orders.application.ports.order_number_allocator import OrderNumberAllocator
from otc_orders.application.ports.order_repository import OrderRepository
from otc_orders.application.ports.saga_command_store import SagaCommandQueue
from otc_orders.application.ports.saga_ignored_facts import SagaIgnoredFactRecorder


class OrdersTransaction(Protocol):
    @property
    def orders(self) -> OrderRepository: ...

    @property
    def order_numbers(self) -> OrderNumberAllocator: ...

    @property
    def saga_commands(self) -> SagaCommandQueue: ...

    @property
    def ignored_facts(self) -> SagaIgnoredFactRecorder: ...


class UnitOfWork(Protocol):
    def begin(self) -> AbstractAsyncContextManager[OrdersTransaction]: ...
