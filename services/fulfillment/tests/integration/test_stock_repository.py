"""The stock repository and `StockTransactions.run` against a real PostgreSQL (D5 - D7).

No host and no NATS: the transactions are built directly over the test's engine, so the lock
protocol of `design.md` 6 is exercised by the constructed lock waits themselves.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from otc_fulfillment.application import stock_reservation
from otc_fulfillment.application.messages import (
    ReleaseStockCommand,
    ReserveOutcomeKind,
    ReserveStockCommand,
    StockLine,
)
from otc_fulfillment.application.ports.stock_store import (
    ConcurrentReservationChangeError,
    LockedStock,
    StockTransaction,
)
from otc_fulfillment.application.scope import FulfillmentScope
from otc_fulfillment.domain.events import ReleaseReason
from otc_fulfillment.infrastructure.clock import SystemClock
from otc_fulfillment.infrastructure.ids import UuidIdSource
from otc_fulfillment.infrastructure.outbox.writer import OutboxWriter
from otc_fulfillment.infrastructure.persistence.stock_reads import SqlAlchemyStockReads
from otc_fulfillment.infrastructure.persistence.stock_repository import SqlAlchemyStockRepository
from otc_fulfillment.infrastructure.persistence.stock_transactions import (
    SqlAlchemyStockTransactions,
)
from otc_shared_kernel import Quantity, UniqueId

COMPANY = "ACME-CO"
ORDER = "ORD-000050"


@pytest_asyncio.fixture(loop_scope="function")
async def transactions(engine: AsyncEngine) -> AsyncIterator[SqlAlchemyStockTransactions]:
    # function loop: the engine fixture is created and disposed in the loop that uses it
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    clock = SystemClock()
    yield SqlAlchemyStockTransactions(
        sessions=sessions, outbox=OutboxWriter(clock=clock), clock=clock
    )


@pytest.fixture
def scope(transactions: SqlAlchemyStockTransactions, engine: AsyncEngine) -> FulfillmentScope:
    return FulfillmentScope(
        transactions=transactions,
        reads=SqlAlchemyStockReads(async_sessionmaker(engine, expire_on_commit=False)),
        clock=SystemClock(),
        ids=UuidIdSource(),
    )


def reservation_insert() -> str:
    return (
        "INSERT INTO reservations (id, stock_id, company_code, retailer_code, product_code,"
        " order_reference, units, status, created_at, updated_at)"
        " SELECT $1, id, company_code, 'RET-9', product_code, $2, 3, 'reserved', $3, $3"
        " FROM stock WHERE company_code = $4 AND product_code = $5"
    )


async def test_fs19_the_reservation_read_made_after_the_stock_lock_sees_a_reservation_committed_while_it_waited(  # noqa: E501
    db: Any, transactions: SqlAlchemyStockTransactions
) -> None:
    await db.seed_stock(COMPANY, [("PRD-A1", 10, 0, 3)])
    # the test's connection FOLLOWS THE PROTOCOL: locks the stock row, inserts a reservation for
    # order X, updates the counter, and holds
    hold = await db.hold([(COMPANY, "PRD-A1")])
    reservation_id = uuid.uuid4()
    try:
        await hold.execute(
            reservation_insert(), reservation_id, ORDER, datetime.now(UTC), COMPANY, "PRD-A1"
        )
        await hold.execute("UPDATE stock SET reserved_units = 3 WHERE product_code = 'PRD-A1'")

        async def work(tx: StockTransaction) -> LockedStock:
            return await tx.repository.lock_for_reserve(COMPANY, ["PRD-A1"], ORDER)

        locking = asyncio.create_task(transactions.run(work))
        await db.wait_for_lock_waiters("SELECT%FROM stock%FOR UPDATE%", 1)  # seen UNGRANTED
        assert not locking.done()
        await hold.commit()

        locked = await asyncio.wait_for(locking, timeout=15)
    finally:
        await hold.rollback()

    assert [r.id.value for r in locked.reservations_of_order] == [reservation_id], (
        "the reservation committed while the lock waited is seen"
    )
    assert locked.items["PRD-A1"].reserved_units == 3, "and the counter is the UPDATED one"


async def test_fs25_the_release_lock_reads_the_orders_reservations_only_after_the_stock_lock_and_sees_a_reservation_committed_while_it_waited(  # noqa: E501
    db: Any, transactions: SqlAlchemyStockTransactions
) -> None:
    # D5's construction applied to the SA-4 lock (`lock_order_items`), the method `stock.release`
    # and feature 18's despatch call. The order ALREADY holds a reservation on PRD-A1.
    await db.seed_stock(COMPANY, [("PRD-A1", 10, 3, 3)])
    existing_id = uuid.uuid4()
    await db.execute(reservation_insert(), existing_id, ORDER, datetime.now(UTC), COMPANY, "PRD-A1")
    # the test's connection FOLLOWS THE PROTOCOL: locks the stock row, inserts a FURTHER reserved
    # reservation of the order on it, raises the counter, and holds
    hold = await db.hold([(COMPANY, "PRD-A1")])
    late_id = uuid.uuid4()
    try:
        await hold.execute(
            reservation_insert(), late_id, ORDER, datetime.now(UTC), COMPANY, "PRD-A1"
        )
        await hold.execute("UPDATE stock SET reserved_units = 6 WHERE product_code = 'PRD-A1'")

        async def work(tx: StockTransaction) -> LockedStock:
            return await tx.repository.lock_order_items(ORDER, [(COMPANY, "PRD-A1")])

        locking = asyncio.create_task(transactions.run(work))
        await db.wait_for_lock_waiters("SELECT%FROM stock%FOR UPDATE%", 1)  # seen UNGRANTED
        assert not locking.done()
        await hold.commit()

        locked = await asyncio.wait_for(locking, timeout=15)
    finally:
        await hold.rollback()

    assert {r.id.value for r in locked.reservations_of_order} == {existing_id, late_id}, (
        "the lock read the order's reservations BEFORE the stock lock was granted: "
        "the reservation committed while it waited is missing"
    )
    assert locked.items["PRD-A1"].reserved_units == 6, "and the counter is the UPDATED one"


async def test_the_release_lock_raises_concurrent_reservation_change_when_the_order_holds_a_reservation_on_a_stock_row_outside_the_keys(  # noqa: E501
    db: Any, transactions: SqlAlchemyStockTransactions
) -> None:
    await db.seed_stock(COMPANY, [("PRD-A1", 10, 3, 3), ("PRD-B2", 10, 3, 3)])
    for product in ("PRD-A1", "PRD-B2"):
        await db.execute(
            reservation_insert(), uuid.uuid4(), ORDER, datetime.now(UTC), COMPANY, product
        )

    async def outside(tx: StockTransaction) -> LockedStock:
        # the keys name ONLY PRD-A1; the order's second reservation sits on PRD-B2
        return await tx.repository.lock_order_items(ORDER, [(COMPANY, "PRD-A1")])

    with pytest.raises(ConcurrentReservationChangeError) as refusal:
        await transactions.run(outside)
    assert ORDER in str(refusal.value.args), "the error names the order"

    async def inside(tx: StockTransaction) -> LockedStock:
        return await tx.repository.lock_order_items(
            ORDER, [(COMPANY, "PRD-A1"), (COMPANY, "PRD-B2")]
        )

    # control: with every key given, the same data is accepted, so the raise above is the check
    assert len((await transactions.run(inside)).reservations_of_order) == 2


async def test_fs19_every_stock_transaction_runs_at_read_committed(
    transactions: SqlAlchemyStockTransactions,
) -> None:
    async def work(tx: StockTransaction) -> str:
        assert isinstance(tx.repository, SqlAlchemyStockRepository)
        session = tx.repository._session
        level = await session.scalar(text("SHOW transaction_isolation"))
        return str(level)

    assert await transactions.run(work) == "read committed"


async def test_the_reserve_lock_returns_every_reservation_of_the_order_including_products_outside_the_request(  # noqa: E501
    db: Any, transactions: SqlAlchemyStockTransactions
) -> None:
    await db.seed_stock(COMPANY, [("PRD-A1", 10, 3, 3), ("PRD-B2", 10, 0, 3)])
    reservation_id = uuid.uuid4()
    await db.execute(
        reservation_insert(), reservation_id, ORDER, datetime.now(UTC), COMPANY, "PRD-A1"
    )

    async def work(tx: StockTransaction) -> LockedStock:
        # the request names ONLY PRD-B2: the order's reservation sits on PRD-A1
        return await tx.repository.lock_for_reserve(COMPANY, ["PRD-B2"], ORDER)

    locked = await transactions.run(work)

    assert list(locked.items) == ["PRD-B2"]
    assert [(r.id.value, r.product_code) for r in locked.reservations_of_order] == [
        (reservation_id, "PRD-A1")
    ]


FS12_CHECK = (
    "SELECT s.company_code, s.product_code, s.reserved_units,"
    " coalesce(sum(r.units) FILTER (WHERE r.status = 'reserved'), 0) AS expected"
    " FROM stock s LEFT JOIN reservations r ON r.stock_id = s.id"
    " GROUP BY s.id HAVING s.reserved_units <> coalesce(sum(r.units) FILTER"
    " (WHERE r.status = 'reserved'), 0)"
)


def reserve_command(order: str, *lines: tuple[str, int]) -> ReserveStockCommand:
    return ReserveStockCommand(
        order_reference=order,
        company_code=COMPANY,
        retailer_code="RET-9",
        lines=tuple(StockLine(code, Quantity(units)) for code, units in lines),
        correlation_id=UniqueId(uuid.uuid4()),
        request_id=UniqueId(uuid.uuid4()),
    )


async def test_fs12_reserved_units_equals_the_sum_of_reserved_reservation_units_after_every_committed_operation(  # noqa: E501
    db: Any, transactions: SqlAlchemyStockTransactions, scope: FulfillmentScope
) -> None:
    await db.seed_stock(COMPANY, [("PRD-A1", 30, 0, 3), ("PRD-B2", 30, 0, 3)])

    result = await stock_reservation.reserve(
        reserve_command("ORD-000050", ("PRD-A1", 4), ("PRD-B2", 6), ("PRD-A1", 2)), scope
    )
    assert result.outcome is ReserveOutcomeKind.ACCEPTED
    await stock_reservation.reserve(reserve_command("ORD-000051", ("PRD-A1", 5)), scope)
    assert await db.fetch(FS12_CHECK) == [], "after two reserves"
    assert [(await db.stock(COMPANY, p))["reserved_units"] for p in ("PRD-A1", "PRD-B2")] == [11, 6]

    await stock_reservation.release(
        ReleaseStockCommand(
            order_reference="ORD-000050",
            reason=ReleaseReason.ORDER_CANCELLED,
            correlation_id=UniqueId(uuid.uuid4()),
            request_id=UniqueId(uuid.uuid4()),
        ),
        scope,
    )
    assert await db.fetch(FS12_CHECK) == [], "after a release"
    assert [(await db.stock(COMPANY, p))["reserved_units"] for p in ("PRD-A1", "PRD-B2")] == [5, 0]

    async def consume(tx: StockTransaction) -> int:
        locked = await tx.repository.lock_order_items("ORD-000051", [(COMPANY, "PRD-A1")])
        consumed = locked.items["PRD-A1"].consume("ORD-000051")
        await tx.repository.save()
        return len(consumed)

    assert await transactions.run(consume) == 1
    assert await db.fetch(FS12_CHECK) == [], "after a consume"
    a1 = await db.stock(COMPANY, "PRD-A1")
    assert (a1["units"], a1["reserved_units"]) == (30 - 5, 0)

    # control: the query CAN report a mismatch. A deliberately inconsistent row is reported.
    await db.seed_stock(COMPANY, [("PRD-BAD", 10, 7, 1)])  # reserved 7, no reservation at all
    [mismatch] = await db.fetch(FS12_CHECK)
    assert (mismatch["product_code"], mismatch["reserved_units"], mismatch["expected"]) == (
        "PRD-BAD",
        7,
        0,
    )


async def test_a_failure_after_save_inside_run_leaves_no_stock_change_no_reservation_and_no_outbox_row(  # noqa: E501
    db: Any, transactions: SqlAlchemyStockTransactions
) -> None:
    await db.seed_stock(COMPANY, [("PRD-A1", 30, 0, 3)])
    from otc_fulfillment.domain.order_stock_reservation import (
        Reserved,
        ReserveLine,
        ReserveOrderInput,
        StockContext,
        reserve_order,
    )

    async def work(tx: StockTransaction) -> None:
        locked = await tx.repository.lock_for_reserve(COMPANY, ["PRD-A1"], ORDER)
        outcome = reserve_order(
            locked.items,
            ReserveOrderInput(
                order_reference=ORDER,
                company_code=COMPANY,
                retailer_code="RET-9",
                lines=(ReserveLine(product_code="PRD-A1", units=Quantity(4)),),
                correlation_id=UniqueId(uuid.uuid4()),
            ),
            StockContext(occurred_at=datetime.now(UTC), causation_id=UniqueId(uuid.uuid4())),
            UniqueId.new,
        )
        assert isinstance(outcome, Reserved)
        await tx.repository.save()  # reservation row, counter and outbox row are all flushed ...
        raise RuntimeError("the transaction fails after save()")  # ... and then it fails

    with pytest.raises(RuntimeError, match="after save"):
        await transactions.run(work)

    a1 = await db.stock(COMPANY, "PRD-A1")
    assert (a1["units"], a1["reserved_units"]) == (30, 0), "no stock change"
    assert await db.reservations(ORDER) == [], "no reservation"
    assert await db.outbox() == [], "no outbox row"
