# ruff: noqa: E501 - test names are sentences naming the case
"""`CancelOrderCommandHandler` with fakes: the branches of `saga.md` 4.3's table, the order of the
effects, and the lock.

The fakes record the ORDER of the calls, so "loaded FOR UPDATE, never plain", "the release is
enqueued before the commit and signalled after it" and "a refusal writes and signals nothing" are
assertions, not hopes. The status cells are literals transcribed from the spec.
"""

import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from otc_orders.application.commands.cancel_order import (
    COMPENSATION_PLANS,
    CancelOrderCommand,
    CancelOrderCommandHandler,
    CancelOrderResult,
    CompensationPlanned,
    OrderNotFoundError,
)
from otc_orders.application.ports.saga_command_store import EnqueueOutcome, OwedCommand
from otc_orders.application.saga.command_kind import SagaCommandKind
from otc_orders.application.saga.dispatch_events import OperatorCancelAccepted
from otc_orders.application.scope import OrdersScope
from otc_orders.domain.errors import OrderNotCancellableError
from otc_orders.domain.order import Order
from otc_orders.domain.value_objects.cancellation_reason import CancellationReason
from otc_orders.domain.value_objects.order_status import OrderStatus
from otc_shared_kernel import UniqueId

NOW = datetime(2026, 10, 12, 8, 30, 15, 123000, tzinfo=UTC)
ORDER_ID = UniqueId(uuid.UUID("00000000-0000-4000-8000-0000000000d1"))


@dataclass
class Calls:
    log: list[str] = field(default_factory=list)
    enqueued: list[OwedCommand] = field(default_factory=list)
    saved: list[Order] = field(default_factory=list)
    published: list[Any] = field(default_factory=list)


class FakeOrders:
    def __init__(self, calls: Calls, order: Order | None) -> None:
        self._calls = calls
        self._order = order

    async def get_by_id(self, order_id: UniqueId) -> Order | None:
        raise AssertionError("an operator cancel must load the order FOR UPDATE (SO17)")

    async def get_by_id_for_update(self, order_id: UniqueId) -> Order | None:
        self._calls.log.append("load_for_update")
        return self._order

    async def save(self, order: Order) -> None:
        self._calls.log.append("save")
        self._calls.saved.append(order)


class FakeQueue:
    def __init__(self, calls: Calls) -> None:
        self._calls = calls

    async def enqueue(self, command: OwedCommand) -> EnqueueOutcome:
        self._calls.log.append("enqueue")
        self._calls.enqueued.append(command)
        return EnqueueOutcome.ENQUEUED


class FakeTransaction:
    def __init__(self, calls: Calls, order: Order | None) -> None:
        self.orders = FakeOrders(calls, order)
        self.saga_commands = FakeQueue(calls)


class FakeUnitOfWork:
    def __init__(self, calls: Calls, order: Order | None) -> None:
        self._calls = calls
        self._order = order

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[FakeTransaction]:
        self._calls.log.append("begin")
        try:
            yield FakeTransaction(self._calls, self._order)
        except BaseException:
            self._calls.log.append("rollback")
            raise
        self._calls.log.append("commit")


class FakeDispatcher:
    def __init__(self, calls: Calls) -> None:
        self._calls = calls

    async def publish(self, event: Any, scope: Any) -> None:
        self._calls.log.append("publish")
        self._calls.published.append(event)


class FixedClock:
    def now(self) -> datetime:
        return NOW


def handler_over(
    order: Order | None,
) -> tuple[CancelOrderCommandHandler, Calls]:
    calls = Calls()
    scope = OrdersScope(
        unit_of_work=cast("Any", FakeUnitOfWork(calls, order)),
        catalog=cast("Any", object()),
        stock=cast("Any", object()),
        clock=FixedClock(),
        dispatcher=cast("Any", FakeDispatcher(calls)),
    )
    return CancelOrderCommandHandler(scope), calls


CANCEL = CancelOrderCommand(order_id=ORDER_ID, note="$operator note — café")

# status -> (the plan the reply names, IN RELEASE ORDER), transcribed from saga.md 4.3's table
PLANS: dict[OrderStatus, tuple[CompensationPlanned, ...]] = {
    OrderStatus.STOCK_RESERVED: (CompensationPlanned.STOCK_RELEASE,),
    OrderStatus.CREDIT_APPROVED: (
        CompensationPlanned.STOCK_RELEASE,
        CompensationPlanned.CREDIT_RELEASE,
    ),
    OrderStatus.CONFIRMED: (CompensationPlanned.STOCK_RELEASE, CompensationPlanned.CREDIT_RELEASE),
}


def test_the_plans_are_the_spec_s_and_name_stock_before_credit() -> None:
    assert COMPENSATION_PLANS == PLANS
    for plan in PLANS.values():
        assert plan[0] is CompensationPlanned.STOCK_RELEASE, "stock is released FIRST (SA-4)"
    assert [p.value for p in PLANS[OrderStatus.CONFIRMED]] == ["stock_release", "credit_release"]


@pytest.mark.parametrize("status", list(PLANS))
async def test_a_compensating_status_enqueues_the_operators_stock_release_signals_it_after_commit_and_changes_nothing_else(
    status: OrderStatus, order_in: Callable[..., Order]
) -> None:
    order = order_in(status)
    handler, calls = handler_over(order)

    result = await handler.handle(CANCEL)

    assert calls.log == ["begin", "load_for_update", "enqueue", "commit", "publish"], (
        "loaded FOR UPDATE, enqueued inside the transaction, signalled strictly after the commit"
    )
    assert result == CancelOrderResult(
        order_id=order.id,
        order_reference=order.order_reference,
        status=status,
        cancellation_reason=None,
        compensation_planned=PLANS[status],
    )
    assert order.status is status, "the order stays where it is until a FACT completes the cancel"
    assert order.domain_events == (), "no order.cancelled.v1 yet"
    assert calls.saved == []
    [owed] = calls.enqueued
    assert owed.kind is SagaCommandKind.STOCK_RELEASE
    assert owed.order_id == order.id
    assert owed.order_reference == "ORD-000007"
    assert owed.operator_note == CANCEL.note
    assert owed.payload == '{"orderReference":"ORD-000007","reason":"order_cancelled"}'
    assert "note" not in owed.payload
    assert "$operator" not in owed.payload
    [event] = calls.published
    assert event == OperatorCancelAccepted(
        order_id=order.id, triggering_event_id=owed.triggering_event_id
    )


async def test_a_placed_order_is_cancelled_at_once_with_the_note_the_clocks_instant_and_no_signal(
    order_in: Callable[..., Order],
) -> None:
    order = order_in(OrderStatus.PLACED)
    handler, calls = handler_over(order)

    result = await handler.handle(CANCEL)

    assert calls.log == ["begin", "load_for_update", "save", "commit"]
    assert result.status is OrderStatus.CANCELLED
    assert result.cancellation_reason is CancellationReason.OPERATOR_CANCELLED
    assert result.compensation_planned == ()
    [cancelled] = order.domain_events
    assert cancelled.note == CANCEL.note  # type: ignore[attr-defined]
    assert cancelled.compensation_steps == ()  # type: ignore[attr-defined]
    assert cancelled.occurred_at == NOW  # type: ignore[attr-defined]
    assert cancelled.cancellation_reason is CancellationReason.OPERATOR_CANCELLED  # type: ignore[attr-defined]
    assert calls.enqueued == []
    assert calls.published == []


async def test_a_placed_order_cancelled_without_a_note_carries_none(
    order_in: Callable[..., Order],
) -> None:
    order = order_in(OrderStatus.PLACED)
    handler, _ = handler_over(order)

    await handler.handle(CancelOrderCommand(order_id=ORDER_ID, note=None))

    [cancelled] = order.domain_events
    assert cancelled.note is None  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "status",
    [
        OrderStatus.DESPATCHED,
        OrderStatus.INVOICED,
        OrderStatus.PAID,
        OrderStatus.COMPLETED,
        OrderStatus.CANCELLED,
    ],
)
async def test_a_status_the_aggregate_refuses_raises_its_own_error_and_writes_and_signals_nothing(
    status: OrderStatus, order_in: Callable[..., Order]
) -> None:
    order = order_in(status)
    handler, calls = handler_over(order)

    with pytest.raises(OrderNotCancellableError) as refused:
        await handler.handle(CANCEL)

    assert refused.value.source == status.value
    assert calls.log == ["begin", "load_for_update", "rollback"]
    assert calls.saved == []
    assert calls.enqueued == []
    assert calls.published == []
    assert order.status is status


async def test_an_unknown_order_raises_not_found_naming_the_id_and_rolls_back() -> None:
    handler, calls = handler_over(None)

    with pytest.raises(OrderNotFoundError) as refused:
        await handler.handle(CANCEL)

    assert refused.value.order_id == ORDER_ID
    assert str(ORDER_ID.value) in str(refused.value)
    assert calls.log == ["begin", "load_for_update", "rollback"]


def test_a_scope_without_a_dispatcher_refuses_the_handler_at_boot_not_on_the_first_cancel() -> None:
    scope = OrdersScope(
        unit_of_work=cast("Any", object()),
        catalog=cast("Any", object()),
        stock=cast("Any", object()),
        clock=FixedClock(),
    )

    with pytest.raises(Exception, match="dispatcher"):
        CancelOrderCommandHandler(scope)


@pytest.mark.parametrize("status", list(PLANS))
async def test_or12_the_operators_release_is_enqueued_with_no_triggering_envelope_and_no_topic(
    status: OrderStatus, order_in: Callable[..., Order]
) -> None:
    """Gate G1: no fact owes the operator's release, so there is no envelope to dead-letter and no
    topic to dead-letter it to. A synthetic `orders.cancel.requested` envelope would be a record no
    producer ever wrote (and the traceparent is stored by the queue, not passed by the handler)."""
    handler, calls = handler_over(order_in(status))

    await handler.handle(CANCEL)

    [owed] = calls.enqueued
    assert owed.triggering_event_envelope is None
    assert owed.triggering_event_topic is None
