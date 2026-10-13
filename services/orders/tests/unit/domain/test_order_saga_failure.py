"""`Order.record_saga_failure` (S4.14, `R29`, `OR3`): one `order.saga_failed.v1` and NOTHING else.

The pure half of the first park (the mapper half is in `test_outbox_payloads.py`). The status, the
lines, the totals and `updated_at` are compared as a whole state before and after.
"""

from collections.abc import Callable
from datetime import datetime

import pytest

from otc_orders.domain.errors import InstantNotUtcError
from otc_orders.domain.events import OrderSagaFailed
from otc_orders.domain.order import Order
from otc_orders.domain.value_objects.order_status import OrderStatus
from otc_shared_kernel import UniqueId


def state_of(order: Order) -> tuple[object, ...]:
    return (
        order.status,
        order.cancellation_reason,
        order.lines,
        order.initial_amount,
        order.initial_discount,
        order.total_amount,
        order.notes,
        order.created_at,
        order.updated_at,
    )


def test_r29_a_first_park_raises_exactly_one_saga_failed_event_and_changes_nothing_else(
    placed_order: Order,
    walk_to: Callable[[Order, OrderStatus], None],
    at: Callable[[int], datetime],
) -> None:
    walk_to(placed_order, OrderStatus.STOCK_RESERVED)
    order = placed_order
    before_events = len(order.domain_events)
    before = state_of(order)
    cause = UniqueId.new()

    order.record_saga_failure(
        command="credit.hold",
        attempts=7,
        last_error="no reply within 400 ms from billing.credit.hold",
        occurred_at=at(95),
        causation_id=cause,
    )

    assert state_of(order) == before, "status, lines, totals and updated_at are unchanged"
    new = order.domain_events[before_events:]
    assert len(new) == 1, "exactly one event"
    event = new[0]
    assert isinstance(event, OrderSagaFailed)
    assert event.correlation_id == order.id
    assert event.aggregate_id == order.id
    assert event.causation_id == cause


def test_r29_a_naive_instant_is_refused_before_any_event_is_raised(
    placed_order: Order,
) -> None:
    before = len(placed_order.domain_events)
    with pytest.raises(InstantNotUtcError):
        placed_order.record_saga_failure(
            command="stock.reserve",
            attempts=1,
            last_error="x",
            occurred_at=datetime(2026, 10, 1, 10, 0, 0),
            causation_id=UniqueId.new(),
        )
    assert len(placed_order.domain_events) == before
