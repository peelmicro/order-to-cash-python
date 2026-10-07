"""R12, OI1, OI19: the envelope the writer stores and the relay rebuilds (feature 14, 3.12-3.14).

Every identity in these tests is distinct (the order id, the two causation ids, the event ids), so
a writer that copies `event_id` into `causation_id`, or reads `correlation_id` from the wrong field,
produces a value the assertions cannot mistake for the right one. Loop scope: default (function).
"""

import dataclasses
import json
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import asyncpg
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from otc_orders.domain.events import OrderConfirmed
from otc_orders.domain.order import Order
from otc_orders.infrastructure.clock import SystemClock
from otc_orders.infrastructure.outbox.errors import UndeclaredFactError
from otc_orders.infrastructure.outbox.publisher import PublishableFact
from otc_orders.infrastructure.outbox.relay import OutboxRelay
from otc_orders.infrastructure.outbox.wire import to_publishable_fact
from otc_orders.infrastructure.outbox.writer import OutboxWriter
from otc_orders.infrastructure.persistence.models import Outbox
from otc_orders.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from otc_shared_kernel import IncompleteDomainEventEnvelopeError, Money, Quantity, UniqueId

INSTANT = datetime(2026, 10, 5, 12, 0, 0, 123000, tzinfo=UTC)


class RecordingPublisher:
    def __init__(self) -> None:
        self.published: list[PublishableFact] = []

    async def publish(self, facts: Any) -> None:
        self.published.extend(facts)


def relay_over(
    sessions: async_sessionmaker[AsyncSession], publisher: RecordingPublisher, clock: SystemClock
) -> OutboxRelay:
    return OutboxRelay(
        sessions=sessions, publisher=publisher, clock=clock, batch_size=100, publish_timeout=5.0
    )


async def stored_rows(sessions: async_sessionmaker[AsyncSession]) -> list[Outbox]:
    async with sessions() as session:
        return list((await session.scalars(select(Outbox).order_by(Outbox.seq))).all())


async def test_r12_stamps_every_fact_of_one_order_with_the_order_id_as_correlation_id_and_the_causing_event_id_as_causation_id(  # noqa: E501
    uow: SqlAlchemyUnitOfWork, sessions: async_sessionmaker[AsyncSession], place_order: Any
) -> None:
    placing_cause, confirming_cause = UniqueId.new(), UniqueId.new()
    order: Order = place_order(occurred_at=INSTANT, causation_id=placing_cause)
    order.mark_stock_reserved(occurred_at=INSTANT + timedelta(minutes=1))
    order.approve_credit(occurred_at=INSTANT + timedelta(minutes=2))
    order.confirm(occurred_at=INSTANT + timedelta(minutes=3), causation_id=confirming_cause)
    async with uow.begin() as tx:
        await tx.orders.save(order)

    placed_row, confirmed_row = await stored_rows(sessions)
    assert placed_row.event_type == "order.placed.v1"
    assert confirmed_row.event_type == "order.confirmed.v1"
    assert {placing_cause.value, confirming_cause.value, order.id.value}.__len__() == 3
    assert placed_row.correlation_id == confirmed_row.correlation_id == order.id.value
    assert placed_row.aggregate_id == confirmed_row.aggregate_id == order.id.value
    assert placed_row.causation_id == placing_cause.value
    assert confirmed_row.causation_id == confirming_cause.value
    assert placed_row.event_id != confirmed_row.event_id
    assert order.id.value not in {placed_row.event_id, confirmed_row.event_id}


async def test_oi1_relay_reconstructs_the_complete_envelope_from_the_stored_record_alone(
    uow: SqlAlchemyUnitOfWork, sessions: async_sessionmaker[AsyncSession], place_order: Any
) -> None:
    cause = UniqueId.new()
    order: Order = place_order(occurred_at=INSTANT, causation_id=cause, notes="dock 4")
    async with uow.begin() as tx:
        await tx.orders.save(order)
    (row,) = await stored_rows(sessions)

    fact = to_publishable_fact(row)  # given ONLY the stored row: no clock, no uuid4, no default
    envelope = json.loads(fact.value)

    assert list(envelope) == [
        "eventId",
        "eventType",
        "aggregateId",
        "correlationId",
        "causationId",
        "occurredAt",
        "payload",
    ]
    assert envelope["eventId"] == str(row.event_id)
    assert envelope["eventType"] == "order.placed.v1"
    assert envelope["aggregateId"] == str(order.id)
    assert envelope["correlationId"] == str(order.id)
    assert envelope["causationId"] == str(cause)
    assert envelope["occurredAt"] == "2026-10-05T12:00:00.123Z"
    assert envelope["payload"]["orderReference"] == "ORD-000001"
    assert envelope["payload"]["notes"] == "dock 4"
    assert fact.key == str(order.id).encode("utf-8")
    assert fact.event_id == row.event_id


def only_event(order: Order) -> OrderConfirmed:
    (event,) = [e for e in order.domain_events if isinstance(e, OrderConfirmed)]
    return event


def confirmed_order(place_order: Any) -> Order:
    order: Order = place_order(occurred_at=INSTANT)
    order.mark_stock_reserved(occurred_at=INSTANT + timedelta(minutes=1))
    order.approve_credit(occurred_at=INSTANT + timedelta(minutes=2))
    order.confirm(occurred_at=INSTANT + timedelta(minutes=3), causation_id=UniqueId.new())
    return order


async def count_outbox(session: AsyncSession) -> int:
    found = await session.scalar(select(func.count()).select_from(Outbox))
    assert found is not None
    return found


@pytest.mark.parametrize(
    ("field", "absent"),
    [
        ("event_id", None),
        ("aggregate_id", None),
        ("correlation_id", None),
        ("causation_id", None),
        ("occurred_at", datetime(2026, 10, 5, 12, 0, 0)),  # naive: no instant
    ],
)
async def test_oi1_writer_refuses_an_event_with_an_incomplete_envelope_before_any_row_is_written(
    field: str,
    absent: Any,
    sessions: async_sessionmaker[AsyncSession],
    place_order: Any,
    clock: SystemClock,
) -> None:
    changes: dict[str, Any] = {field: absent}  # a frozen dataclass does not stop None
    broken = dataclasses.replace(only_event(confirmed_order(place_order)), **changes)
    async with sessions() as session, session.begin():
        with pytest.raises(IncompleteDomainEventEnvelopeError, match=field):
            await OutboxWriter(clock=clock).write(session, [broken])
        assert await count_outbox(session) == 0, "no row was written before the refusal"


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class OrderShipped(OrderConfirmed):
    """Pattern-valid (`<aggregate>.<fact>.v<n>`) and NOT in the fact catalogue."""

    EVENT_TYPE: ClassVar[str] = "order.shipped.v1"


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class OrderConfirmedAsCompleted(OrderConfirmed):
    """A catalogued type (`order.completed.v1`) carrying the WRONG payload model."""

    EVENT_TYPE: ClassVar[str] = "order.completed.v1"


def reclassed[E: OrderConfirmed](event: OrderConfirmed, kind: type[E]) -> E:
    return kind(**{f.name: getattr(event, f.name) for f in dataclasses.fields(event)})


async def test_oi1_writer_refuses_an_event_type_outside_the_fact_catalogue(
    sessions: async_sessionmaker[AsyncSession], place_order: Any, clock: SystemClock
) -> None:
    undeclared = reclassed(only_event(confirmed_order(place_order)), OrderShipped)
    async with sessions() as session, session.begin():
        with pytest.raises(UndeclaredFactError, match=r"order\.shipped\.v1") as raised:
            await OutboxWriter(clock=clock).write(session, [undeclared])
        assert raised.value.event_type == "order.shipped.v1"
        assert "no model is registered" in str(raised.value)
        assert await count_outbox(session) == 0


async def test_oi1_writer_refuses_a_payload_that_is_not_the_catalogues_payload_for_the_type(
    sessions: async_sessionmaker[AsyncSession], place_order: Any, clock: SystemClock
) -> None:
    mismatched = reclassed(only_event(confirmed_order(place_order)), OrderConfirmedAsCompleted)
    async with sessions() as session, session.begin():
        with pytest.raises(UndeclaredFactError, match="OrderConfirmedPayload") as raised:
            await OutboxWriter(clock=clock).write(session, [mismatched])
        assert raised.value.event_type == "order.completed.v1"
        assert await count_outbox(session) == 0


async def test_oi19_a_sub_millisecond_instant_is_stored_enveloped_and_written_in_the_payload_as_the_same_millisecond(  # noqa: E501
    uow: SqlAlchemyUnitOfWork,
    sessions: async_sessionmaker[AsyncSession],
    place_order: Any,
    migrated_db: Any,
    clock: SystemClock,
) -> None:
    sub_millisecond = datetime(2026, 10, 5, 12, 0, 5, 123987, tzinfo=UTC)
    order = place_order(occurred_at=INSTANT)
    order.mark_stock_reserved(occurred_at=INSTANT + timedelta(minutes=1))
    order.approve_credit(occurred_at=INSTANT + timedelta(minutes=2))
    order.confirm(occurred_at=sub_millisecond, causation_id=UniqueId.new())
    assert order.updated_at.microsecond == 123987, "the premise: the aggregate holds microseconds"
    async with uow.begin() as tx:
        await tx.orders.save(order)

    conn = await asyncpg.connect(migrated_db.dsn)
    try:
        stored_occurred_at: datetime = await conn.fetchval(
            "SELECT occurred_at FROM outbox WHERE event_type = 'order.confirmed.v1'"
        )
        stored_updated_at: datetime = await conn.fetchval(
            "SELECT updated_at FROM orders WHERE id = $1", order.id.value
        )
    finally:
        await conn.close()
    publisher = RecordingPublisher()
    await relay_over(sessions, publisher, clock).run_once()
    (envelope,) = [
        json.loads(f.value) for f in publisher.published if b"order.confirmed.v1" in f.value
    ]

    expected = datetime(2026, 10, 5, 12, 0, 5, 123000, tzinfo=UTC)
    assert stored_occurred_at == expected
    assert stored_updated_at == expected
    assert envelope["occurredAt"] == "2026-10-05T12:00:05.123Z"
    assert envelope["payload"]["confirmedAt"] == "2026-10-05T12:00:05.123Z"


async def stored_header(dsn: str, order: Order) -> tuple[datetime, datetime, datetime]:
    conn = await asyncpg.connect(dsn)
    try:
        row = await conn.fetchrow(
            "SELECT order_date, created_at, updated_at FROM orders WHERE id = $1", order.id.value
        )
    finally:
        await conn.close()
    assert row is not None
    return row["order_date"], row["created_at"], row["updated_at"]


async def test_oi19_every_instant_column_the_repository_writes_is_stored_truncated_never_rounded(
    uow: SqlAlchemyUnitOfWork, place_order: Any, migrated_db: Any
) -> None:
    """The writer's own instants are covered above; this covers the REPOSITORY's: every instant
    column on the insert path and on the update path, with `.123987` (`timestamptz(3)` would round
    it to `.124`)."""
    placed_at = datetime(2026, 10, 5, 12, 0, 1, 123987, tzinfo=UTC)
    order_date = datetime(2026, 10, 5, 11, 0, 2, 123987, tzinfo=UTC)
    order = place_order(occurred_at=placed_at, order_date=order_date)
    async with uow.begin() as tx:
        await tx.orders.save(order)
    # the INSERT path, read before any update can overwrite it
    assert await stored_header(migrated_db.dsn, order) == (
        datetime(2026, 10, 5, 11, 0, 2, 123000, tzinfo=UTC),
        datetime(2026, 10, 5, 12, 0, 1, 123000, tzinfo=UTC),
        datetime(2026, 10, 5, 12, 0, 1, 123000, tzinfo=UTC),
    )

    # an aggregate saved TWICE in one transaction: the second save is the UPDATE path, and the
    # instance still holds microseconds (a loaded aggregate would already hold truncated ones)
    twice: Order = place_order(
        order_reference="ORD-000002", occurred_at=placed_at, order_date=order_date
    )
    async with uow.begin() as tx:
        await tx.orders.save(twice)
        twice.mark_stock_reserved(occurred_at=datetime(2026, 10, 5, 12, 0, 6, 123987, tzinfo=UTC))
        await tx.orders.save(twice)
    assert await stored_header(migrated_db.dsn, twice) == (
        datetime(2026, 10, 5, 11, 0, 2, 123000, tzinfo=UTC),
        datetime(2026, 10, 5, 12, 0, 1, 123000, tzinfo=UTC),
        datetime(2026, 10, 5, 12, 0, 6, 123000, tzinfo=UTC),
    )

    changed_at = datetime(2026, 10, 5, 12, 0, 3, 123987, tzinfo=UTC)
    async with uow.begin() as tx:
        loaded = await tx.orders.get_by_id(order.id)
        assert loaded is not None
        loaded.add_line(
            product_code="SKU-C",
            description="Gamma crate",
            quantity=Quantity(5),
            unit_price=Money(777, "EUR"),
            line_discount=Money(33, "EUR"),
            occurred_at=changed_at,
        )
        await tx.orders.save(loaded)
    changed_again = datetime(2026, 10, 5, 12, 0, 4, 123987, tzinfo=UTC)
    async with uow.begin() as tx:
        loaded = await tx.orders.get_by_id(order.id)
        assert loaded is not None
        first = loaded.lines[0]
        loaded.change_line(
            line_id=first.id,
            quantity=Quantity(4),
            unit_price=first.unit_price,
            line_discount=first.line_discount,
            occurred_at=changed_again,
        )
        await tx.orders.save(loaded)

    assert (await stored_header(migrated_db.dsn, order))[2] == datetime(
        2026, 10, 5, 12, 0, 4, 123000, tzinfo=UTC
    )
    conn = await asyncpg.connect(migrated_db.dsn)
    try:
        items = await conn.fetch(
            "SELECT created_at, updated_at FROM order_items WHERE order_id = $1", order.id.value
        )
    finally:
        await conn.close()
    stamps = sorted((row["created_at"], row["updated_at"]) for row in items)
    assert len(stamps) == 3
    created = {created for created, _ in stamps}
    updated = {updated for _, updated in stamps}
    assert created == {
        datetime(2026, 10, 5, 12, 0, 1, 123000, tzinfo=UTC),  # the two placed lines
        datetime(2026, 10, 5, 12, 0, 3, 123000, tzinfo=UTC),  # the line added on the update path
    }
    assert datetime(2026, 10, 5, 12, 0, 4, 123000, tzinfo=UTC) in updated, "the changed line"


async def test_oi1_every_column_and_envelope_field_comes_from_its_own_event_field(
    sessions: async_sessionmaker[AsyncSession], place_order: Any, clock: SystemClock
) -> None:
    """The aggregate mints `aggregate_id == correlation_id` (R12), so no real order can tell the two
    columns apart. This event is hand-built with FIVE distinct ids, and the row's own `id` is a
    sixth: each stored column and each envelope field must be its own event field's value."""
    base = only_event(confirmed_order(place_order))
    event = dataclasses.replace(
        base,
        event_id=UniqueId.new(),
        aggregate_id=UniqueId.new(),
        correlation_id=UniqueId.new(),
        causation_id=UniqueId.new(),
    )
    async with sessions() as session, session.begin():
        await OutboxWriter(clock=clock).write(session, [event])
    (row,) = await stored_rows(sessions)

    assert row.event_id == event.event_id.value
    assert row.aggregate_id == event.aggregate_id.value
    assert row.correlation_id == event.correlation_id.value
    assert row.causation_id == event.causation_id.value
    assert row.id not in {
        event.event_id.value,
        event.aggregate_id.value,
        event.correlation_id.value,
        event.causation_id.value,
    }, "a row is a publication record: its id is its own, not any of the event's"
    fact = to_publishable_fact(row)
    envelope = json.loads(fact.value)
    assert envelope["eventId"] == str(event.event_id)
    assert envelope["aggregateId"] == str(event.aggregate_id)
    assert envelope["correlationId"] == str(event.correlation_id)
    assert envelope["causationId"] == str(event.causation_id)
    assert fact.key == str(event.correlation_id).encode("utf-8"), "keyed by the correlation id"
    assert fact.event_id == event.event_id.value
