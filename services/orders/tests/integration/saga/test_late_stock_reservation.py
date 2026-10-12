# ruff: noqa: E501 - test names are the sentences the acceptance items and the spec use
"""A `stock.reserved.v1` that arrives after the operator's cancellation (`saga.md` 4.3, "A stock
reservation that arrives after the cancellation"; SA-8; backlog 216).

An order cancelled while `placed` acquired nothing *yet*, but `stock.reserve` was already owed and
may already be at Fulfillment. The reservation, once made, is unwound: `stock.release` (reason
`order_cancelled`) and NOTHING else: no transition, no `credit.hold`. The cancellations the saga
decided itself (`stock_rejected`, `credit_rejected`) must NOT be treated as one.
"""

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from otc_orders.application.saga.command_kind import SagaCommandKind
from otc_orders.domain.order import Order
from otc_orders.domain.value_objects.cancellation_reason import CancellationReason
from otc_orders.domain.value_objects.order_status import OrderStatus

Waits = Callable[..., Awaitable[None]]
OrderAt = Callable[..., Awaitable[Order]]


async def release_sent(saga: Any, order: Order, waits: Waits) -> None:
    async def sent() -> bool:
        row = await saga.db.command_row(order.id, SagaCommandKind.STOCK_RELEASE)
        return row is not None and row["status"] == "sent"

    await waits(sent, "the stock.release row reaches sent")


async def ignored_as_unmet(
    saga: Any, order: Order, event_type: str, fact_id: uuid.UUID, waits: Waits
) -> None:
    async def recorded() -> bool:
        return any(
            row["event_id"] == fact_id and row["marker"] == "precondition_unmet"
            for row in await saga.db.ignored(order.id, event_type)
        )

    await waits(recorded, f"{event_type} is recorded as a precondition_unmet fact")


async def test_an_operator_cancel_at_placed_then_the_late_reservation_issues_stock_release_and_nothing_else(
    saga_harness: Any, order_at: OrderAt, waits: Waits, nats_client: Any
) -> None:
    """Acceptance 2: the reviewer's scenario end to end (real host, NATS, Kafka, PostgreSQL)."""
    order = await order_at(OrderStatus.PLACED)
    async with saga_harness() as saga:
        reserve = saga.stand_in(SagaCommandKind.STOCK_RESERVE)
        reserve.behaviour = saga.behaviours["silent"]  # Fulfillment held: no reply
        release = saga.stand_in(SagaCommandKind.STOCK_RELEASE)
        release.emit = True  # the real responder publishes stock.released.v1 after releasing
        await saga.publish_fact(
            "order.placed.v1", correlation_id=order.id.value, reference=order.order_reference.value
        )

        async def reserve_asked() -> bool:
            return len(reserve.requests_for(order.id.value)) >= 1

        await waits(reserve_asked, "stock.reserve was sent to the (held) Fulfillment")
        reply = await nats_client.request(
            "orders.cancel",
            json.dumps(
                {"orderId": str(order.id.value), "reason": "operator_cancelled", "note": "n"}
            ).encode(),
            timeout=10,
            headers={"x-correlation-id": str(order.id.value), "x-request-id": str(uuid.uuid4())},
        )
        assert json.loads(reply.data)["status"] == "cancelled"
        assert release.requests_for(order.id.value) == [], "an immediate cancel owes no release"

        # Fulfillment comes back: the (still dispatched) stock.reserve is accepted and the
        # reservation is made
        reserve.behaviour = saga.behaviours["accept_stock_reserve"]
        reserve.emit = True

        async def release_requested() -> bool:
            return len(release.requests_for(order.id.value)) >= 1

        await waits(release_requested, "the late reservation owes stock.release", seconds=30)
        await release_sent(saga, order, waits)
        assert len(reserve.emitted) >= 1, "Fulfillment reserved and said so"

        async def released_fact_ignored() -> bool:
            return len(await saga.db.ignored(order.id, "stock.released.v1")) == 1

        await waits(released_fact_ignored, "stock.released.v1 reaches the cancelled order, ignored")
        await asyncio.sleep(1)  # let anything further surface before asserting absence

        [request] = release.requests_for(order.id.value)
        assert request.request["reason"] == "order_cancelled"
        assert request.request["orderReference"] == order.order_reference.value
        assert await saga.db.status_of(order.id) == "cancelled", "no transition"
        assert await saga.db.command_row(order.id, SagaCommandKind.CREDIT_HOLD) is None
        assert [r["command"] for r in await saga.db.command_rows(order.id)] == [
            "stock.reserve",
            "stock.release",
        ]
        assert saga.stand_in(SagaCommandKind.CREDIT_HOLD).requests == []
        assert await saga.db.outbox_types(order.id) == ["order.cancelled.v1"]


async def test_the_late_reservation_release_carries_the_aggregates_reference_the_reason_and_no_note(
    saga_harness: Any, order_at: OrderAt, waits: Waits
) -> None:
    order = await order_at(OrderStatus.CANCELLED, reason=CancellationReason.OPERATOR_CANCELLED)
    other = await order_at(OrderStatus.CANCELLED, reason=CancellationReason.OPERATOR_CANCELLED)
    async with saga_harness() as saga:
        await saga.publish_fact(
            "stock.reserved.v1",
            correlation_id=order.id.value,
            reference=other.order_reference.value,  # the fact's reference is a decoy (SO12)
        )
        await release_sent(saga, order, waits)

        [request] = saga.stand_in(SagaCommandKind.STOCK_RELEASE).requests_for(order.id.value)
        assert request.request == {
            "orderReference": order.order_reference.value,
            "reason": "order_cancelled",
        }, "the wire payload declares no note, so none is sent"
        row = await saga.db.command_row(order.id, SagaCommandKind.STOCK_RELEASE)
        assert row is not None
        assert row["operator_note"] is None
        assert await saga.db.status_of(order.id) == "cancelled"
        assert await saga.db.outbox_types(order.id) == []
        assert await saga.db.command_row(order.id, SagaCommandKind.CREDIT_HOLD) is None
        assert await saga.db.command_rows(other.id) == [], "no other order is touched"


async def test_a_redelivered_late_reservation_adds_no_second_release_row_and_sends_no_second_request(
    saga_harness: Any, order_at: OrderAt, waits: Waits
) -> None:
    order = await order_at(OrderStatus.CANCELLED, reason=CancellationReason.OPERATOR_CANCELLED)
    async with saga_harness() as saga:
        stock = saga.stand_in(SagaCommandKind.STOCK_RELEASE)
        fact_id = await saga.publish_fact(
            "stock.reserved.v1",
            correlation_id=order.id.value,
            reference=order.order_reference.value,
        )
        await release_sent(saga, order, waits)
        rows_before = [r["id"] for r in await saga.db.command_rows(order.id)]
        requests_before = len(stock.requests_for(order.id.value))
        assert len(rows_before) == 1, "the baseline is one row, not zero"
        assert requests_before == 1, "the baseline is one request, not zero"

        # the same event id again (a redelivery), then a NEW event for the same reservation (the
        # saga.md 6 case where the dedup record is missing): the (order, command) ledger holds
        await saga.publish_fact(
            "stock.reserved.v1",
            correlation_id=order.id.value,
            reference=order.order_reference.value,
            event_id=fact_id,
        )
        marker = await saga.publish_fact(
            "stock.reserved.v1",
            correlation_id=order.id.value,
            reference=order.order_reference.value,
        )

        async def second_processed() -> bool:
            return bool(await saga.db.processed(marker))

        await waits(second_processed, "the second stock.reserved.v1 was consumed")
        await asyncio.sleep(1)
        assert [r["id"] for r in await saga.db.command_rows(order.id)] == rows_before
        assert len(stock.requests_for(order.id.value)) == requests_before


@pytest.mark.parametrize(
    "reason", [CancellationReason.CREDIT_REJECTED, CancellationReason.STOCK_REJECTED]
)
async def test_a_late_reservation_for_a_cancellation_the_saga_decided_is_ignored_and_releases_nothing(
    reason: CancellationReason, saga_harness: Any, order_at: OrderAt, waits: Waits
) -> None:
    order = await order_at(OrderStatus.CANCELLED, reason=reason)
    async with saga_harness() as saga:
        fact_id = await saga.publish_fact(
            "stock.reserved.v1",
            correlation_id=order.id.value,
            reference=order.order_reference.value,
        )
        await ignored_as_unmet(saga, order, "stock.reserved.v1", fact_id, waits)

        assert await saga.db.command_rows(order.id) == [], "no stock.release for this one"
        assert all(not s.requests for s in saga.stand_ins.values())
        assert await saga.db.outbox_types(order.id) == []


async def test_a_reservation_for_a_placed_order_still_advances_it_and_asks_for_the_credit_hold(
    saga_harness: Any, order_at: OrderAt, waits: Waits
) -> None:
    """The precondition's other side: the late branch must not capture the ordinary step."""
    order = await order_at(OrderStatus.PLACED)
    async with saga_harness() as saga:
        await saga.publish_fact(
            "stock.reserved.v1",
            correlation_id=order.id.value,
            reference=order.order_reference.value,
        )

        async def advanced() -> bool:
            return bool(await saga.db.status_of(order.id) == "stock_reserved")

        await waits(advanced, "the reservation moves the order to stock_reserved")
        assert await saga.db.command_row(order.id, SagaCommandKind.STOCK_RELEASE) is None
        assert await saga.db.command_row(order.id, SagaCommandKind.CREDIT_HOLD) is not None


NOTE = "$keep: café €"


async def cancel_by_operator(nats_client: Any, order: Order, note: str) -> dict[str, Any]:
    reply = await nats_client.request(
        "orders.cancel",
        json.dumps(
            {"orderId": str(order.id.value), "reason": "operator_cancelled", "note": note}
        ).encode(),
        timeout=10,
        headers={"x-correlation-id": str(order.id.value), "x-request-id": str(uuid.uuid4())},
    )
    answer: dict[str, Any] = json.loads(reply.data)
    return answer


async def test_a_reservation_at_stock_reserved_with_an_accepted_operator_cancel_is_still_ignored_as_out_of_order(
    saga_harness: Any, order_at: OrderAt, waits: Waits, nats_client: Any
) -> None:
    """The late branch's precondition is exactly `cancelled` with `operator_cancelled` (SA-8,
    `saga.md` 6: `stock.reserved.v1` at `stock_reserved or later` is ignored, recorded). The
    late-approval shape (`stock_reserved` plus an accepted cancel) must NOT capture it."""
    order = await order_at(OrderStatus.STOCK_RESERVED)
    async with saga_harness() as saga:
        release = saga.stand_in(SagaCommandKind.STOCK_RELEASE)
        release.behaviour = saga.behaviours["silent"]  # the cancellation stays under way
        assert (await cancel_by_operator(nats_client, order, NOTE))["status"] == "stock_reserved"
        original = await saga.db.command_row(order.id, SagaCommandKind.STOCK_RELEASE)
        assert original is not None
        rows_before = [r["id"] for r in await saga.db.command_rows(order.id)]

        fact_id = await saga.publish_fact(
            "stock.reserved.v1",
            correlation_id=order.id.value,
            reference=order.order_reference.value,
        )
        await ignored_as_unmet(saga, order, "stock.reserved.v1", fact_id, waits)
        await asyncio.sleep(1)

        [recorded] = [
            r
            for r in await saga.db.ignored(order.id, "stock.reserved.v1")
            if r["event_id"] == fact_id
        ]
        assert recorded["observed_status"] == "stock_reserved"
        assert recorded["expected_status"] == "placed"
        assert [r["id"] for r in await saga.db.command_rows(order.id)] == rows_before
        row = await saga.db.command_row(order.id, SagaCommandKind.STOCK_RELEASE)
        assert row is not None
        assert (row["id"], row["payload"], row["operator_note"]) == (
            original["id"],
            original["payload"],
            NOTE,
        )
        # (the held stand-in is retried by the dispatcher, so the request count is not a baseline)
        assert await saga.db.status_of(order.id) == "stock_reserved"


async def test_a_reservation_after_an_operator_cancel_from_stock_reserved_adds_no_second_release_and_keeps_the_note(
    saga_harness: Any, order_at: OrderAt, waits: Waits, nats_client: Any
) -> None:
    """The operator's cancel from `stock_reserved` already owes the one `stock.release` row, with
    the note. A (redelivered, new event id) `stock.reserved.v1` after the cancellation completed
    adds no row, sends no request, and leaves the note and `order.cancelled.v1` as they were."""
    order = await order_at(OrderStatus.STOCK_RESERVED)
    async with saga_harness() as saga:
        release = saga.stand_in(SagaCommandKind.STOCK_RELEASE)
        release.behaviour = saga.behaviours["silent"]
        assert (await cancel_by_operator(nats_client, order, NOTE))["status"] == "stock_reserved"

        release.behaviour = saga.behaviours["accept_stock_release"]
        release.emit = True  # the real responder publishes stock.released.v1, which cancels

        async def cancelled() -> bool:
            return bool(await saga.db.status_of(order.id) == "cancelled")

        await waits(cancelled, "stock.released.v1 completes the cancellation", seconds=30)
        await release_sent(saga, order, waits)
        await asyncio.sleep(1)
        original = await saga.db.command_row(order.id, SagaCommandKind.STOCK_RELEASE)
        assert original is not None
        assert original["operator_note"] == NOTE
        rows_before = [
            (r["id"], r["command"], r["payload"], r["operator_note"])
            for r in await saga.db.command_rows(order.id)
        ]
        requests_before = len(release.requests_for(order.id.value))
        assert [row[1] for row in rows_before].count("stock.release") == 1, "the baseline is one"
        assert requests_before >= 1

        marker = await saga.publish_fact(
            "stock.reserved.v1",
            correlation_id=order.id.value,
            reference=order.order_reference.value,
        )

        async def processed() -> bool:
            return bool(await saga.db.processed(marker))

        await waits(processed, "the late stock.reserved.v1 was consumed")
        await asyncio.sleep(1)

        assert [
            (r["id"], r["command"], r["payload"], r["operator_note"])
            for r in await saga.db.command_rows(order.id)
        ] == rows_before
        assert len(release.requests_for(order.id.value)) == requests_before
        outbox = await saga.db.fetch(
            "SELECT event_type, payload::text AS p FROM outbox WHERE aggregate_id=$1 ORDER BY seq",
            order.id.value,
        )
        assert [r["event_type"] for r in outbox] == ["order.cancelled.v1"]
        assert json.loads(outbox[0]["p"])["note"] == NOTE
