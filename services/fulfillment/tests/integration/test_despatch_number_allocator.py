"""`SqlAlchemyDespatchNumberAllocator`: `DES-######` under `SELECT ... FOR UPDATE`, through REAL
sessions and REAL transactions on a real PostgreSQL.

Ported from Orders' `test_order_number_allocator.py` (six tests, each classified in
`progress/impl_fulfillment_despatch.md`). The allocator is exercised through the transactions
object the service uses, so the claim "the allocation belongs to the unit of work's transaction" is
about the real path (`StockTransaction.despatch_numbers`), not a hand-built allocator only.

Loop scope: every async fixture here is function-scoped; the engines are created and disposed in
the test's own loop.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from otc_fulfillment.application.ports.stock_store import StockTransaction
from otc_fulfillment.infrastructure.clock import SystemClock
from otc_fulfillment.infrastructure.outbox.writer import OutboxWriter
from otc_fulfillment.infrastructure.persistence.despatch_number_allocator import (
    SqlAlchemyDespatchNumberAllocator,
)
from otc_fulfillment.infrastructure.persistence.stock_transactions import (
    SqlAlchemyStockTransactions,
)
from otc_shared_kernel import DespatchReference

pytestmark = pytest.mark.integration

CALLERS = 24


@pytest_asyncio.fixture(loop_scope="function")
async def wide_sessions(migrated_db: Any) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    # one pooled connection per caller: a barrier of N callers needs N simultaneous connections
    engine: AsyncEngine = create_async_engine(migrated_db.url, pool_size=CALLERS, max_overflow=0)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def _allocate_and_commit(sessions: async_sessionmaker[AsyncSession]) -> str:
    async with sessions() as session, session.begin():
        return (await SqlAlchemyDespatchNumberAllocator(session).next_reference()).value


async def test_concurrent_allocations_in_separate_transactions_are_gap_free_and_unique(
    wide_sessions: async_sessionmaker[AsyncSession],
) -> None:
    barrier = asyncio.Barrier(CALLERS)

    async def caller() -> str:
        async with wide_sessions() as session, session.begin():
            await session.connection()  # the connection is held BEFORE the barrier releases
            await barrier.wait()
            return (await SqlAlchemyDespatchNumberAllocator(session).next_reference()).value

    allocated = await asyncio.gather(*(caller() for _ in range(CALLERS)))

    assert len(set(allocated)) == CALLERS, f"duplicate references: {sorted(allocated)}"
    assert sorted(allocated) == [
        DespatchReference.from_sequence(n).value for n in range(1, CALLERS + 1)
    ]


async def test_an_uncommitted_allocation_holds_the_next_allocator_back_and_it_gets_the_next_number(
    wide_sessions: async_sessionmaker[AsyncSession],
) -> None:
    # The counter row must EXIST first: while it does not, the seed's `ON CONFLICT` makes a second
    # caller wait for the first one's insert, which would hold it back without any row lock.
    assert await _allocate_and_commit(wide_sessions) == "DES-000001"

    async with wide_sessions() as first, first.begin():
        held = (await SqlAlchemyDespatchNumberAllocator(first).next_reference()).value
        second = asyncio.create_task(_allocate_and_commit(wide_sessions))
        done, _ = await asyncio.wait({second}, timeout=1.0)
        assert not done, "a second allocator must wait on the row lock while the first is open"
    # the first transaction has committed: the waiting one proceeds, with the NEXT number
    assert held == "DES-000002"
    assert await asyncio.wait_for(second, timeout=10) == "DES-000003"


async def test_a_rolled_back_transaction_burns_no_number(
    wide_sessions: async_sessionmaker[AsyncSession],
) -> None:
    assert await _allocate_and_commit(wide_sessions) == "DES-000001"

    async with wide_sessions() as session:
        transaction = await session.begin()
        burned = (await SqlAlchemyDespatchNumberAllocator(session).next_reference()).value
        await transaction.rollback()

    assert burned == "DES-000002"
    assert await _allocate_and_commit(wide_sessions) == "DES-000002"


async def test_the_allocation_belongs_to_the_stock_transactions_transaction(
    wide_sessions: async_sessionmaker[AsyncSession],
) -> None:
    clock = SystemClock()
    transactions = SqlAlchemyStockTransactions(
        sessions=wide_sessions, outbox=OutboxWriter(clock=clock), clock=clock
    )

    class Refused(Exception):
        pass

    async def allocate_then_refuse(tx: StockTransaction) -> None:
        assert (await tx.despatch_numbers.next_reference()).value == "DES-000001"
        raise Refused

    async def allocate(tx: StockTransaction) -> str:
        return (await tx.despatch_numbers.next_reference()).value

    with pytest.raises(Refused):
        await transactions.run(allocate_then_refuse)

    # the refused work's allocation, and its seed, were rolled back with the transaction
    assert await transactions.run(allocate) == "DES-000001"
    assert await transactions.run(allocate) == "DES-000002"


async def test_seeding_over_a_non_empty_despatches_table_continues_above_its_maximum(
    wide_sessions: async_sessionmaker[AsyncSession], migrated_db: Any
) -> None:
    conn = await asyncpg.connect(migrated_db.dsn)
    try:
        for n, reference in enumerate(("DES-000042", "DES-000007")):
            await conn.execute(
                "INSERT INTO despatches (id, despatch_reference, despatch_date, company_code,"
                " retailer_code, order_reference, created_at, updated_at)"
                " VALUES ($1, $2, $3, 'ACME-CO', 'RET-9', $4, $3, $3)",
                uuid.uuid4(),
                reference,
                datetime.now(UTC),
                f"ORD-00000{n + 1}",
            )
        assert await conn.fetchval("SELECT count(*) FROM despatch_number_sequences") == 0
    finally:
        await conn.close()

    assert await _allocate_and_commit(wide_sessions) == "DES-000043"
    assert await _allocate_and_commit(wide_sessions) == "DES-000044"


async def test_the_reference_grows_past_six_digits_instead_of_truncating(
    wide_sessions: async_sessionmaker[AsyncSession], migrated_db: Any
) -> None:
    conn = await asyncpg.connect(migrated_db.dsn)
    try:
        await conn.execute(
            "INSERT INTO despatch_number_sequences (id, next_value) VALUES (1, 999999)"
        )
    finally:
        await conn.close()

    assert await _allocate_and_commit(wide_sessions) == "DES-999999"
    assert await _allocate_and_commit(wide_sessions) == "DES-1000000"
