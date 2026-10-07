"""Every instant the aggregate is given is aware UTC (`design.md` L13, section 7.5).

The population of instant parameters is a literal list; a second assertion compares it with every
parameter annotated `datetime` across `Order`'s public signatures, so a new instant parameter
without a case here fails by name.
"""

import inspect
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone

import pytest

from otc_orders.domain.errors import InstantNotUtcError
from otc_orders.domain.order import Order
from otc_orders.domain.value_objects.cancellation_reason import CancellationReason
from otc_orders.domain.value_objects.compensation_step import CompensationStep, CompensationStepKind
from otc_orders.domain.value_objects.order_status import OrderStatus
from otc_shared_kernel import Money, Quantity, UniqueId

State = tuple[object, ...]

INSTANT_PARAMETERS = {
    ("place", "order_date"),
    ("place", "occurred_at"),
    ("mark_stock_reserved", "occurred_at"),
    ("approve_credit", "occurred_at"),
    ("confirm", "occurred_at"),
    ("mark_despatched", "occurred_at"),
    ("mark_invoiced", "occurred_at"),
    ("mark_paid", "occurred_at"),
    ("complete", "occurred_at"),
    ("cancel", "occurred_at"),
    ("add_line", "occurred_at"),
    ("remove_line", "occurred_at"),
    ("change_line", "occurred_at"),
}

NAIVE = datetime(2026, 10, 1, 9, 0, 0)
PLUS_ONE = datetime(2026, 10, 1, 9, 0, 0, tzinfo=timezone(timedelta(hours=1)))
BAD_INSTANTS = [NAIVE, PLUS_ONE]


def _public_instant_parameters() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for name, member in inspect.getmembers(Order):
        if name.startswith("_") or isinstance(member, property) or not callable(member):
            continue
        for parameter in inspect.signature(member).parameters.values():
            if parameter.annotation is datetime:
                found.add((name, parameter.name))
    return found


def test_the_instant_parameter_population_is_the_literal_list() -> None:
    assert len(INSTANT_PARAMETERS) == 13
    assert _public_instant_parameters() == INSTANT_PARAMETERS


@pytest.mark.parametrize("bad", BAD_INSTANTS, ids=["naive", "plus-one-hour"])
def test_every_instant_parameter_refuses_a_naive_or_non_utc_datetime(
    bad: datetime,
    place_order: Callable[..., Order],
    order_in: Callable[..., Order],
    walk_to: Callable[[Order, OrderStatus], None],
    state_of: Callable[[Order], State],
    causation: UniqueId,
    at: Callable[[int], datetime],
) -> None:
    def in_status(status: OrderStatus) -> Order:
        # The order is in the status where the call would be LEGAL, so only the instant is wrong.
        order = place_order()
        walk_to(order, status)
        return order

    def add(order: Order) -> None:
        order.add_line(
            product_code="SKU-Z",
            description=None,
            quantity=Quantity(1),
            unit_price=Money(10, "EUR"),
            line_discount=Money(0, "EUR"),
            occurred_at=bad,
        )

    cases: dict[tuple[str, str], tuple[OrderStatus, Callable[[Order], None]]] = {
        ("mark_stock_reserved", "occurred_at"): (
            OrderStatus.PLACED,
            lambda o: o.mark_stock_reserved(occurred_at=bad),
        ),
        ("approve_credit", "occurred_at"): (
            OrderStatus.STOCK_RESERVED,
            lambda o: o.approve_credit(occurred_at=bad),
        ),
        ("confirm", "occurred_at"): (
            OrderStatus.CREDIT_APPROVED,
            lambda o: o.confirm(occurred_at=bad, causation_id=causation),
        ),
        ("mark_despatched", "occurred_at"): (
            OrderStatus.CONFIRMED,
            lambda o: o.mark_despatched(occurred_at=bad),
        ),
        ("mark_invoiced", "occurred_at"): (
            OrderStatus.DESPATCHED,
            lambda o: o.mark_invoiced(occurred_at=bad),
        ),
        ("mark_paid", "occurred_at"): (
            OrderStatus.INVOICED,
            lambda o: o.mark_paid(occurred_at=bad),
        ),
        ("complete", "occurred_at"): (
            OrderStatus.PAID,
            lambda o: o.complete(occurred_at=bad, causation_id=causation),
        ),
        ("cancel", "occurred_at"): (
            OrderStatus.PLACED,
            lambda o: o.cancel(
                reason=CancellationReason.OPERATOR_CANCELLED,
                compensation_steps=(),
                occurred_at=bad,
                causation_id=causation,
            ),
        ),
        ("add_line", "occurred_at"): (OrderStatus.PLACED, add),
        ("remove_line", "occurred_at"): (
            OrderStatus.PLACED,
            lambda o: o.remove_line(line_id=o.lines[0].id, occurred_at=bad),
        ),
        ("change_line", "occurred_at"): (
            OrderStatus.PLACED,
            lambda o: o.change_line(
                line_id=o.lines[0].id,
                quantity=Quantity(1),
                unit_price=Money(10, "EUR"),
                line_discount=Money(0, "EUR"),
                occurred_at=bad,
            ),
        ),
    }
    for (method, parameter), (status, attempt) in cases.items():
        order = in_status(status)
        before = state_of(order)
        with pytest.raises(InstantNotUtcError) as raised:
            attempt(order)
        assert raised.value.code == "order.instant_not_utc", method
        assert raised.value.field == parameter, method
        assert state_of(order) == before, f"{method} changed the order"

    # `place` has no order to leave unchanged: it must refuse, and the error names the parameter.
    for parameter in ("order_date", "occurred_at"):
        with pytest.raises(InstantNotUtcError) as placed:
            place_order(**{parameter: bad})
        assert placed.value.code == "order.instant_not_utc"
        assert placed.value.field == parameter

    # The case list covers every literal parameter but the two of `place`, and `CompensationStep`.
    assert {*cases, ("place", "order_date"), ("place", "occurred_at")} == INSTANT_PARAMETERS
    with pytest.raises(InstantNotUtcError) as step:
        CompensationStep(
            step=CompensationStepKind.STOCK_RELEASED,
            event_id=None,
            event_type="stock.released.v1",
            occurred_at=bad,
        )
    assert step.value.code == "order.instant_not_utc"


def test_a_utc_instant_in_any_spelling_of_utc_is_accepted(
    place_order: Callable[..., Order],
) -> None:
    # Offset zero is UTC whichever tzinfo object spells it (`datetime.UTC` or `timezone(0)`).
    spelled = datetime(2026, 10, 1, 9, 0, 0, tzinfo=timezone(timedelta(0)))
    order = place_order(occurred_at=spelled, order_date=datetime(2026, 9, 30, 9, 0, tzinfo=UTC))
    assert order.updated_at == spelled
