"""The idempotent consumer against a real PostgreSQL (feature 14, 6.2-6.6): R17, R18, OI10.

Loop scope: default (function); every engine and session lives in the test's own loop.
The dedup row, the state change, the outbox rows and a `saga_commands` row are all in ONE
transaction (R17 literally): each test reads them back with a fresh session.
"""

import asyncio
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from otc_orders.domain.order import Order
from otc_orders.domain.value_objects.order_status import OrderStatus
from otc_orders.infrastructure.clock import SystemClock
from otc_orders.infrastructure.messaging.consumer_name import ConsumerName
from otc_orders.infrastructure.messaging.idempotent_consumer import (
    ConsumptionOutcome,
    IdempotentConsumer,
)
from otc_orders.infrastructure.outbox.writer import OutboxWriter
from otc_orders.infrastructure.persistence.models import Order as OrderRow
from otc_orders.infrastructure.persistence.unit_of_work import (
    SqlAlchemyOrdersTransaction,
    SqlAlchemyUnitOfWork,
)
from otc_shared_kernel import Quantity, UniqueId

INSTANT = datetime(2026, 10, 5, 12, 0, 0, 123000, tzinfo=UTC)


class Boom(Exception):
    pass


async def processed_rows(dsn: str) -> list[tuple[uuid.UUID, str]]:
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch("SELECT event_id, consumer FROM processed_events ORDER BY consumer")
    finally:
        await conn.close()
    return [(r["event_id"], r["consumer"]) for r in rows]


async def count(sessions: async_sessionmaker[AsyncSession], sql: str) -> int:
    async with sessions() as session:
        found = await session.scalar(text(sql))
    assert found is not None
    return int(found)


async def order_row(
    sessions: async_sessionmaker[AsyncSession], order: Order
) -> tuple[str, datetime]:
    async with sessions() as session:
        row = (await session.scalars(select(OrderRow).where(OrderRow.id == order.id.value))).one()
        return row.status, row.updated_at


@pytest.fixture
def consumer(uow: SqlAlchemyUnitOfWork, clock: SystemClock) -> IdempotentConsumer[Any]:
    return IdempotentConsumer(begin=uow.begin, clock=clock.now)


async def saved_order(uow: SqlAlchemyUnitOfWork, place_order: Any, reference: str) -> Order:
    order: Order = place_order(order_reference=reference, occurred_at=INSTANT)
    async with uow.begin() as tx:
        await tx.orders.save(order)
    return order


async def confirm_step(tx: SqlAlchemyOrdersTransaction, order_id: UniqueId, at: datetime) -> None:
    order = await tx.orders.get_by_id(order_id)
    assert order is not None
    order.mark_stock_reserved(occurred_at=at)
    order.approve_credit(occurred_at=at)
    order.confirm(occurred_at=at, causation_id=UniqueId.new())
    await tx.orders.save(order)


async def test_r17_records_the_event_id_and_consumer_name_in_the_same_transaction_as_the_state_change_and_the_outbox_records(  # noqa: E501
    consumer: IdempotentConsumer[Any],
    uow: SqlAlchemyUnitOfWork,
    sessions: async_sessionmaker[AsyncSession],
    place_order: Any,
    migrated_db: Any,
) -> None:
    order = await saved_order(uow, place_order, "ORD-000051")
    first_event = uuid.uuid4()

    async def work(tx: SqlAlchemyOrdersTransaction) -> None:
        await confirm_step(tx, order.id, INSTANT + timedelta(minutes=1))

    outcome = await consumer.run_once(first_event, ConsumerName.ORDERS_SAGA, work)
    assert outcome is ConsumptionOutcome.PROCESSED
    assert await processed_rows(migrated_db.dsn) == [(first_event, "orders.saga")]
    assert (await order_row(sessions, order))[0] == "confirmed", "the state change committed"
    assert await count(sessions, "SELECT count(*) FROM outbox") == 2, "placed + confirmed"

    # --- the failing sibling, in the same case: a failure AFTER the writes leaves nothing at all
    second_event = uuid.uuid4()
    status_before, updated_before = await order_row(sessions, order)

    async def failing_work(tx: SqlAlchemyOrdersTransaction) -> None:
        loaded = await tx.orders.get_by_id(order.id)
        assert loaded is not None
        loaded.mark_despatched(occurred_at=INSTANT + timedelta(minutes=9))
        loaded.mark_invoiced(occurred_at=INSTANT + timedelta(minutes=10))
        loaded.mark_paid(occurred_at=INSTANT + timedelta(minutes=11))
        loaded.complete(occurred_at=INSTANT + timedelta(minutes=12), causation_id=UniqueId.new())
        await tx.orders.save(loaded)
        raise Boom

    with pytest.raises(Boom):
        await consumer.run_once(second_event, ConsumerName.ORDERS_SAGA, failing_work)
    assert await processed_rows(migrated_db.dsn) == [(first_event, "orders.saga")], "no dedup row"
    assert await order_row(sessions, order) == (status_before, updated_before), "no order change"
    assert await count(sessions, "SELECT count(*) FROM outbox") == 2, "no outbox row"


async def test_r17_leaves_no_dedup_row_when_a_failure_inside_work_rolls_back_the_whole_transaction(
    consumer: IdempotentConsumer[Any],
    uow: SqlAlchemyUnitOfWork,
    sessions: async_sessionmaker[AsyncSession],
    place_order: Any,
    migrated_db: Any,
) -> None:
    order = await saved_order(uow, place_order, "ORD-000052")
    event_id = uuid.uuid4()

    async def work(tx: SqlAlchemyOrdersTransaction) -> None:
        await confirm_step(tx, order.id, INSTANT + timedelta(minutes=1))
        raise Boom

    with pytest.raises(Boom):
        await consumer.run_once(event_id, ConsumerName.ORDERS_SAGA, work)
    assert await processed_rows(migrated_db.dsn) == [], "the dedup row rolled back with the work"
    assert (await order_row(sessions, order))[0] == "placed"
    assert await count(sessions, "SELECT count(*) FROM outbox") == 1, "only the placing fact"

    # the redelivery after a failure is processed (nothing was recorded): not a duplicate
    async def good(tx: SqlAlchemyOrdersTransaction) -> None:
        await confirm_step(tx, order.id, INSTANT + timedelta(minutes=2))

    assert await consumer.run_once(event_id, ConsumerName.ORDERS_SAGA, good) is (
        ConsumptionOutcome.PROCESSED
    )


async def test_r18_acknowledges_a_redelivered_fact_without_mutating_state_emitting_a_fact_or_issuing_a_command(  # noqa: E501
    consumer: IdempotentConsumer[Any],
    uow: SqlAlchemyUnitOfWork,
    sessions: async_sessionmaker[AsyncSession],
    place_order: Any,
    clock: SystemClock,
) -> None:
    """`work` changes the order, saves a NEW order (so each invocation writes a fresh outbox row)
    and inserts a `saga_commands` row by raw SQL: all three effects discriminate. Every invocation
    differs from the last (a new quantity, a new instant, a new command name), so a `work` that ran
    again on the redelivery could not hide behind identical values."""
    target = await saved_order(uow, place_order, "ORD-000053")
    invocations: list[int] = []

    async def work(tx: SqlAlchemyOrdersTransaction) -> None:
        invocations.append(len(invocations))
        await asyncio.sleep(0.01)  # distinct `updated_at` milliseconds per invocation
        loaded = await tx.orders.get_by_id(target.id)
        assert loaded is not None
        if loaded.status is OrderStatus.PLACED:
            loaded.mark_stock_reserved(occurred_at=clock.now())
        loaded.change_line(
            line_id=loaded.lines[0].id,
            quantity=Quantity(50 + len(invocations)),
            unit_price=loaded.lines[0].unit_price,
            line_discount=loaded.lines[0].line_discount,
            occurred_at=clock.now(),
        )
        await tx.orders.save(loaded)  # the aggregate change
        fresh = place_order(order_reference=f"ORD-1{len(invocations):05d}", occurred_at=clock.now())
        await tx.orders.save(fresh)  # an outbox row: the OrderPlaced fact
        await tx.session.execute(  # a command row, by raw SQL
            text(
                "INSERT INTO saga_commands (id, order_id, order_reference, command, payload, "
                "triggering_event_id, created_at, updated_at) VALUES "
                "(:id, :order_id, :ref, :command, '{}'::json, :trigger, :now, :now)"
            ),
            {
                "id": uuid.uuid4(),
                "order_id": target.id.value,
                "ref": "ORD-000053",
                "command": f"stock.reserve.{len(invocations)}",
                "trigger": uuid.uuid4(),
                "now": clock.now(),
            },
        )

    event_id = uuid.uuid4()
    assert await consumer.run_once(event_id, ConsumerName.ORDERS_SAGA, work) is (
        ConsumptionOutcome.PROCESSED
    )
    # positive control: the first delivery wrote all three effects
    state_after_first = await order_row(sessions, target)
    outbox_after_first = await count(sessions, "SELECT count(*) FROM outbox")
    commands_after_first = await count(sessions, "SELECT count(*) FROM saga_commands")
    assert state_after_first[0] == "stock_reserved", "the order changed"
    assert outbox_after_first == 2, "target placed + the fresh order placed"
    assert commands_after_first == 1, "a command row was issued"

    # the redelivery
    outcome = await consumer.run_once(event_id, ConsumerName.ORDERS_SAGA, work)
    assert outcome is ConsumptionOutcome.DUPLICATE
    assert invocations == [0], "work was invoked once in total"
    assert await order_row(sessions, target) == state_after_first, "the order row (re-read) moved"
    assert await count(sessions, "SELECT count(*) FROM outbox") == outbox_after_first, (
        "a fact was emitted on a redelivery"
    )
    assert await count(sessions, "SELECT count(*) FROM saga_commands") == commands_after_first, (
        "a command was issued on a redelivery"
    )


async def wait_until_ungranted(dsn: str, application_name: str) -> None:
    admin = await asyncpg.connect(dsn)
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            waiting = await admin.fetchval(
                "SELECT count(*) FROM pg_locks l JOIN pg_stat_activity a USING (pid) "
                "WHERE NOT l.granted AND a.application_name = $1",
                application_name,
            )
            if waiting:
                return
            await asyncio.sleep(0.05)
    finally:
        await admin.close()
    raise TimeoutError(f"{application_name} was never observed waiting in pg_locks")


async def test_oi10_applies_the_effects_once_when_the_same_event_is_delivered_concurrently(
    sessions: async_sessionmaker[AsyncSession], clock: SystemClock, migrated_db: Any
) -> None:
    engines = [
        create_async_engine(
            migrated_db.url, connect_args={"server_settings": {"application_name": name}}
        )
        for name in ("consumer-1", "consumer-2")
    ]
    try:
        consumers = [
            IdempotentConsumer(
                begin=SqlAlchemyUnitOfWork(
                    sessions=async_sessionmaker(engine, expire_on_commit=False),
                    outbox=OutboxWriter(clock=clock),
                ).begin,
                clock=clock.now,
            )
            for engine in engines
        ]
        event_id = uuid.uuid4()
        entered = asyncio.Event()
        proceed = asyncio.Event()
        ran: list[str] = []

        async def first_work(tx: SqlAlchemyOrdersTransaction) -> None:
            ran.append("first")
            entered.set()
            await proceed.wait()  # block AFTER the dedup insert

        async def second_work(tx: SqlAlchemyOrdersTransaction) -> None:
            ran.append("second")

        task_one = asyncio.create_task(
            consumers[0].run_once(event_id, ConsumerName.ORDERS_SAGA, first_work)
        )
        await asyncio.wait_for(entered.wait(), timeout=10)
        task_two = asyncio.create_task(
            consumers[1].run_once(event_id, ConsumerName.ORDERS_SAGA, second_work)
        )
        await wait_until_ungranted(migrated_db.dsn, "consumer-2")  # the race is REAL: it waits
        assert not task_two.done()
        proceed.set()
        outcomes = await asyncio.wait_for(asyncio.gather(task_one, task_two), timeout=15)
    finally:
        for engine in engines:
            await engine.dispose()

    assert list(outcomes) == [ConsumptionOutcome.PROCESSED, ConsumptionOutcome.DUPLICATE]
    assert ran == ["first"], "the effects were applied exactly once"
    assert await processed_rows(migrated_db.dsn) == [(event_id, "orders.saga")]


async def test_dedup_is_per_event_id_and_consumer_pair_not_per_event_id(
    consumer: IdempotentConsumer[Any], migrated_db: Any
) -> None:
    event_id = uuid.uuid4()
    ran: list[str] = []

    async def work(tx: SqlAlchemyOrdersTransaction) -> None:
        ran.append("ran")

    saga = await consumer.run_once(event_id, ConsumerName.ORDERS_SAGA, work)
    projector = await consumer.run_once(event_id, ConsumerName.PROJECTOR, work)
    assert (saga, projector) == (ConsumptionOutcome.PROCESSED, ConsumptionOutcome.PROCESSED)
    assert await processed_rows(migrated_db.dsn) == [
        (event_id, "orders.saga"),
        (event_id, "projector"),
    ]
    assert len(ran) == 2
    again = await consumer.run_once(event_id, ConsumerName.PROJECTOR, work)
    assert again is ConsumptionOutcome.DUPLICATE
