"""`SqlAlchemyUnitOfWork`: one `AsyncSession`, one transaction pinned to `READ COMMITTED` (R13).

`begin()` opens the session and its transaction, pins the isolation level BEFORE the first
statement (never inheriting the engine's or server's default: L2), yields a transaction object that
holds the session and the repository bound to it, commits on a clean exit and rolls back and
re-raises on any exception. After the commit returns it clears the domain events of every aggregate
saved in the transaction (L16): cleared before the commit, a retry from the same instance after a
rollback would write no outbox row at all (OI9).

A unique violation on `uq_orders_request_id` (R62, RI3) is the one error it translates: after the
rollback it raises `RequestIdAlreadyPlacedError` (chained from the database error), because
PostgreSQL aborts the whole transaction on any error and the collision therefore cannot be caught
inside the block; the caller re-reads the winner in a new transaction. It decides by the structured
`constraint_name` of the asyncpg error (measured: `error.orig.__cause__`, not `error.orig`), never
by the message; any other integrity error propagates unchanged.

It does NOT retry (gate point G2): a retried block would re-run caller code this class cannot see.
The session belongs to this one `begin()` and is closed with it; no module-level session exists.

The whole transaction is one `writemodel.transaction` INTERNAL span (`R56`): a child of the
request's server span, and the context every outbox row written inside it records as its
`trace_parent`.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
from opentelemetry.trace import SpanKind, Tracer
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from otc_orders.application.ports.clock import Clock
from otc_orders.application.ports.order_number_allocator import OrderNumberAllocator
from otc_orders.application.ports.order_repository import OrderRepository
from otc_orders.application.ports.saga_command_store import SagaCommandQueue
from otc_orders.application.ports.saga_ignored_facts import SagaIgnoredFactRecorder
from otc_orders.application.ports.unit_of_work import RequestIdAlreadyPlacedError
from otc_orders.infrastructure.clock import SystemClock
from otc_orders.infrastructure.observability.trace_context import (
    NO_TRACER,
    TRANSACTION_SPAN,
)
from otc_orders.infrastructure.outbox.writer import OutboxWriter
from otc_orders.infrastructure.persistence.order_number_allocator import (
    SqlAlchemyOrderNumberAllocator,
)
from otc_orders.infrastructure.persistence.order_repository import SqlAlchemyOrderRepository
from otc_orders.infrastructure.saga.command_queue import SqlAlchemySagaCommandQueue
from otc_orders.infrastructure.saga.ignored_facts import SqlAlchemySagaIgnoredFactRecorder

REQUEST_ID_CONSTRAINT = "uq_orders_request_id"


def _violates_request_id_index(error: IntegrityError) -> bool:
    """Measured (R62 S2.3): SQLAlchemy wraps asyncpg's `UniqueViolationError` in its adapter's own
    class, and the original, carrying `constraint_name`, is that adapter error's `__cause__`."""
    cause = error.orig.__cause__ if error.orig is not None else None
    return (
        isinstance(cause, asyncpg.exceptions.UniqueViolationError)
        and cause.constraint_name == REQUEST_ID_CONSTRAINT
    )


class SqlAlchemyOrdersTransaction:
    """Satisfies `OrdersTransaction` (`.orders`, `.order_numbers`, `.saga_commands`,
    `.ignored_facts`) and the idempotent consumer's `SessionBound`."""

    def __init__(
        self, session: AsyncSession, repository: SqlAlchemyOrderRepository, clock: Clock
    ) -> None:
        self._session = session
        self._repository = repository
        self._clock = clock

    @property
    def orders(self) -> OrderRepository:
        return self._repository

    @property
    def order_numbers(self) -> OrderNumberAllocator:
        # Built on the transaction's own session, so an allocation is part of this transaction.
        return SqlAlchemyOrderNumberAllocator(self._session)

    @property
    def saga_commands(self) -> SagaCommandQueue:
        # Built on the transaction's own session: the owed command commits with the status change.
        return SqlAlchemySagaCommandQueue(self._session, self._clock)

    @property
    def ignored_facts(self) -> SagaIgnoredFactRecorder:
        return SqlAlchemySagaIgnoredFactRecorder(self._session, self._clock)

    @property
    def session(self) -> AsyncSession:
        return self._session

    @property
    def repository(self) -> SqlAlchemyOrderRepository:
        return self._repository


class SqlAlchemyUnitOfWork:
    def __init__(
        self,
        *,
        sessions: async_sessionmaker[AsyncSession],
        outbox: OutboxWriter,
        clock: Clock | None = None,
        tracer: Tracer = NO_TRACER,
    ) -> None:
        self._tracer = tracer
        self._sessions = sessions
        self._outbox = outbox
        # The instants of the saga's rows (`created_at`, `recorded_at`): the clock port, never
        # `datetime.now()` (L13). The composition root passes its one clock; a caller that builds a
        # unit of work for the order path alone gets the system clock.
        self._clock: Clock = clock if clock is not None else SystemClock()

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[SqlAlchemyOrdersTransaction]:
        with self._tracer.start_as_current_span(TRANSACTION_SPAN, kind=SpanKind.INTERNAL):
            async with self._sessions() as session:
                repository = SqlAlchemyOrderRepository(session, self._outbox)
                try:
                    async with session.begin():
                        await session.connection(
                            execution_options={"isolation_level": "READ COMMITTED"}
                        )
                        yield SqlAlchemyOrdersTransaction(session, repository, self._clock)
                except IntegrityError as error:
                    # `session.begin()` has rolled back by here (R62, RI3)
                    if _violates_request_id_index(error):
                        raise RequestIdAlreadyPlacedError(REQUEST_ID_CONSTRAINT) from error
                    raise
                # the commit has returned: only now may the aggregates forget their events
                for order in repository.saved:
                    order.clear_domain_events()
