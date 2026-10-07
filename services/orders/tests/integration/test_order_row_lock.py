"""A saga step loads its order `FOR UPDATE OF orders` (SO17; `design.md` 7.2).

PostgreSQL only. Two transactions through the REAL unit of work: the second one's load is observed
WAITING in `pg_locks` (not granted) until the first commits a status change, and then reads that
status; and the lock holds the order's own row only: a third connection takes the order's retailer,
company and currency rows `FOR UPDATE NOWAIT` while the order is held.
"""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime

import asyncpg
import pytest

from otc_orders.domain.order import Order
from otc_orders.domain.value_objects.order_status import OrderStatus
from otc_orders.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

LATER = datetime(2026, 10, 6, 9, 0, 0, 0, tzinfo=UTC)
WAITING = "SELECT count(*) FROM pg_locks WHERE NOT granted AND locktype = 'transactionid'"


async def saved_order(uow: SqlAlchemyUnitOfWork, place_order: Callable[..., Order]) -> Order:
    order = place_order()
    async with uow.begin() as transaction:
        await transaction.orders.save(order)
    return order


async def test_so17_a_second_transaction_loading_the_same_order_for_update_waits_for_the_first(
    uow: SqlAlchemyUnitOfWork,
    place_order: Callable[..., Order],
    migrated_db: asyncpg.Record,
) -> None:
    order = await saved_order(uow, place_order)
    dsn = migrated_db.dsn  # type: ignore[attr-defined]
    observer = await asyncpg.connect(dsn)
    holding, release = asyncio.Event(), asyncio.Event()

    async def first() -> None:
        async with uow.begin() as transaction:
            loaded = await transaction.orders.get_by_id_for_update(order.id)
            assert loaded is not None
            holding.set()
            await release.wait()
            loaded.mark_stock_reserved(occurred_at=LATER)
            await transaction.orders.save(loaded)

    async def second() -> OrderStatus:
        async with uow.begin() as transaction:
            loaded = await transaction.orders.get_by_id_for_update(order.id)
            assert loaded is not None
            return loaded.status

    first_task = asyncio.create_task(first())
    try:
        await asyncio.wait_for(holding.wait(), timeout=10)
        second_task = asyncio.create_task(second())
        try:
            async with asyncio.timeout(10):
                while await observer.fetchval(WAITING) == 0:  # noqa: ASYNC110 - polling pg_locks
                    await asyncio.sleep(0.02)
            assert not second_task.done(), "the second load is waiting, not served"
            assert await observer.fetchval(WAITING) >= 1, "its lock request is NOT granted"
        finally:
            release.set()
        status = await asyncio.wait_for(second_task, timeout=10)
        await asyncio.wait_for(first_task, timeout=10)
    finally:
        release.set()
        await observer.close()

    assert status is OrderStatus.STOCK_RESERVED, "the second reads what the first committed"


@pytest.mark.parametrize(
    ("table", "code"),
    [("retailers", "RET-01"), ("companies", "CMP-01"), ("currencies", "EUR")],
)
async def test_so17_the_lock_holds_the_order_row_and_no_reference_data_row(
    table: str,
    code: str,
    uow: SqlAlchemyUnitOfWork,
    place_order: Callable[..., Order],
    migrated_db: asyncpg.Record,
) -> None:
    order = await saved_order(uow, place_order)
    holding, release = asyncio.Event(), asyncio.Event()

    async def hold() -> None:
        async with uow.begin() as transaction:
            assert await transaction.orders.get_by_id_for_update(order.id) is not None
            holding.set()
            await release.wait()

    holder = asyncio.create_task(hold())
    third = await asyncpg.connect(migrated_db.dsn)  # type: ignore[attr-defined]
    try:
        await asyncio.wait_for(holding.wait(), timeout=10)
        try:
            row = await third.fetchrow(
                f"SELECT id FROM {table} WHERE code = $1 FOR UPDATE NOWAIT",  # noqa: S608
                code,
            )
        except asyncpg.LockNotAvailableError:
            pytest.fail(
                f"the {table} row {code!r} is locked by the order load: the lock is too wide"
            )
        assert row is not None
    finally:
        release.set()
        await third.close()
        await asyncio.wait_for(holder, timeout=10)


async def test_the_plain_read_does_not_lock_the_order(
    uow: SqlAlchemyUnitOfWork,
    place_order: Callable[..., Order],
    migrated_db: asyncpg.Record,
) -> None:
    order = await saved_order(uow, place_order)
    holding, release = asyncio.Event(), asyncio.Event()

    async def hold() -> None:
        async with uow.begin() as transaction:
            assert await transaction.orders.get_by_id(order.id) is not None
            holding.set()
            await release.wait()

    holder = asyncio.create_task(hold())
    third = await asyncpg.connect(migrated_db.dsn)  # type: ignore[attr-defined]
    try:
        await asyncio.wait_for(holding.wait(), timeout=10)
        row = await third.fetchrow(
            "SELECT id FROM orders WHERE id = $1 FOR UPDATE NOWAIT", order.id.value
        )
        assert row is not None, "get_by_id keeps its plain read for feature 15's callers"
    finally:
        release.set()
        await third.close()
        await asyncio.wait_for(holder, timeout=10)
