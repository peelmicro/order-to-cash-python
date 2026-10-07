"""Order totals (R6, invariant O3; `design.md` section 5): derived, never negative, never half-done.

Every expected figure is hand-computed from the two fixture lines (conftest.py) and typed here:
3 x 1999 + 2 x 1234 = 8465 initial; 250 + 100 = 350 discount; 8115 total. All non-round.
"""

from collections.abc import Callable
from datetime import datetime

import pytest

from otc_orders.domain.errors import OrderTotalMustNotBeNegativeError
from otc_orders.domain.order import Order
from otc_orders.domain.order_line import OrderLineInput
from otc_shared_kernel import InvalidMoneyAmountError, Money, Quantity

State = tuple[object, ...]

MAX_MINOR_UNITS = 9_223_372_036_854_775_807  # signed 64-bit, the bigint column


def _line(
    *, quantity: int, price: int, discount: int, currency: str = "EUR", code: str = "SKU-N"
) -> OrderLineInput:
    return OrderLineInput(
        product_code=code,
        description=None,
        quantity=Quantity(quantity),
        unit_price=Money(price, currency),
        line_discount=Money(discount, currency),
    )


def _totals(order: Order) -> tuple[int, int, int]:
    return (
        order.initial_amount.amount,
        order.initial_discount.amount,
        order.total_amount.amount,
    )


def test_r6_order_recomputes_initial_amount_initial_discount_and_total_amount_after_each_mutation(
    placed_order: Order, at: Callable[[int], datetime]
) -> None:
    assert _totals(placed_order) == (8465, 350, 8115)

    added = placed_order.add_line(
        product_code="SKU-C",
        description=None,
        quantity=Quantity(4),
        unit_price=Money(777, "EUR"),
        line_discount=Money(33, "EUR"),
        occurred_at=at(1),
    )
    assert _totals(placed_order) == (8465 + 3108, 350 + 33, 11573 - 383)

    first = placed_order.lines[0].id
    placed_order.change_line(
        line_id=first,
        quantity=Quantity(5),
        unit_price=Money(1500, "EUR"),
        line_discount=Money(125, "EUR"),
        occurred_at=at(2),
    )
    # 5 x 1500 + 2 x 1234 + 4 x 777 = 13076; 125 + 100 + 33 = 258; 12818
    assert _totals(placed_order) == (13076, 258, 12818)

    second = placed_order.lines[1].id
    placed_order.remove_line(line_id=second, occurred_at=at(3))
    # 5 x 1500 + 4 x 777 = 10608; 125 + 33 = 158; 10450
    assert _totals(placed_order) == (10608, 158, 10450)
    assert placed_order.initial_discount.amount == sum(
        line.line_discount.amount for line in placed_order.lines
    )
    assert placed_order.lines[-1].id == added
    assert placed_order.updated_at == at(3)
    assert {m.currency for m in (placed_order.total_amount, placed_order.initial_amount)} == {"EUR"}


def _negative_attempts(
    order: Order, at: Callable[[int], datetime]
) -> dict[str, Callable[[], object]]:
    return {
        "add_line": lambda: order.add_line(
            product_code="SKU-X",
            description=None,
            quantity=Quantity(1),
            unit_price=Money(100, "EUR"),
            line_discount=Money(9000, "EUR"),
            occurred_at=at(5),
        ),
        "change_line": lambda: order.change_line(
            line_id=order.lines[1].id,
            quantity=Quantity(1),
            unit_price=Money(100, "EUR"),
            line_discount=Money(9000, "EUR"),
            occurred_at=at(5),
        ),
    }


@pytest.mark.parametrize("mutation", ["add_line", "change_line"])
def test_r6_order_rejects_a_mutation_whose_resulting_total_amount_would_be_negative_and_leaves_the_order_unchanged(  # noqa: E501
    mutation: str,
    placed_order: Order,
    at: Callable[[int], datetime],
    state_of: Callable[[Order], State],
) -> None:
    before = state_of(placed_order)
    lines_before = placed_order.lines
    attempt = _negative_attempts(placed_order, at)[mutation]
    with pytest.raises(OrderTotalMustNotBeNegativeError) as raised:
        attempt()
    assert raised.value.code == "order.total_must_not_be_negative"
    assert state_of(placed_order) == before  # status, lines, all three totals, updated_at, events
    assert placed_order.lines == lines_before
    assert _totals(placed_order) == (8465, 350, 8115)


def test_r6_place_refuses_a_negative_total(place_order: Callable[..., Order]) -> None:
    with pytest.raises(OrderTotalMustNotBeNegativeError) as raised:
        place_order(lines=(_line(quantity=2, price=100, discount=500),))
    assert raised.value.code == "order.total_must_not_be_negative"
    assert raised.value.candidate_total == Money(-300, "EUR")


def test_r6_a_total_of_exactly_zero_is_allowed(place_order: Callable[..., Order]) -> None:
    order = place_order(lines=(_line(quantity=1, price=500, discount=500),))
    assert _totals(order) == (500, 500, 0)


def test_the_negative_total_message_renders_money_text_never_minor_units(
    place_order: Callable[..., Order],
) -> None:
    with pytest.raises(OrderTotalMustNotBeNegativeError) as euro:
        place_order(lines=(_line(quantity=1, price=100, discount=200),))
    assert euro.value.message == "The resulting total amount would be negative: -1.00 EUR."

    with pytest.raises(OrderTotalMustNotBeNegativeError) as yen:
        place_order(
            currency="JPY", lines=(_line(quantity=1, price=1000, discount=2000, currency="JPY"),)
        )
    assert yen.value.message == "The resulting total amount would be negative: -1 000 JPY."


def test_an_overflowing_total_is_refused_and_leaves_the_order_unchanged(
    placed_order: Order,
    at: Callable[[int], datetime],
    state_of: Callable[[Order], State],
) -> None:
    before = state_of(placed_order)
    lines_before = placed_order.lines
    with pytest.raises(InvalidMoneyAmountError) as raised:
        placed_order.add_line(
            product_code="SKU-BIG",
            description=None,
            quantity=Quantity(2),
            unit_price=Money(MAX_MINOR_UNITS, "EUR"),
            line_discount=Money(0, "EUR"),
            occurred_at=at(5),
        )
    assert raised.value.code == "money.invalid_amount"
    assert state_of(placed_order) == before
    assert placed_order.lines == lines_before
    assert len(placed_order.lines) == 2
    assert _totals(placed_order) == (8465, 350, 8115)
