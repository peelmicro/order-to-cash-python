# ruff: noqa: E501 - test names are the sentences the acceptance items and the spec use
"""Feature 41 end to end: `orders.cancel` against the REAL host, real NATS, real Kafka, real PostgreSQL.

The saga's other side is stood in by real NATS responders (`saga_harness`'s six stand-ins), which
RECORD every request in arrival order and, with `emit=True`, publish the fact a real responder
would. Every claim about what Orders asked is read from what a responder RECEIVED, never from our
own table alone (#8 D1: the `stock.release` reason is asserted on the observed request).

The wrong orders a fixture must differ from (SA-4, `saga.md` 4.3): credit first then stock (what
"reverse order of acquisition" would suggest), credit only, stock only. The expected arrival list
`[stock.release(order_cancelled), credit.release]` equals none of them.
"""

import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from otc_contracts.generated.asyncapi import Reason1
from otc_orders.application.saga.command_kind import SagaCommandKind
from otc_orders.domain.order import Order
from otc_orders.domain.value_objects.cancellation_reason import CancellationReason
from otc_orders.domain.value_objects.order_status import OrderStatus

Waits = Callable[..., Awaitable[None]]
OrderAt = Callable[..., Awaitable[Order]]

NOTE = "$set: the pallet is gone — café"  # begins with `$` (PR47), non-ASCII raw


async def ask_cancel(
    client: Any, order_id: uuid.UUID, *, note: str | None = NOTE, **overrides: Any
) -> dict[str, Any]:
    body: dict[str, Any] = {"orderId": str(order_id), "reason": "operator_cancelled"}
    if note is not None:
        body["note"] = note
    body |= overrides
    reply = await client.request(
        "orders.cancel",
        json.dumps(body, ensure_ascii=False).encode("utf-8"),
        timeout=10,
        headers={"x-correlation-id": str(order_id), "x-request-id": str(uuid.uuid4())},
    )
    answer: dict[str, Any] = json.loads(reply.data)
    return answer


async def cancelled_payload(saga: Any, order: Order) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(
        await saga.db.fetchval(
            "SELECT payload::text FROM outbox WHERE aggregate_id = $1 "
            "AND event_type = 'order.cancelled.v1'",
            order.id.value,
        )
    )
    return payload


def arrivals_for(saga: Any, order: Order) -> list[tuple[SagaCommandKind, str | None]]:
    stand_in = saga.stand_in(SagaCommandKind.STOCK_RELEASE)
    return [(a.kind, a.reason) for a in stand_in.arrivals if a.order_id == order.id.value]


async def cancelled(saga: Any, order: Order, waits: Waits) -> None:
    async def done() -> bool:
        return "order.cancelled.v1" in await saga.db.outbox_types(order.id)

    await waits(done, "an order.cancelled.v1 outbox row exists")


@pytest.mark.parametrize("status", [OrderStatus.CREDIT_APPROVED, OrderStatus.CONFIRMED])
async def test_sa4_from_credit_approved_and_confirmed_the_requests_received_are_stock_release_then_credit_release_and_the_credit_fact_cancels(
    status: OrderStatus, saga_harness: Any, order_at: OrderAt, waits: Waits, nats_client: Any
) -> None:
    order = await order_at(status)
    async with saga_harness() as saga:
        stock = saga.stand_in(SagaCommandKind.STOCK_RELEASE)
        credit = saga.stand_in(SagaCommandKind.CREDIT_RELEASE)
        stock.emit = credit.emit = True

        reply = await ask_cancel(nats_client, order.id.value)

        assert reply == {
            "orderId": str(order.id.value),
            "orderReference": order.order_reference.value,
            "status": status.value,
            "compensationPlanned": ["stock_release", "credit_release"],
        }
        await cancelled(saga, order, waits)

        assert arrivals_for(saga, order) == [
            (SagaCommandKind.STOCK_RELEASE, "order_cancelled"),
            (SagaCommandKind.CREDIT_RELEASE, None),
        ], (
            "stock first (the contested resource), then credit; the release reason is the observed one"
        )
        assert saga.stand_in(SagaCommandKind.DESPATCH_CREATE).requests == [], (
            "the cancel issues no despatch"
        )
        [stock_released] = stock.emitted
        [credit_released] = credit.emitted
        credit_row = await saga.db.command_row(order.id, SagaCommandKind.CREDIT_RELEASE)
        assert credit_row is not None
        assert credit_row["triggering_event_id"] == stock_released, (
            "credit.release is owed by the stock.released.v1 fact, not issued at cancel time"
        )
        assert await saga.db.status_of(order.id) == "cancelled"
        payload = await cancelled_payload(saga, order)
        assert payload["cancellationReason"] == "operator_cancelled"
        assert payload["note"] == NOTE
        stock_step, credit_step = payload["compensationSteps"]
        assert stock_step["step"] == "stock_released"
        assert stock_step["eventType"] == "stock.released.v1"
        assert "eventId" not in stock_step, "synthesised: no state survives from the earlier fact"
        assert credit_step["step"] == "credit_released"
        assert credit_step["eventId"] == str(credit_released)
        assert credit_step["eventType"] == "credit.released.v1"
        causation = await saga.db.fetchval(
            "SELECT causation_id FROM outbox WHERE aggregate_id = $1 "
            "AND event_type = 'order.cancelled.v1'",
            order.id.value,
        )
        assert causation == credit_released, "R12: the cancel is caused by the credit release fact"


async def test_sa4_from_stock_reserved_one_release_cancels_on_the_stock_fact_and_no_credit_is_released(
    saga_harness: Any, order_at: OrderAt, waits: Waits, nats_client: Any
) -> None:
    order = await order_at(OrderStatus.STOCK_RESERVED)
    async with saga_harness() as saga:
        stock = saga.stand_in(SagaCommandKind.STOCK_RELEASE)
        stock.emit = True

        reply = await ask_cancel(nats_client, order.id.value)

        assert reply["compensationPlanned"] == ["stock_release"]
        assert reply["status"] == "stock_reserved"
        assert "cancellationReason" not in reply
        await cancelled(saga, order, waits)

        [recorded] = stock.requests_for(order.id.value)
        assert recorded.request == {
            "orderReference": order.order_reference.value,
            "reason": "order_cancelled",
        }, "the observed stock.release carries the operator's reason, and no note"
        assert saga.stand_in(SagaCommandKind.CREDIT_RELEASE).requests == [], "no credit was held"
        payload = await cancelled_payload(saga, order)
        assert payload["cancellationReason"] == "operator_cancelled"
        assert payload["note"] == NOTE
        [step] = payload["compensationSteps"]
        assert step["step"] == "stock_released"
        assert step["eventId"] == str(stock.emitted[0]), "built from the OBSERVED release fact"
        assert [r["command"] for r in await saga.db.command_rows(order.id)] == ["stock.release"]


async def test_a_placed_order_is_cancelled_at_once_with_the_note_and_no_compensation(
    saga_harness: Any, order_at: OrderAt, nats_client: Any
) -> None:
    order = await order_at(OrderStatus.PLACED)
    async with saga_harness() as saga:
        reply = await ask_cancel(nats_client, order.id.value)

        assert reply == {
            "orderId": str(order.id.value),
            "orderReference": order.order_reference.value,
            "status": "cancelled",
            "cancellationReason": "operator_cancelled",
            "compensationPlanned": [],
        }
        assert await saga.db.status_of(order.id) == "cancelled"
        assert await saga.db.command_rows(order.id) == [], (
            "nothing was acquired: nothing to release"
        )
        payload = await cancelled_payload(saga, order)
        assert payload["note"] == NOTE
        assert payload["compensationSteps"] == []
        assert payload["cancellationReason"] == "operator_cancelled"
        assert all(not s.requests for s in saga.stand_ins.values())


async def test_without_a_note_the_cancelled_fact_carries_no_note_key_on_every_branch(
    saga_harness: Any, order_at: OrderAt, waits: Waits, nats_client: Any
) -> None:
    placed = await order_at(OrderStatus.PLACED)
    reserved = await order_at(OrderStatus.STOCK_RESERVED)
    async with saga_harness() as saga:
        saga.stand_in(SagaCommandKind.STOCK_RELEASE).emit = True
        await ask_cancel(nats_client, placed.id.value, note=None)
        await ask_cancel(nats_client, reserved.id.value, note=None)
        await cancelled(saga, placed, waits)
        await cancelled(saga, reserved, waits)

        assert "note" not in await cancelled_payload(saga, placed)
        assert "note" not in await cancelled_payload(saga, reserved)


def already_released(recorded: Any) -> bytes:
    """What `saga.md` 4.3 describes: nothing was released, the reply says so, no fact follows."""
    return json.dumps(
        {
            "outcome": "already_released",
            "orderReference": recorded.request["orderReference"],
            "released": [],
        }
    ).encode()


def precondition_failed(_recorded: Any) -> bytes:
    """What the REAL Fulfillment answered in the live walkthrough when the despatch consumed the
    reservation first (a `consumed` reservation cannot become `released`): a terminal refusal."""
    return json.dumps(
        {
            "code": "PRECONDITION_FAILED",
            "message": "A reservation that is 'consumed' cannot become 'released'.",
        }
    ).encode()


@pytest.mark.parametrize(
    ("answer", "row_status"),
    [(already_released, "sent"), (precondition_failed, "rejected")],
    ids=["already_released", "precondition_failed"],
)
async def test_the_despatch_wins_the_release_finds_nothing_so_no_credit_is_released_and_the_order_despatches(
    answer: Callable[[Any], bytes],
    row_status: str,
    saga_harness: Any,
    order_at: OrderAt,
    waits: Waits,
    nats_client: Any,
) -> None:
    order = await order_at(OrderStatus.CONFIRMED)
    async with saga_harness() as saga:
        stock = saga.stand_in(SagaCommandKind.STOCK_RELEASE)
        # either way no `stock.released.v1` follows (saga.md 4.3): nothing was released
        stock.behaviour = answer
        await ask_cancel(nats_client, order.id.value)

        async def release_resolved() -> bool:
            row = await saga.db.command_row(order.id, SagaCommandKind.STOCK_RELEASE)
            return row is not None and row["status"] == row_status

        await waits(release_resolved, f"the stock.release row reaches {row_status}")
        await saga.publish_fact(
            "order.despatched.v1",
            correlation_id=order.id.value,
            reference=order.order_reference.value,
        )

        async def despatched() -> bool:
            return bool(await saga.db.status_of(order.id) == "despatched")

        await waits(despatched, "order.despatched.v1 moves the confirmed order on")

        assert saga.stand_in(SagaCommandKind.CREDIT_RELEASE).requests == [], (
            "no credit.release: the hold still backs an order that is shipping"
        )
        assert "order.cancelled.v1" not in await saga.db.outbox_types(order.id), (
            "overtaken: no fact"
        )
        assert "order.saga_failed.v1" not in await saga.db.outbox_types(order.id)
        assert len(stock.requests_for(order.id.value)) == 1, "never retried"
        assert [r["command"] for r in await saga.db.command_rows(order.id)] == [
            "stock.release",
            "invoice.issue",
        ]


async def test_a_despatch_create_refused_precondition_failed_after_the_release_won_is_rejected_once_not_retried_not_parked_and_fails_no_saga(
    saga_harness: Any, order_at: OrderAt, waits: Waits
) -> None:
    order = await order_at(OrderStatus.STOCK_RESERVED)
    async with saga_harness() as saga:
        despatch = saga.stand_in(SagaCommandKind.DESPATCH_CREATE)
        despatch.behaviour = lambda _recorded: json.dumps(
            {"code": "PRECONDITION_FAILED", "message": "no reservation left to consume"}
        ).encode()
        await saga.publish_fact(
            "credit.approved.v1",
            correlation_id=order.id.value,
            reference=order.order_reference.value,
        )

        async def rejected() -> bool:
            row = await saga.db.command_row(order.id, SagaCommandKind.DESPATCH_CREATE)
            return row is not None and row["status"] == "rejected"

        await waits(rejected, "the lost despatch.create row is resolved to rejected")

        row = await saga.db.command_row(order.id, SagaCommandKind.DESPATCH_CREATE)
        assert row is not None
        assert row["attempts"] == 1, "no retry"
        assert len(despatch.requests_for(order.id.value)) == 1
        assert "order.saga_failed.v1" not in await saga.db.outbox_types(order.id), (
            "not a saga failure"
        )
        assert await saga.db.status_of(order.id) == "confirmed"


async def test_a_second_cancel_of_an_order_being_released_adds_no_row_and_keeps_the_first_note(
    saga_harness: Any, order_at: OrderAt, waits: Waits, nats_client: Any
) -> None:
    order = await order_at(OrderStatus.STOCK_RESERVED)
    async with saga_harness() as saga:
        stock = saga.stand_in(SagaCommandKind.STOCK_RELEASE)
        stock.behaviour = saga.behaviours["silent"]  # the order stays stock_reserved
        first = await ask_cancel(nats_client, order.id.value, note="first note")
        second = await ask_cancel(nats_client, order.id.value, note="second note")

        assert first == second, "a repeated cancel is answered the same way"
        [row] = await saga.db.command_rows(order.id)
        assert row["command"] == "stock.release"
        assert row["operator_note"] == "first note"
        stock.behaviour = lambda recorded: json.dumps(
            {"outcome": "released", "orderReference": recorded.request["orderReference"]}
        ).encode()
        stock.emit = True
        # the dispatcher re-issues the parked row; the fact then completes the cancellation

        await cancelled(saga, order, waits)
        assert (await cancelled_payload(saga, order))["note"] == "first note"


async def test_the_operator_cancel_of_an_order_whose_credit_rejection_release_is_already_owed_adds_no_row_and_no_note_leaks(
    saga_harness: Any, order_at: OrderAt, waits: Waits, nats_client: Any
) -> None:
    order = await order_at(OrderStatus.STOCK_RESERVED)
    async with saga_harness() as saga:
        stock = saga.stand_in(SagaCommandKind.STOCK_RELEASE)
        stock.behaviour = saga.behaviours["silent"]
        await saga.publish_fact(
            "credit.rejected.v1",
            correlation_id=order.id.value,
            reference=order.order_reference.value,
        )

        async def release_owed() -> bool:
            return await saga.db.command_row(order.id, SagaCommandKind.STOCK_RELEASE) is not None

        await waits(release_owed, "the credit rejection owes stock.release")

        reply = await ask_cancel(nats_client, order.id.value, note="too late to matter")

        assert reply["compensationPlanned"] == ["stock_release"]
        [row] = await saga.db.command_rows(order.id)
        assert json.loads(row["payload"])["reason"] == "credit_rejected", (
            "the saga's own release stands"
        )
        assert row["operator_note"] is None, "the note was not stored beside another command's row"
        stock.behaviour = lambda recorded: json.dumps(
            {"outcome": "released", "orderReference": recorded.request["orderReference"]}
        ).encode()
        stock.emit = True
        await cancelled(saga, order, waits)
        payload = await cancelled_payload(saga, order)
        assert payload["cancellationReason"] == "credit_rejected"
        assert "note" not in payload


@pytest.mark.parametrize(
    "reason", [CancellationReason.CREDIT_REJECTED, CancellationReason.STOCK_REJECTED]
)
async def test_a_saga_decided_cancellation_never_carries_an_operator_note(
    reason: CancellationReason, saga_harness: Any, order_at: OrderAt, waits: Waits
) -> None:
    order = await order_at(
        OrderStatus.PLACED
        if reason is CancellationReason.STOCK_REJECTED
        else OrderStatus.STOCK_RESERVED
    )
    async with saga_harness() as saga:
        if reason is CancellationReason.STOCK_REJECTED:
            await saga.publish_fact(
                "stock.rejected.v1",
                correlation_id=order.id.value,
                reference=order.order_reference.value,
            )
        else:
            await saga.publish_fact(
                "stock.released.v1",
                correlation_id=order.id.value,
                reference=order.order_reference.value,
            )
        await cancelled(saga, order, waits)
        payload = await cancelled_payload(saga, order)
        assert payload["cancellationReason"] == reason.value
        assert "note" not in payload


async def test_the_operators_stock_release_is_issued_by_the_fast_path_alone_with_the_sweeper_disabled(
    saga_harness: Any, order_at: OrderAt, waits: Waits, nats_client: Any
) -> None:
    """The durable `pending` row would be issued by the sweeper anyway; with the sweeper off, only
    the post-commit signal (`OperatorCancelAccepted` -> the fast path) can issue it."""
    order = await order_at(OrderStatus.STOCK_RESERVED)
    async with saga_harness(SAGA_SWEEPER_ENABLED="false") as saga:
        await ask_cancel(nats_client, order.id.value)

        async def sent() -> bool:
            row = await saga.db.command_row(order.id, SagaCommandKind.STOCK_RELEASE)
            return row is not None and row["status"] == "sent"

        await waits(sent, "the fast path alone issues the stock.release row")


async def test_credit_release_after_the_stock_fact_is_issued_by_the_fast_path_alone_with_the_sweeper_disabled(
    saga_harness: Any, order_at: OrderAt, waits: Waits
) -> None:
    order = await order_at(OrderStatus.CONFIRMED)
    async with saga_harness(SAGA_SWEEPER_ENABLED="false") as saga:
        await saga.publish_fact(
            "stock.released.v1",
            correlation_id=order.id.value,
            reference=order.order_reference.value,
            release_reason=Reason1.order_cancelled,
        )

        async def sent() -> bool:
            row = await saga.db.command_row(order.id, SagaCommandKind.CREDIT_RELEASE)
            return row is not None and row["status"] == "sent"

        await waits(sent, "the fast path alone issues the credit.release row")
