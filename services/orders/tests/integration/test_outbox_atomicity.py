"""R13 and OI9: the aggregate and its outbox records commit together, or neither (feature 14).

The failure is forced AFTER the rows are provably visible inside the transaction (read back through
the transaction's own session), so "nothing is there" afterwards is the rollback's work and not an
insert that never happened. Loop scope: the default (function) for every engine, session and relay.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from otc_orders.domain.order import Order
from otc_orders.infrastructure.clock import SystemClock
from otc_orders.infrastructure.outbox.payloads import narrow
from otc_orders.infrastructure.outbox.publisher import PublishableFact
from otc_orders.infrastructure.outbox.relay import OutboxRelay
from otc_orders.infrastructure.persistence.models import Order as OrderRow
from otc_orders.infrastructure.persistence.models import OrderItem, Outbox
from otc_orders.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from otc_shared_kernel import UniqueId

INSTANT = datetime(2026, 10, 5, 12, 0, 0, 123000, tzinfo=UTC)


class RecordingPublisher:
    def __init__(self) -> None:
        self.published: list[PublishableFact] = []

    async def publish(self, facts: Any) -> None:
        self.published.extend(facts)


class Boom(Exception):
    pass


def confirmed(order: Order) -> Order:
    """Walk a placed order to `confirmed`: two facts in all (placed, confirmed)."""
    order.mark_stock_reserved(occurred_at=INSTANT + timedelta(minutes=1))
    order.approve_credit(occurred_at=INSTANT + timedelta(minutes=2))
    order.confirm(occurred_at=INSTANT + timedelta(minutes=3), causation_id=UniqueId.new())
    return order


def event_ids(order: Order) -> list[UUID]:
    return [narrow(event).event_id.value for event in order.domain_events]


async def counts_in(session: AsyncSession, order: Order) -> tuple[int, int, int]:
    """(orders rows, order_items rows, outbox rows) of this order, as `session` sees them."""
    orders = await session.scalar(
        select(func.count()).select_from(OrderRow).where(OrderRow.id == order.id.value)
    )
    items = await session.scalar(
        select(func.count()).select_from(OrderItem).where(OrderItem.order_id == order.id.value)
    )
    outbox = await session.scalar(
        select(func.count()).select_from(Outbox).where(Outbox.aggregate_id == order.id.value)
    )
    assert orders is not None
    assert items is not None
    assert outbox is not None
    return orders, items, outbox


async def counts(sessions: async_sessionmaker[AsyncSession], order: Order) -> tuple[int, int, int]:
    async with sessions() as session:
        return await counts_in(session, order)


async def save_then_fail(
    uow: SqlAlchemyUnitOfWork, order: Order, expected: tuple[int, ...]
) -> None:
    async with uow.begin() as tx:
        await tx.orders.save(order)
        assert await counts_in(tx.session, order) == expected, "visible inside the transaction"
        raise Boom


async def save_both(uow: SqlAlchemyUnitOfWork, first: Order, second: Order) -> None:
    async with uow.begin() as tx:
        await tx.orders.save(first)
        assert await counts_in(tx.session, first) == (1, 2, 1), "the first save is visible"
        await tx.orders.save(second)  # the same order_reference: this flush raises


async def test_r13_persists_neither_the_aggregate_nor_the_outbox_record_and_publishes_nothing_when_the_transaction_fails(  # noqa: E501
    uow: SqlAlchemyUnitOfWork,
    sessions: async_sessionmaker[AsyncSession],
    place_order: Any,
    clock: SystemClock,
) -> None:
    # --- control: the success path writes one orders row, its two items and one row per event
    control = confirmed(place_order(order_reference="ORD-000001", occurred_at=INSTANT))
    control_events = event_ids(control)
    assert len(control_events) == 2
    async with uow.begin() as tx:
        await tx.orders.save(control)
    assert await counts(sessions, control) == (1, 2, 2)

    # --- the failure: rows are visible inside the transaction, then the unit of work fails
    doomed = place_order(order_reference="ORD-000002", occurred_at=INSTANT)
    doomed_events = event_ids(doomed)
    assert len(doomed_events) == 1
    with pytest.raises(Boom):
        await save_then_fail(uow, doomed, (1, 2, 1))

    assert await counts(sessions, doomed) == (0, 0, 0)
    publisher = RecordingPublisher()
    relay = OutboxRelay(
        sessions=sessions, publisher=publisher, clock=clock, batch_size=100, publish_timeout=5.0
    )
    result = await relay.run_once()
    published = [fact.event_id for fact in publisher.published]
    assert set(published).isdisjoint(doomed_events), (
        "nothing of the failed transaction is published"
    )
    assert published == control_events, "only the control's two facts exist to be published"
    assert result.published == 2


async def test_r13_rolls_back_an_outbox_row_already_written_when_a_later_save_in_the_same_transaction_fails(  # noqa: E501
    uow: SqlAlchemyUnitOfWork,
    sessions: async_sessionmaker[AsyncSession],
    place_order: Any,
) -> None:
    first = place_order(order_reference="ORD-000003", occurred_at=INSTANT)
    second = place_order(order_reference="ORD-000003", occurred_at=INSTANT)  # same reference
    with pytest.raises(IntegrityError):
        await save_both(uow, first, second)

    assert await counts(sessions, first) == (0, 0, 0), "the first order's rows are gone too"
    assert await counts(sessions, second) == (0, 0, 0)


async def test_oi9_a_retry_from_the_same_instance_after_a_rollback_writes_exactly_one_outbox_row_per_event(  # noqa: E501
    uow: SqlAlchemyUnitOfWork,
    sessions: async_sessionmaker[AsyncSession],
    place_order: Any,
) -> None:
    order = confirmed(place_order(order_reference="ORD-000004", occurred_at=INSTANT))
    events = event_ids(order)
    assert len(events) == 2

    with pytest.raises(Boom):
        await save_then_fail(uow, order, (1, 2, 2))
    assert await counts(sessions, order) == (0, 0, 0)
    assert event_ids(order) == events, "a rolled-back unit of work must not clear the events"

    async with uow.begin() as tx:  # the retry: the SAME instance, a new transaction
        await tx.orders.save(order)
    async with sessions() as session:
        stored = (
            await session.scalars(
                select(Outbox.event_id)
                .where(Outbox.aggregate_id == order.id.value)
                .order_by(Outbox.seq)
            )
        ).all()
    assert list(stored) == events, "exactly one outbox row per event, in raise order, never zero"
    assert order.domain_events == (), "cleared only after the commit"
