"""`SqlAlchemyInvoiceNumberAllocator`: `INV-######` under `SELECT ... FOR UPDATE`, through REAL
sessions and REAL transactions on a real PostgreSQL (task D6; BI12).

Ported from Fulfillment's `test_despatch_number_allocator.py` (six cases). The allocator is
exercised through the transactions object the service uses (`SqlAlchemyCreditTransactions.run`), so
"the allocation belongs to the unit of work's transaction" is about the real path
(`CreditTransaction.invoice_numbers`). The counter SQL's own five guards
(`test_billing_counter_seed.py`, BI29) are re-run alongside and cited in the report.

One change from the source: "an uncommitted allocation holds the next back" is synchronised on the
lock request seen UNGRANTED in `pg_stat_activity` (`Db.wait_for_lock_waiters`), not on a one-second
timeout.

Loop scope: every async fixture here is function-scoped; the engines are created and disposed in
the test's own loop.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import asyncpg
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from otc_billing.application.ports.credit_store import CreditTransaction
from otc_billing.infrastructure.clock import SystemClock
from otc_billing.infrastructure.outbox.writer import OutboxWriter
from otc_billing.infrastructure.persistence.credit_transactions import (
    SqlAlchemyCreditTransactions,
)
from otc_billing.infrastructure.persistence.invoice_number_allocator import (
    SqlAlchemyInvoiceNumberAllocator,
)
from otc_shared_kernel import InvoiceReference

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
        return (await SqlAlchemyInvoiceNumberAllocator(session).next_reference()).value


async def test_concurrent_allocations_in_separate_transactions_are_gap_free_and_unique(
    wide_sessions: async_sessionmaker[AsyncSession],
) -> None:
    barrier = asyncio.Barrier(CALLERS)

    async def caller() -> str:
        async with wide_sessions() as session, session.begin():
            await session.connection()  # the connection is held BEFORE the barrier releases
            await barrier.wait()
            return (await SqlAlchemyInvoiceNumberAllocator(session).next_reference()).value

    allocated = await asyncio.gather(*(caller() for _ in range(CALLERS)))

    assert len(set(allocated)) == CALLERS, f"duplicate references: {sorted(allocated)}"
    assert sorted(allocated) == [
        InvoiceReference.from_sequence(n).value for n in range(1, CALLERS + 1)
    ]


async def test_an_uncommitted_allocation_holds_the_next_allocator_back_and_it_gets_the_next_number(
    db: Any, wide_sessions: async_sessionmaker[AsyncSession]
) -> None:
    # The counter row must EXIST first: while it does not, the seed's `ON CONFLICT` makes a second
    # caller wait for the first one's insert, which would hold it back without any row lock.
    assert await _allocate_and_commit(wide_sessions) == "INV-000001"

    async with wide_sessions() as first, first.begin():
        held = (await SqlAlchemyInvoiceNumberAllocator(first).next_reference()).value
        second = asyncio.create_task(_allocate_and_commit(wide_sessions))
        # terminal evidence: the second caller's lock request is seen UNGRANTED
        await db.wait_for_lock_waiters("%FROM invoice_number_sequences%FOR UPDATE%", 1)
        assert not second.done(), (
            "a second allocator must wait on the row lock while the first is open"
        )
    # the first transaction has committed: the waiting one proceeds, with the NEXT number
    assert held == "INV-000002"
    assert await asyncio.wait_for(second, timeout=10) == "INV-000003"


async def test_a_rolled_back_transaction_burns_no_number(
    wide_sessions: async_sessionmaker[AsyncSession],
) -> None:
    assert await _allocate_and_commit(wide_sessions) == "INV-000001"

    async with wide_sessions() as session:
        transaction = await session.begin()
        burned = (await SqlAlchemyInvoiceNumberAllocator(session).next_reference()).value
        await transaction.rollback()

    assert burned == "INV-000002"
    assert await _allocate_and_commit(wide_sessions) == "INV-000002"


async def test_the_allocation_belongs_to_the_credit_transactions_transaction(
    wide_sessions: async_sessionmaker[AsyncSession],
) -> None:
    clock = SystemClock()
    transactions = SqlAlchemyCreditTransactions(
        sessions=wide_sessions, outbox=OutboxWriter(clock=clock), clock=clock
    )

    class Refused(Exception):
        pass

    async def allocate_then_refuse(tx: CreditTransaction) -> None:
        assert (await tx.invoice_numbers.next_reference()).value == "INV-000001"
        raise Refused

    async def allocate(tx: CreditTransaction) -> str:
        return (await tx.invoice_numbers.next_reference()).value

    try:
        await transactions.run(allocate_then_refuse)
    except Refused:
        pass
    else:
        raise AssertionError("the refusing work did not raise")

    # the refused work's allocation, and its seed, were rolled back with the transaction
    assert await transactions.run(allocate) == "INV-000001"
    assert await transactions.run(allocate) == "INV-000002"


async def test_seeding_over_a_non_empty_invoices_table_continues_above_its_maximum(
    wide_sessions: async_sessionmaker[AsyncSession], migrated_db: Any
) -> None:
    conn = await asyncpg.connect(migrated_db.dsn)
    try:
        for n, reference in enumerate(("INV-000042", "INV-000007")):
            await conn.execute(
                "INSERT INTO invoices (id, invoice_reference, invoice_date, company_code,"
                " retailer_code, order_reference, amount, discount, total_amount, currency_code,"
                " status, paid_at, created_at, updated_at) VALUES ($1, $2, $3, 'ACME-CO', 'RET-9',"
                " $4, 10, 1, 9, 'EUR', 'issued', NULL, $3, $3)",
                uuid.uuid4(),
                reference,
                datetime.now(UTC),
                f"ORD-00000{n + 1}",
            )
        assert await conn.fetchval("SELECT count(*) FROM invoice_number_sequences") == 0
    finally:
        await conn.close()

    assert await _allocate_and_commit(wide_sessions) == "INV-000043"
    assert await _allocate_and_commit(wide_sessions) == "INV-000044"


async def test_the_reference_grows_past_six_digits_instead_of_truncating(
    wide_sessions: async_sessionmaker[AsyncSession], migrated_db: Any
) -> None:
    conn = await asyncpg.connect(migrated_db.dsn)
    try:
        await conn.execute(
            "INSERT INTO invoice_number_sequences (id, next_value) VALUES (1, 999999)"
        )
    finally:
        await conn.close()

    assert await _allocate_and_commit(wide_sessions) == "INV-999999"
    assert await _allocate_and_commit(wide_sessions) == "INV-1000000"
