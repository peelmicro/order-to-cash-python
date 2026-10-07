"""`SqlAlchemyOrderNumberAllocator`: `ORD-######` under `SELECT ... FOR UPDATE` (#8 A11, owed since
#8's feature 15 and never paid there).

The allocator is exercised through REAL sessions and REAL transactions on a real PostgreSQL:

* N concurrent allocations in N transactions, released together by a barrier, each committed, yield
  one gap-free, duplicate-free run (the lock serialises them);
* the lock is what does it: a transaction that has allocated and not yet committed holds every
  other allocator back, and the one it held back receives the NEXT number, not the same one;
* a rolled-back transaction burns no number, because the allocation (and the seed) is part of it;
* seeding over a non-empty `orders` continues above the maximum, numerically, past six digits.
"""

import asyncio
from collections.abc import AsyncIterator

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from otc_orders.infrastructure.persistence.order_number_allocator import (
    SqlAlchemyOrderNumberAllocator,
)
from otc_orders.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from otc_shared_kernel import OrderNumber

pytestmark = pytest.mark.integration

CALLERS = 24


@pytest_asyncio.fixture(loop_scope="function")
async def wide_sessions(migrated_db: object) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    # one pooled connection per caller: a barrier of N callers needs N simultaneous connections
    engine: AsyncEngine = create_async_engine(
        migrated_db.url,  # type: ignore[attr-defined]
        pool_size=CALLERS,
        max_overflow=0,
    )
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def _allocate_and_commit(sessions: async_sessionmaker[AsyncSession]) -> str:
    async with sessions() as session, session.begin():
        return (await SqlAlchemyOrderNumberAllocator(session).next_number()).value


async def test_concurrent_allocations_in_separate_transactions_are_gap_free_and_unique(
    wide_sessions: async_sessionmaker[AsyncSession],
) -> None:
    barrier = asyncio.Barrier(CALLERS)

    async def caller() -> str:
        async with wide_sessions() as session, session.begin():
            await session.connection()  # the connection is held BEFORE the barrier releases
            await barrier.wait()
            return (await SqlAlchemyOrderNumberAllocator(session).next_number()).value

    allocated = await asyncio.gather(*(caller() for _ in range(CALLERS)))

    assert len(set(allocated)) == CALLERS, f"duplicate references: {sorted(allocated)}"
    assert sorted(allocated) == [OrderNumber.from_sequence(n).value for n in range(1, CALLERS + 1)]


async def test_an_uncommitted_allocation_holds_the_next_allocator_back_and_it_gets_the_next_number(
    wide_sessions: async_sessionmaker[AsyncSession],
) -> None:
    # The counter row must EXIST first: while it does not, the seed's `ON CONFLICT` makes a second
    # caller wait for the first one's insert, which would hold it back without any row lock.
    assert await _allocate_and_commit(wide_sessions) == "ORD-000001"

    async with wide_sessions() as first, first.begin():
        held = (await SqlAlchemyOrderNumberAllocator(first).next_number()).value
        second = asyncio.create_task(_allocate_and_commit(wide_sessions))
        done, _ = await asyncio.wait({second}, timeout=1.0)
        assert not done, "a second allocator must wait on the row lock while the first is open"
    # the first transaction has committed: the waiting one proceeds, with the NEXT number
    assert held == "ORD-000002"
    assert await asyncio.wait_for(second, timeout=10) == "ORD-000003"


async def test_a_rolled_back_transaction_burns_no_number(
    wide_sessions: async_sessionmaker[AsyncSession],
) -> None:
    assert await _allocate_and_commit(wide_sessions) == "ORD-000001"

    async with wide_sessions() as session:
        transaction = await session.begin()
        burned = (await SqlAlchemyOrderNumberAllocator(session).next_number()).value
        await transaction.rollback()

    assert burned == "ORD-000002"
    assert await _allocate_and_commit(wide_sessions) == "ORD-000002"


async def test_the_allocation_belongs_to_the_unit_of_work_s_transaction(
    uow: SqlAlchemyUnitOfWork, wide_sessions: async_sessionmaker[AsyncSession]
) -> None:
    class Refused(Exception):
        pass

    async def allocate_then_refuse() -> None:
        async with uow.begin() as transaction:
            assert (await transaction.order_numbers.next_number()).value == "ORD-000001"
            raise Refused

    with pytest.raises(Refused):
        await allocate_then_refuse()

    async with uow.begin() as transaction:
        assert (await transaction.order_numbers.next_number()).value == "ORD-000001"


async def test_seeding_over_a_non_empty_orders_table_continues_above_its_maximum(
    wide_sessions: async_sessionmaker[AsyncSession], migrated_db: object, reference_data: object
) -> None:
    dsn = migrated_db.dsn  # type: ignore[attr-defined]
    conn = await asyncpg.connect(dsn)
    try:
        ids = {
            table: await conn.fetchval(f"SELECT id FROM {table} LIMIT 1")  # noqa: S608
            for table in ("retailers", "companies", "currencies")
        }
        for reference in ("ORD-000042", "ORD-000007"):
            await conn.execute(
                "INSERT INTO orders (id, order_reference, request_id, order_date, company_id, "
                "retailer_id, currency_id, initial_amount, initial_discount, total_amount, "
                "status, cancellation_reason, notes, created_at, updated_at) "
                "VALUES (gen_random_uuid(), $1, NULL, now(), $2, $3, $4, 1, 0, 1, 'placed', "
                "NULL, NULL, now(), now())",
                reference,
                ids["companies"],
                ids["retailers"],
                ids["currencies"],
            )
        assert await conn.fetchval("SELECT count(*) FROM order_number_sequences") == 0
    finally:
        await conn.close()

    assert await _allocate_and_commit(wide_sessions) == "ORD-000043"
    assert await _allocate_and_commit(wide_sessions) == "ORD-000044"


async def test_the_reference_grows_past_six_digits_instead_of_truncating(
    wide_sessions: async_sessionmaker[AsyncSession], migrated_db: object
) -> None:
    dsn = migrated_db.dsn  # type: ignore[attr-defined]
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute("INSERT INTO order_number_sequences (id, next_value) VALUES (1, 999999)")
    finally:
        await conn.close()

    assert await _allocate_and_commit(wide_sessions) == "ORD-999999"
    assert await _allocate_and_commit(wide_sessions) == "ORD-1000000"
