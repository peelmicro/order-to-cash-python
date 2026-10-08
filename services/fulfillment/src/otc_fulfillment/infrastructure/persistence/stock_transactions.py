"""`SqlAlchemyStockTransactions.run(work)`: one transaction per attempt, `READ COMMITTED`, and the
`40P01` re-run (`design.md` 6.5; FS19, FS23).

WHY THIS CLASS RE-RUNS WHEN ORDERS' UNIT OF WORK DOES NOT. Orders' `SqlAlchemyUnitOfWork.begin()` is
an async context manager around the CALLER's block (its gate point G2: a retried block would re-run
caller code the class cannot see), so it cannot retry. `run(work)` is given the callable itself, so
re-running it is possible, and PostgreSQL aborts a deadlock victim's WHOLE transaction, so only a
whole re-run is: `work` is re-runnable by construction (it receives everything through `tx` and its
own arguments, builds its aggregates from rows read in THIS attempt, mints its ids per attempt and
does no I/O outside the transaction). Only `40P01` is re-run (at most three attempts in total,
200 ms before each re-run, the relay's constants); every other store failure is not.

The isolation level is PINNED before the first statement of every attempt, never inherited: at
`REPEATABLE READ` PostgreSQL raises `40001` on the stock lock itself (measured), and the in-lock
re-reads of feature 18 rely on a statement-scoped snapshot (#8 id 54, L13). The session belongs to
one attempt and is closed with it; there is no module-level session.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

import sqlalchemy.exc
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from otc_fulfillment.application.ports.clock import Clock
from otc_fulfillment.application.ports.stock_store import StockTransaction, StoreUnavailableError
from otc_fulfillment.infrastructure.outbox.relay import DEADLOCK_DETECTED, sqlstate_of
from otc_fulfillment.infrastructure.outbox.writer import OutboxWriter
from otc_fulfillment.infrastructure.persistence.despatch_number_allocator import (
    SqlAlchemyDespatchNumberAllocator,
)
from otc_fulfillment.infrastructure.persistence.despatch_repository import (
    SqlAlchemyDespatchRepository,
)
from otc_fulfillment.infrastructure.persistence.stock_repository import SqlAlchemyStockRepository

log = logging.getLogger("otc_fulfillment.persistence.stock_transactions")

DEADLOCK_ATTEMPTS = 3  # total attempts, the relay's
DEADLOCK_BACKOFF_SECONDS = 0.2  # before each re-run, the relay's

# SQLSTATEs that mean "try again later" (a literal set): `40P01` once its attempts are exhausted,
# `40001` serialization_failure, `55P03` lock_not_available, `57014` query_canceled, `53300`
# too_many_connections, and the whole of class `08` (connection exceptions, below).
TRANSIENT_SQLSTATES = frozenset({"40P01", "40001", "55P03", "57014", "53300"})
CONNECTION_EXCEPTION_CLASS = "08"


class RepositoryFactory(Protocol):
    def __call__(
        self, session: AsyncSession, outbox: OutboxWriter, clock: Clock
    ) -> SqlAlchemyStockRepository: ...


class DespatchRepositoryFactory(Protocol):
    def __call__(
        self, session: AsyncSession, outbox: OutboxWriter, clock: Clock
    ) -> SqlAlchemyDespatchRepository: ...


class SqlAlchemyStockTransaction:
    """Satisfies `StockTransaction`: the stock repository, the despatch repository and the `DES-`
    allocator, all bound to this attempt's session (so one transaction holds all three)."""

    def __init__(
        self,
        repository: SqlAlchemyStockRepository,
        despatches: SqlAlchemyDespatchRepository,
        despatch_numbers: SqlAlchemyDespatchNumberAllocator,
    ) -> None:
        self._repository = repository
        self._despatches = despatches
        self._despatch_numbers = despatch_numbers

    @property
    def repository(self) -> SqlAlchemyStockRepository:
        return self._repository

    @property
    def despatches(self) -> SqlAlchemyDespatchRepository:
        return self._despatches

    @property
    def despatch_numbers(self) -> SqlAlchemyDespatchNumberAllocator:
        return self._despatch_numbers


def _is_transient(state: str | None) -> bool:
    return state is not None and (
        state in TRANSIENT_SQLSTATES or state.startswith(CONNECTION_EXCEPTION_CLASS)
    )


class SqlAlchemyStockTransactions:
    def __init__(
        self,
        *,
        sessions: async_sessionmaker[AsyncSession],
        outbox: OutboxWriter,
        clock: Clock,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        repository_factory: RepositoryFactory = SqlAlchemyStockRepository,
        despatch_repository_factory: DespatchRepositoryFactory = SqlAlchemyDespatchRepository,
    ) -> None:
        self._sessions = sessions
        self._outbox = outbox
        self._clock = clock
        self._sleep = sleep
        self._repository_factory = repository_factory
        self._despatch_repository_factory = despatch_repository_factory

    async def run[T](self, work: Callable[[StockTransaction], Awaitable[T]]) -> T:
        attempt = 1
        while True:
            try:
                async with self._sessions() as session, session.begin():
                    await session.connection(
                        execution_options={"isolation_level": "READ COMMITTED"}
                    )
                    repository = self._repository_factory(session, self._outbox, self._clock)
                    despatches = self._despatch_repository_factory(
                        session, self._outbox, self._clock
                    )
                    result = await work(
                        SqlAlchemyStockTransaction(
                            repository, despatches, SqlAlchemyDespatchNumberAllocator(session)
                        )
                    )
                # the commit has returned: only now may the aggregates forget their events
                repository.clear_saved_events()
                despatches.clear_saved_events()
                return result
            except DBAPIError as error:
                state = sqlstate_of(error)
                if state == DEADLOCK_DETECTED and attempt < DEADLOCK_ATTEMPTS:
                    log.warning(
                        "stock transaction was a deadlock victim (SQLSTATE %s); re-running it "
                        "from the start",
                        state,
                        extra={"attempt": attempt, "sqlstate": state},
                    )
                    attempt += 1
                    await self._sleep(DEADLOCK_BACKOFF_SECONDS)
                    continue
                if _is_transient(state):
                    raise StoreUnavailableError(str(state)) from error
                raise
            except (sqlalchemy.exc.TimeoutError, OSError) as error:
                # a pool timeout, a refused or lost connection
                raise StoreUnavailableError(type(error).__name__) from error
