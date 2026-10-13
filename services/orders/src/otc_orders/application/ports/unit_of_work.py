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


class RequestIdAlreadyPlacedError(Exception):
    """`begin()` rolled back because the insert violated `uq_orders_request_id` (R62, RI3).

    Raised by the unit of work AFTER the rollback and only for that one unique index; every other
    integrity error (an `order_reference` collision, say) propagates unchanged. `__cause__` is the
    original database error, so a caller that finds no winner re-raises it, never swallows it.
    """


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
