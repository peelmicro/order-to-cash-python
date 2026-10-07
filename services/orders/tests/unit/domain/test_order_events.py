"""The four domain events and what raises them (O8, R12's aggregate half; `design.md` section 7).

The event types and the fact-bearing / silent split are LITERALS transcribed from Table T-1's Fact
column: rows 1, 4, 8 and 9 - 12 raise a fact; rows 2, 3, 5, 6, 7 raise nothing.
"""

import dataclasses
import importlib
import pkgutil
import typing
from collections.abc import Callable
from dataclasses import FrozenInstanceError
from datetime import datetime

import pytest

import otc_orders.domain
from otc_orders.domain.events import (
    OrderCancelled,
    OrderCompleted,
    OrderConfirmed,
    OrderEvent,
    OrderPlaced,
)
from otc_orders.domain.order import Order
from otc_orders.domain.value_objects.cancellation_reason import CancellationReason
from otc_orders.domain.value_objects.compensation_step import CompensationStep, CompensationStepKind
from otc_orders.domain.value_objects.order_status import OrderStatus
from otc_shared_kernel import GLN, Money, OrderNumber, Quantity, UniqueId

PLACED_TYPE = "order.placed.v1"
CONFIRMED_TYPE = "order.confirmed.v1"
COMPLETED_TYPE = "order.completed.v1"
CANCELLED_TYPE = "order.cancelled.v1"

OPERATOR = CancellationReason.OPERATOR_CANCELLED


def _events(order: Order) -> list[OrderEvent]:
    narrowed: list[OrderEvent] = []
    for event in order.domain_events:
        assert isinstance(event, OrderPlaced | OrderConfirmed | OrderCompleted | OrderCancelled)
        narrowed.append(event)
    return narrowed


def _types(order: Order) -> list[str]:
    return [type(event).EVENT_TYPE for event in order.domain_events if hasattr(event, "EVENT_TYPE")]


def test_o8_order_appends_exactly_one_domain_event_for_each_fact_bearing_edge_of_table_t1(
    place_order: Callable[..., Order],
    walk_to: Callable[[Order, OrderStatus], None],
    at: Callable[[int], datetime],
    causation: UniqueId,
) -> None:
    # Row 1: `place` is creation, with exactly one `order.placed.v1`.
    order = place_order()
    assert _types(order) == [PLACED_TYPE]
    assert len(order.domain_events) == 1

    # Row 4: credit_approved -> confirmed.
    walk_to(order, OrderStatus.CREDIT_APPROVED)
    before = len(order.domain_events)
    order.confirm(occurred_at=at(30), causation_id=causation)
    assert len(order.domain_events) == before + 1
    assert _types(order)[-1] == CONFIRMED_TYPE

    # Row 8: paid -> completed.
    walk_to(order, OrderStatus.PAID)
    before = len(order.domain_events)
    order.complete(occurred_at=at(70), causation_id=causation)
    assert len(order.domain_events) == before + 1
    assert _types(order)[-1] == COMPLETED_TYPE

    # Rows 9 - 12: each cancel row from its source.
    for source in (
        OrderStatus.PLACED,
        OrderStatus.STOCK_RESERVED,
        OrderStatus.CREDIT_APPROVED,
        OrderStatus.CONFIRMED,
    ):
        fresh = place_order()
        walk_to(fresh, source)
        before = len(fresh.domain_events)
        fresh.cancel(
            reason=OPERATOR, compensation_steps=(), occurred_at=at(80), causation_id=causation
        )
        assert len(fresh.domain_events) == before + 1, source
        assert _types(fresh)[-1] == CANCELLED_TYPE, source


def test_o8_order_appends_no_domain_event_on_the_five_silent_edges_of_table_t1(
    place_order: Callable[..., Order],
    at: Callable[[int], datetime],
    causation: UniqueId,
) -> None:
    order = place_order()
    order.pull_domain_events()  # drop `order.placed.v1`: only the silent edges are counted below
    order.mark_stock_reserved(occurred_at=at(10))  # row 2
    assert order.domain_events == ()
    order.approve_credit(occurred_at=at(20))  # row 3
    assert order.domain_events == ()
    order.confirm(occurred_at=at(30), causation_id=causation)  # row 4 (a fact)
    order.pull_domain_events()
    order.mark_despatched(occurred_at=at(40))  # row 5
    assert order.domain_events == ()
    order.mark_invoiced(occurred_at=at(50))  # row 6
    assert order.domain_events == ()
    order.mark_paid(occurred_at=at(60))  # row 7
    assert order.domain_events == ()
    assert order.status is OrderStatus.PAID


def test_events_are_frozen_and_hold_tuples_and_steps_are_copied(
    place_order: Callable[..., Order],
    walk_to: Callable[[Order, OrderStatus], None],
    at: Callable[[int], datetime],
    causation: UniqueId,
) -> None:
    order = place_order()
    placed = order.domain_events[0]
    assert isinstance(placed, OrderPlaced)
    with pytest.raises(FrozenInstanceError):
        placed.event_id = UniqueId.new()  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        placed.total_amount = placed.initial_amount  # type: ignore[misc]

    supplied = [
        CompensationStep(
            step=CompensationStepKind.STOCK_RELEASED,
            event_id=None,
            event_type="stock.released.v1",
            occurred_at=at(31),
        )
    ]
    walk_to(order, OrderStatus.STOCK_RESERVED)
    order.cancel(
        reason=CancellationReason.CREDIT_REJECTED,
        compensation_steps=supplied,
        occurred_at=at(40),
        causation_id=causation,
    )
    cancelled = order.domain_events[-1]
    assert isinstance(cancelled, OrderCancelled)
    assert isinstance(cancelled.compensation_steps, tuple)
    steps_before = cancelled.compensation_steps
    supplied.append(supplied[0])
    supplied.clear()
    assert cancelled.compensation_steps == steps_before
    assert len(cancelled.compensation_steps) == 1
    with pytest.raises(FrozenInstanceError):
        cancelled.note = "changed"  # type: ignore[misc]


DOMAIN_DATACLASSES = {
    "OrderEventBase",
    "OrderPlacedLine",
    "OrderPlaced",
    "OrderConfirmed",
    "OrderCompleted",
    "OrderCancelled",
    "CompensationStep",
    "OrderSnapshot",
    "OrderLineSnapshot",
    "OrderLineInput",
    "OrderTotals",
}


def _holds_a_list(annotation: object) -> bool:
    if annotation is list or typing.get_origin(annotation) is list:
        return True
    return any(_holds_a_list(argument) for argument in typing.get_args(annotation))


def test_no_domain_dataclass_has_a_list_field_and_the_population_is_the_literal_set() -> None:
    found: dict[str, type] = {}
    for module_info in pkgutil.walk_packages(
        otc_orders.domain.__path__, prefix="otc_orders.domain."
    ):
        module = importlib.import_module(module_info.name)
        for value in vars(module).values():
            if (
                isinstance(value, type)
                and dataclasses.is_dataclass(value)
                and value.__module__.startswith("otc_orders.domain")
            ):
                found[value.__name__] = value
    assert set(found) == DOMAIN_DATACLASSES
    offenders = [
        f"{name}.{field.name}"
        for name, cls in found.items()
        for field in dataclasses.fields(cls)
        if _holds_a_list(field.type)
    ]
    assert not offenders, f"a frozen dataclass holding a list is still mutable: {offenders}"


def test_order_event_is_the_union_of_exactly_the_four_event_classes() -> None:
    assert set(typing.get_args(OrderEvent.__value__)) == {
        OrderPlaced,
        OrderConfirmed,
        OrderCompleted,
        OrderCancelled,
    }
    assert len(typing.get_args(OrderEvent.__value__)) == 4


def test_r12_order_stamps_every_domain_event_with_a_fresh_event_id_the_order_id_as_correlation_id_and_the_supplied_causation_id(  # noqa: E501
    place_order: Callable[..., Order],
    walk_to: Callable[[Order, OrderStatus], None],
    at: Callable[[int], datetime],
) -> None:
    placing_cause = UniqueId.new()
    confirming_cause = UniqueId.new()
    completing_cause = UniqueId.new()
    cancelling_cause = UniqueId.new()

    completed_order = place_order(causation_id=placing_cause, occurred_at=at(0))
    walk_to(completed_order, OrderStatus.CREDIT_APPROVED)
    completed_order.confirm(occurred_at=at(31), causation_id=confirming_cause)
    walk_to(completed_order, OrderStatus.PAID)
    completed_order.complete(occurred_at=at(71), causation_id=completing_cause)

    cancelled_order = place_order(causation_id=placing_cause, occurred_at=at(1))
    cancelled_order.cancel(
        reason=OPERATOR, compensation_steps=(), occurred_at=at(81), causation_id=cancelling_cause
    )

    events = [*_events(completed_order), *_events(cancelled_order)]
    assert [type(e) for e in events] == [
        OrderPlaced,
        OrderConfirmed,
        OrderCompleted,
        OrderPlaced,
        OrderCancelled,
    ]
    owners = [completed_order] * 3 + [cancelled_order] * 2
    causes = [placing_cause, confirming_cause, completing_cause, placing_cause, cancelling_cause]
    instants = [at(0), at(31), at(71), at(1), at(81)]
    for event, owner, cause, instant in zip(events, owners, causes, instants, strict=True):
        assert event.aggregate_id == owner.id
        assert event.correlation_id == owner.id
        assert event.causation_id == cause
        assert event.causation_id != owner.id
        assert event.occurred_at == instant

    confirmed, completed, cancelled = events[1], events[2], events[4]
    assert isinstance(confirmed, OrderConfirmed)
    assert isinstance(completed, OrderCompleted)
    assert isinstance(cancelled, OrderCancelled)
    assert confirmed.confirmed_at == at(31)
    assert completed.completed_at == at(71)
    assert cancelled.cancelled_at == at(81)

    every_id = [
        *(e.event_id for e in events),
        *(e.aggregate_id for e in events[:1] + events[3:4]),
        placing_cause,
        confirming_cause,
        completing_cause,
        cancelling_cause,
    ]
    assert len(set(every_id)) == len(every_id), "an id was reused where a fresh one was owed"


def test_the_events_carry_the_aggregate_state_not_the_request(
    place_order: Callable[..., Order],
    walk_to: Callable[[Order, OrderStatus], None],
    at: Callable[[int], datetime],
    causation: UniqueId,
) -> None:
    order = place_order(notes="gate 4", order_reference="ORD-000009")
    placed = order.domain_events[0]
    assert isinstance(placed, OrderPlaced)
    assert (placed.initial_amount.amount, placed.initial_discount.amount) == (8465, 350)
    assert placed.total_amount == order.total_amount
    assert placed.notes == "gate 4"
    assert str(placed.order_reference) == "ORD-000009"
    assert [line.product_code for line in placed.lines] == ["SKU-A", "SKU-B"]
    assert placed.lines[0].quantity.value == 3
    assert placed.lines[1].description is None

    walk_to(order, OrderStatus.CREDIT_APPROVED)
    order.confirm(occurred_at=at(30), causation_id=causation)
    confirmed = order.domain_events[-1]
    assert isinstance(confirmed, OrderConfirmed)
    assert confirmed.total_amount == order.total_amount
    assert (confirmed.currency, confirmed.retailer_code, confirmed.company_code) == (
        "EUR",
        "RET-01",
        "CMP-01",
    )


def test_pull_domain_events_empties_the_pending_list_and_leaves_every_other_field_untouched(
    placed_order: Order,
    state_of: Callable[[Order], tuple[object, ...]],
) -> None:
    before = state_of(placed_order)
    drained = placed_order.pull_domain_events()
    assert len(drained) == 1
    assert isinstance(drained[0], OrderPlaced)
    assert placed_order.domain_events == ()
    assert placed_order.pull_domain_events() == ()
    after = state_of(placed_order)
    assert after[:-1] == before[:-1]
    assert (before[-1], after[-1]) == (1, 0)


def test_every_payload_field_of_each_of_the_four_events_is_the_value_the_aggregate_was_given(
    place_order: Callable[..., Order],
    walk_to: Callable[[Order, OrderStatus], None],
    at: Callable[[int], datetime],
    causation: UniqueId,
) -> None:
    # Pairwise distinct: GLNs, retailer vs company code, order_date (-60) vs occurred_at (0),
    # unit price vs discount per line, initial (8465) vs total (8115) amount.
    order = place_order(notes="gate 4", order_reference="ORD-000009")
    placed = order.domain_events[0]
    assert isinstance(placed, OrderPlaced)
    assert placed.order_reference == OrderNumber("ORD-000009")
    assert placed.retailer_code == "RET-01"
    assert placed.company_code == "CMP-01"
    assert placed.buyer_gln == GLN("4012345000009")
    assert placed.supplier_gln == GLN("5412345000006")
    assert placed.currency == "EUR"
    assert placed.order_date == at(-60)
    assert placed.occurred_at == at(0)
    assert placed.notes == "gate 4"
    assert placed.initial_amount == Money(8465, "EUR")
    assert placed.initial_discount == Money(350, "EUR")
    assert placed.total_amount == Money(8115, "EUR")
    assert [
        (x.product_code, x.description, x.quantity, x.unit_price, x.line_discount)
        for x in placed.lines
    ] == [
        ("SKU-A", "Alpha pallet", Quantity(3), Money(1999, "EUR"), Money(250, "EUR")),
        ("SKU-B", None, Quantity(2), Money(1234, "EUR"), Money(100, "EUR")),
    ]

    walk_to(order, OrderStatus.CREDIT_APPROVED)
    order.confirm(occurred_at=at(30), causation_id=causation)
    confirmed = order.domain_events[-1]
    assert isinstance(confirmed, OrderConfirmed)
    assert (
        confirmed.order_reference,
        confirmed.retailer_code,
        confirmed.company_code,
        confirmed.currency,
        confirmed.total_amount,
    ) == (OrderNumber("ORD-000009"), "RET-01", "CMP-01", "EUR", Money(8115, "EUR"))

    walk_to(order, OrderStatus.COMPLETED)
    completed = order.domain_events[-1]
    assert isinstance(completed, OrderCompleted)
    assert (
        completed.order_reference,
        completed.retailer_code,
        completed.company_code,
        completed.currency,
        completed.total_amount,
    ) == (OrderNumber("ORD-000009"), "RET-01", "CMP-01", "EUR", Money(8115, "EUR"))

    other = place_order(order_reference="ORD-000010")
    other.cancel(
        reason=OPERATOR,
        compensation_steps=(),
        occurred_at=at(90),
        causation_id=causation,
    )
    cancelled = other.domain_events[-1]
    assert isinstance(cancelled, OrderCancelled)
    assert (
        cancelled.order_reference,
        cancelled.retailer_code,
        cancelled.company_code,
    ) == (OrderNumber("ORD-000010"), "RET-01", "CMP-01")
