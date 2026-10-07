"""R15 against a real Kafka: facts about one order share a partition, in emission order.

The fixture precondition is ASSERTED: the two orders are chosen so that their keys land on DIFFERENT
partitions of the six-partition topic, so "one partition per order" cannot hold by accident (one
partition for everything would make every ordering claim vacuous). Records are selected by their
own event ids; "published" is read from the broker. Loop scope: default (function).
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from aiokafka.partitioner import DefaultPartitioner

from otc_orders.domain.order import Order
from otc_orders.infrastructure.outbox.payloads import narrow
from otc_orders.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from otc_shared_kernel import UniqueId

INSTANT = datetime(2026, 10, 5, 12, 0, 0, 123000, tzinfo=UTC)
PARTITIONS = 6


def last_event_id(order: Order) -> UUID:
    return narrow(order.domain_events[-1]).event_id.value


def partition_of(order: Order) -> int:
    key = str(order.id).encode("utf-8")
    chosen: int = DefaultPartitioner()(key, list(range(PARTITIONS)), list(range(PARTITIONS)))
    return chosen


async def test_r15_delivers_all_facts_produced_by_one_context_about_one_order_to_consumers_in_emission_order(  # noqa: E501
    uow: SqlAlchemyUnitOfWork,
    place_order: Any,
    make_relay: Any,
    kafka_publisher: Any,
    read_topic: Any,
) -> None:
    first: Order = place_order(order_reference="ORD-000021", occurred_at=INSTANT)
    second: Order = place_order(order_reference="ORD-000022", occurred_at=INSTANT)
    attempts = 0
    while partition_of(first) == partition_of(second):  # choose ids until the orders split
        second = place_order(order_reference="ORD-000022", occurred_at=INSTANT)
        attempts += 1
        assert attempts < 200, "no pair of order ids on different partitions was found"
    assert partition_of(first) != partition_of(second), (
        "precondition: both orders on one partition would make this test pass by accident"
    )

    # three facts each, written INTERLEAVED across three transactions
    emission: dict[UniqueId, list[UUID]] = {first.id: [], second.id: []}
    for order in (first, second):
        emission[order.id].append(last_event_id(order))
    async with uow.begin() as tx:
        await tx.orders.save(first)  # first: placed
        await tx.orders.save(second)  # second: placed
    for stage in ("confirm", "complete"):
        async with uow.begin() as tx:
            for order in (first, second):
                loaded = await tx.orders.get_by_id(order.id)
                assert loaded is not None
                if stage == "confirm":
                    loaded.mark_stock_reserved(occurred_at=INSTANT + timedelta(minutes=1))
                    loaded.approve_credit(occurred_at=INSTANT + timedelta(minutes=2))
                    loaded.confirm(
                        occurred_at=INSTANT + timedelta(minutes=3), causation_id=UniqueId.new()
                    )
                else:
                    loaded.mark_despatched(occurred_at=INSTANT + timedelta(minutes=4))
                    loaded.mark_invoiced(occurred_at=INSTANT + timedelta(minutes=5))
                    loaded.mark_paid(occurred_at=INSTANT + timedelta(minutes=6))
                    loaded.complete(
                        occurred_at=INSTANT + timedelta(minutes=7), causation_id=UniqueId.new()
                    )
                emission[order.id].append(last_event_id(loaded))
                await tx.orders.save(loaded)

    result = await make_relay(kafka_publisher).run_once()
    assert result.published == 6

    wanted = {event_id for ids in emission.values() for event_id in ids}
    records = [r for r in await read_topic() if r.event_id in wanted]
    assert len(records) == 6
    landed = {
        order.id: {r.partition for r in records if r.event_id in set(emission[order.id])}
        for order in (first, second)
    }
    assert landed[first.id] != landed[second.id], (
        "precondition (read from the broker): the two orders landed on ONE partition, so "
        f"'one partition per order' proves nothing: {landed}"
    )
    for order in (first, second):
        mine = [r for r in records if r.event_id in set(emission[order.id])]
        assert len(mine) == 3
        assert {r.partition for r in mine} == {partition_of(order)}, "one partition per order"
        assert [r.event_id for r in sorted(mine, key=lambda r: r.offset)] == emission[order.id], (
            "emission order"
        )
        assert all(r.key == str(order.id).encode("utf-8") for r in mine), "keyed by the order id"
