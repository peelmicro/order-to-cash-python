# ruff: noqa: E501 - test names are the literal names `tasks.md` and the matrix assign
"""Preconditions, redelivery and unknown orders (R25, R18, SO8, SO12; `design.md` 7.6).

R25 is swept over the ten consumed facts, each published with a NEW event id (so the dedup layer is
bypassed on purpose and layer 2, the state-machine precondition, is what is tested) against an order
planted at the status `saga.md` 6's table names. The statuses are LITERALS transcribed from that
table, never read from the code. Each case waits for the `saga_ignored_facts` row it expects, then
asserts with the very same predicate.
"""

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from otc_orders.application.saga.command_kind import SagaCommandKind
from otc_orders.domain.order import Order
from otc_orders.domain.value_objects.order_status import OrderStatus

Waits = Callable[..., Awaitable[None]]
OrderAt = Callable[..., Awaitable[Order]]

# fact -> (the status the order is in when the fact is redelivered, the fact's precondition):
# `saga.md` 6, "Per-fact redelivery behaviour".
REDELIVERY: dict[str, tuple[OrderStatus, str]] = {
    "order.placed.v1": (OrderStatus.STOCK_RESERVED, "placed"),
    "stock.reserved.v1": (OrderStatus.STOCK_RESERVED, "placed"),
    "credit.approved.v1": (OrderStatus.CONFIRMED, "stock_reserved"),
    "order.despatched.v1": (OrderStatus.DESPATCHED, "confirmed"),
    "invoice.issued.v1": (OrderStatus.INVOICED, "despatched"),
    "payment.received.v1": (OrderStatus.PAID, "invoiced"),
    "credit.released.v1": (OrderStatus.COMPLETED, "paid"),
    "stock.rejected.v1": (OrderStatus.CANCELLED, "placed"),
    "credit.rejected.v1": (OrderStatus.CANCELLED, "stock_reserved"),
    "stock.released.v1": (OrderStatus.CANCELLED, "stock_reserved"),
}


@pytest.mark.parametrize("event_type", sorted(REDELIVERY))
async def test_r25_ignores_a_fact_whose_precondition_status_is_unmet_and_records_the_observed_and_expected_status(
    event_type: str, saga_harness: Any, order_at: OrderAt, waits: Waits
) -> None:
    observed, expected = REDELIVERY[event_type]
    order = await order_at(observed)
    async with saga_harness() as saga:
        fact_id = await saga.publish_fact(
            event_type, correlation_id=order.id.value, reference="ORD-000101"
        )

        async def recorded() -> bool:
            return any(
                row["event_id"] == fact_id and row["marker"] == "precondition_unmet"
                for row in await saga.db.ignored(order.id, event_type)
            )

        await waits(recorded, f"one precondition_unmet row for {event_type}")

        rows = [r for r in await saga.db.ignored(order.id, event_type) if r["event_id"] == fact_id]
        [row] = rows
        assert (row["observed_status"], row["expected_status"]) == (observed.value, expected)
        assert row["order_id"] == order.id.value
        assert await saga.db.status_of(order.id) == observed.value, "no status change"
        assert await saga.db.command_rows(order.id) == [], "no command is owed"
        assert await saga.db.outbox_types(order.id) == [], "no fact is emitted"
        assert all(not stand_in.requests for stand_in in saga.stand_ins.values())


async def test_r18_the_same_event_id_redelivered_is_absorbed_by_the_dedup_layer_with_no_ignored_record(
    saga_harness: Any, order_at: OrderAt, waits: Waits
) -> None:
    order = await order_at(OrderStatus.PLACED)
    async with saga_harness() as saga:
        first = await saga.publish_fact(
            "stock.reserved.v1", correlation_id=order.id.value, reference="ORD-000101"
        )

        async def hold_sent() -> bool:
            row = await saga.db.command_row(order.id, SagaCommandKind.CREDIT_HOLD)
            return row is not None and row["status"] == "sent"

        await waits(hold_sent, "the first delivery's credit.hold is sent")

        # the SAME event id again (a relay republish), then a later marker fact: once the marker is
        # recorded the redelivery has been consumed (same key, same partition, in order)
        await saga.publish_fact(
            "stock.reserved.v1",
            correlation_id=order.id.value,
            reference="ORD-000101",
            event_id=first,
        )
        marker = await saga.publish_fact(
            "order.despatched.v1", correlation_id=order.id.value, reference="ORD-000101"
        )

        async def marker_recorded() -> bool:
            return any(
                row["event_id"] == marker
                for row in await saga.db.ignored(order.id, "order.despatched.v1")
            )

        await waits(marker_recorded, "the later marker fact is consumed")

        assert [r for r in await saga.db.ignored(order.id) if r["event_id"] == first] == [], (
            "layer 1 absorbs a redelivery: nothing is recorded as ignored"
        )
        assert (
            await saga.db.fetchval(
                "SELECT count(*) FROM processed_events WHERE event_id = $1", first
            )
            == 1
        )
        assert len(saga.stand_in(SagaCommandKind.CREDIT_HOLD).requests_for(order.id.value)) == 1
        assert await saga.db.status_of(order.id) == "stock_reserved"


async def test_credit_rejected_redelivered_with_a_new_event_id_mid_compensation_owes_one_stock_release_and_commits_its_offset(
    saga_harness: Any, broker: Any, order_at: OrderAt, waits: Waits
) -> None:
    order = await order_at(OrderStatus.STOCK_RESERVED)
    async with saga_harness() as saga:
        first = await saga.publish_fact(
            "credit.rejected.v1", correlation_id=order.id.value, reference="ORD-000101"
        )

        async def release_sent() -> bool:
            row = await saga.db.command_row(order.id, SagaCommandKind.STOCK_RELEASE)
            return row is not None and row["status"] == "sent"

        await waits(release_sent, "the first credit.rejected.v1 owes and sends a stock.release")

        # compensation is in flight (no stock.released.v1 yet): the order is still stock_reserved,
        # so a SECOND credit.rejected.v1 with a new event id MEETS its precondition. It must owe
        # nothing new, poison nothing, and have its offset committed (#7 D1).
        second = await saga.publish_fact(
            "credit.rejected.v1", correlation_id=order.id.value, reference="ORD-000101"
        )

        async def second_processed() -> bool:
            return bool(await saga.db.processed(second))

        await waits(second_processed, "the second credit.rejected.v1 is processed")

        topic, partition, offset = saga.positions[second]

        async def offset_passed_the_fact() -> bool:
            return bool((await broker.committed()).get((topic, partition), -1) >= offset + 1)

        await waits(offset_passed_the_fact, "the group's committed offset passes the second fact")

        # The second fact's fast-path signal fires AFTER its transaction commits. A re-dispatch of the
        # already-`sent` row would reach the stand-in within milliseconds (a loopback request); the
        # window below is 25x that, and a non-claimable `sent` row (SO11) makes it a no-op.
        await asyncio.sleep(0.5)
        release_requests = saga.stand_in(SagaCommandKind.STOCK_RELEASE).requests_for(order.id.value)
        assert len(release_requests) == 1, (
            f"exactly one fulfillment.stock.release request, got {len(release_requests)}: "
            "the sent row must not be re-dispatched by the second credit.rejected.v1"
        )
        assert first != second
        assert [row["command"] for row in await saga.db.command_rows(order.id)] == ["stock.release"]
        assert await saga.db.status_of(order.id) == "stock_reserved"
        assert await saga.db.ignored(order.id) == [], "a met precondition is not an ignored fact"


async def test_so8_a_fact_whose_correlation_id_matches_no_order_is_recorded_unknown_order_and_acknowledged_without_throwing(
    saga_harness: Any,
    broker: Any,
    waits: Waits,
    caplog: pytest.LogCaptureFixture,
) -> None:
    unknown = uuid.uuid4()
    with caplog.at_level(logging.WARNING):
        async with saga_harness() as saga:
            fact_id = await saga.publish_fact(
                "stock.reserved.v1", correlation_id=unknown, reference="ORD-000000"
            )

            async def recorded() -> bool:
                return any(
                    r["event_id"] == fact_id and r["marker"] == "unknown_order"
                    for r in await saga.db.ignored(unknown, "stock.reserved.v1")
                )

            await waits(recorded, "exactly one unknown_order row for the fact")
            topic, partition, offset = saga.positions[fact_id]

            async def acknowledged() -> bool:
                return bool((await broker.committed()).get((topic, partition), -1) >= offset + 1)

            await waits(acknowledged, "the offset is committed past the unknown-order fact")

            [row] = [r for r in await saga.db.ignored(unknown) if r["event_id"] == fact_id]
            assert row["marker"] == "unknown_order"
            assert row["order_id"] is None
            assert row["observed_status"] is None
            assert row["expected_status"] == "placed"
            assert await saga.db.command_rows(unknown) == []
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors == [], f"an unknown order must not be logged at ERROR: {errors}"


async def test_so12_a_fact_carrying_order_reference_ord_000000_is_routed_by_correlation_id_and_never_refused_by_the_reference_parse(
    saga_harness: Any, order_at: OrderAt, waits: Waits
) -> None:
    order = await order_at(OrderStatus.PLACED, reference="ORD-000101")
    async with saga_harness() as saga:
        # the wire pattern ^ORD-[0-9]{6,}$ admits ORD-000000; the kernel's canonical parse refuses it
        await saga.publish_fact(
            "stock.reserved.v1", correlation_id=order.id.value, reference="ORD-000000"
        )

        async def hold_sent() -> bool:
            row = await saga.db.command_row(order.id, SagaCommandKind.CREDIT_HOLD)
            return row is not None and row["status"] == "sent"

        await waits(hold_sent, "the credit.hold row reaches sent")

        assert await saga.db.status_of(order.id) == "stock_reserved"
        [recorded] = saga.stand_in(SagaCommandKind.CREDIT_HOLD).requests_for(order.id.value)
        assert recorded.request["orderReference"] == "ORD-000101", (
            "the command carries the aggregate's own reference, never the fact's"
        )
        assert await saga.db.ignored(order.id) == []
