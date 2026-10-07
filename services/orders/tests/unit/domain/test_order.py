"""The Order aggregate: creation, line mutation, freeze, currency (R5, R7, O2; `design.md` 5, 6)."""

from collections.abc import Callable
from datetime import datetime

import pytest

from otc_orders.domain.errors import (
    OrderLineCurrencyMismatchError,
    OrderLineNotFoundError,
    OrderLinesAreFrozenError,
    OrderMustHaveAtLeastOneLineError,
)
from otc_orders.domain.events import OrderPlaced
from otc_orders.domain.order import Order
from otc_orders.domain.order_line import OrderLineInput
from otc_orders.domain.value_objects.order_status import OrderStatus
from otc_shared_kernel import GLN, Money, OrderNumber, Quantity, UniqueId

State = tuple[object, ...]

# R7's six frozen statuses and the three mutable ones: literals transcribed from the requirement.
R7_FROZEN = ["confirmed", "despatched", "invoiced", "paid", "completed", "cancelled"]
MUTABLE = ["placed", "stock_reserved", "credit_approved"]


def test_place_generates_a_fresh_order_id_and_fresh_line_ids_inside_the_domain(
    place_order: Callable[..., Order],
) -> None:
    first = place_order()
    second = place_order()
    ids = [
        first.id,
        second.id,
        *(line.id for line in first.lines),
        *(line.id for line in second.lines),
    ]
    event_ids = [
        e.event_id
        for e in (*first.domain_events, *second.domain_events)
        if isinstance(e, OrderPlaced)
    ]
    assert len(event_ids) == 2
    assert len({*ids, *event_ids}) == len(ids) + len(event_ids) == 8


def test_r5_order_refuses_to_create_an_order_with_no_lines_and_to_remove_the_last_remaining_line(
    place_order: Callable[..., Order],
    one_line_order: Order,
    at: Callable[[int], datetime],
    state_of: Callable[[Order], State],
) -> None:
    with pytest.raises(OrderMustHaveAtLeastOneLineError) as created:
        place_order(lines=())
    assert created.value.code == "order.must_have_at_least_one_line"

    before = state_of(one_line_order)
    only_line = one_line_order.lines[0].id
    with pytest.raises(OrderMustHaveAtLeastOneLineError) as removed:
        one_line_order.remove_line(line_id=only_line, occurred_at=at(5))
    assert removed.value.code == "order.must_have_at_least_one_line"
    assert state_of(one_line_order) == before
    assert len(one_line_order.lines) == 1


def test_lines_are_a_tuple_and_mutating_the_input_after_place_changes_nothing(
    place_order: Callable[..., Order],
    line_a: OrderLineInput,
    line_b: OrderLineInput,
) -> None:
    supplied = [line_a, line_b]
    order = place_order(lines=supplied)
    assert isinstance(order.lines, tuple)
    placed = next(e for e in order.domain_events if isinstance(e, OrderPlaced))
    assert isinstance(placed.lines, tuple)
    before = (
        order.lines,
        order.initial_amount,
        order.initial_discount,
        order.total_amount,
        placed.lines,
    )

    supplied.append(line_a)
    assert len(order.lines) == 2
    supplied.clear()
    assert (
        order.lines,
        order.initial_amount,
        order.initial_discount,
        order.total_amount,
        placed.lines,
    ) == before
    assert len(order.lines) == 2
    assert len(placed.lines) == 2

    with pytest.raises(AttributeError):
        order.lines[0].quantity = Quantity(9)  # type: ignore[misc]
    with pytest.raises(AttributeError):
        order.lines[0].unit_price = Money(1, "EUR")  # type: ignore[misc]


@pytest.mark.parametrize("status", R7_FROZEN)
def test_r7_order_refuses_to_add_remove_or_modify_a_line_once_the_order_is_confirmed_and_leaves_every_field_unchanged(  # noqa: E501
    status: str,
    order_in: Callable[..., Order],
    at: Callable[[int], datetime],
    state_of: Callable[[Order], State],
    line_a: OrderLineInput,
) -> None:
    # A ONE-line order: removing its only line would also trip the empty-order check, so the CODE
    # asserted below can only be the freeze if the freeze runs first (design.md 6.2).
    order = order_in(OrderStatus(status), line_count=1)
    only_line = order.lines[0].id
    before = state_of(order)

    with pytest.raises(OrderLinesAreFrozenError) as added:
        order.add_line(
            product_code="SKU-Z",
            description=None,
            quantity=Quantity(1),
            unit_price=Money(10, "EUR"),
            line_discount=Money(0, "EUR"),
            occurred_at=at(5),
        )
    with pytest.raises(OrderLinesAreFrozenError) as removed:
        order.remove_line(line_id=only_line, occurred_at=at(5))
    with pytest.raises(OrderLinesAreFrozenError) as changed:
        order.change_line(
            line_id=only_line,
            quantity=Quantity(7),
            unit_price=Money(11, "EUR"),
            line_discount=Money(1, "EUR"),
            occurred_at=at(5),
        )
    for raised in (added, removed, changed):
        assert raised.value.code == "order.lines_are_frozen"
    assert state_of(order) == before


def _mutate_all_three(order: Order, at: Callable[[int], datetime]) -> None:
    added = order.add_line(
        product_code="SKU-Z",
        description="Zulu",
        quantity=Quantity(1),
        unit_price=Money(500, "EUR"),
        line_discount=Money(0, "EUR"),
        occurred_at=at(5),
    )
    order.change_line(
        line_id=added,
        quantity=Quantity(2),
        unit_price=Money(500, "EUR"),
        line_discount=Money(5, "EUR"),
        occurred_at=at(6),
    )
    order.remove_line(line_id=added, occurred_at=at(7))


def test_r7_lines_are_mutable_exactly_in_placed_stock_reserved_and_credit_approved(
    order_in: Callable[..., Order],
    at: Callable[[int], datetime],
) -> None:
    assert len(MUTABLE) + len(R7_FROZEN) == 9
    assert set(MUTABLE) | set(R7_FROZEN) == {s.value for s in OrderStatus}
    assert not set(MUTABLE) & set(R7_FROZEN)
    for status in MUTABLE:
        order = order_in(OrderStatus(status))
        _mutate_all_three(order, at)
        assert len(order.lines) == 2, status
        assert order.updated_at == at(7), status
    for status in R7_FROZEN:
        with pytest.raises(OrderLinesAreFrozenError):
            _mutate_all_three(order_in(OrderStatus(status)), at)


def test_r6_add_line_and_change_line_keep_every_non_money_field_supplied(
    one_line_order: Order,
    at: Callable[[int], datetime],
) -> None:
    # Pairwise-distinct fixture values: product_code, description and quantity never coincide.
    added_id = one_line_order.add_line(
        product_code="SKU-ALPHA",
        description="Bravo widget",
        quantity=Quantity(3),
        unit_price=Money(500, "EUR"),
        line_discount=Money(0, "EUR"),
        occurred_at=at(5),
    )
    added = next(line for line in one_line_order.lines if line.id == added_id)
    assert added.product_code == "SKU-ALPHA"
    assert added.description == "Bravo widget"
    assert added.quantity == Quantity(3)

    one_line_order.change_line(
        line_id=added_id,
        quantity=Quantity(4),
        unit_price=Money(600, "EUR"),
        line_discount=Money(7, "EUR"),
        occurred_at=at(6),
    )
    changed = next(line for line in one_line_order.lines if line.id == added_id)
    assert changed.product_code == "SKU-ALPHA"
    assert changed.description == "Bravo widget"
    assert changed.quantity == Quantity(4)
    assert changed.unit_price == Money(600, "EUR")
    assert changed.line_discount == Money(7, "EUR")


MISMATCHES = [
    ("place", "unit_price"),
    ("place", "line_discount"),
    ("add_line", "unit_price"),
    ("add_line", "line_discount"),
    ("change_line", "unit_price"),
    ("change_line", "line_discount"),
]


@pytest.mark.parametrize(("operation", "field"), MISMATCHES)
def test_o2_order_refuses_a_line_whose_price_or_discount_is_not_in_the_orders_currency(
    operation: str,
    field: str,
    place_order: Callable[..., Order],
    placed_order: Order,
    at: Callable[[int], datetime],
    state_of: Callable[[Order], State],
) -> None:
    # Exactly ONE field is in GBP on an EUR order, so the kernel's own `money.cross_currency`
    # (raised one step later by the arithmetic) must not be what the caller sees.
    price = Money(900, "GBP" if field == "unit_price" else "EUR")
    discount = Money(10, "GBP" if field == "line_discount" else "EUR")
    before = state_of(placed_order)

    def attempt() -> None:
        if operation == "place":
            place_order(
                lines=(
                    OrderLineInput(
                        product_code="SKU-G",
                        description=None,
                        quantity=Quantity(1),
                        unit_price=price,
                        line_discount=discount,
                    ),
                )
            )
        elif operation == "add_line":
            placed_order.add_line(
                product_code="SKU-G",
                description=None,
                quantity=Quantity(1),
                unit_price=price,
                line_discount=discount,
                occurred_at=at(5),
            )
        else:
            placed_order.change_line(
                line_id=placed_order.lines[0].id,
                quantity=Quantity(1),
                unit_price=price,
                line_discount=discount,
                occurred_at=at(5),
            )

    with pytest.raises(OrderLineCurrencyMismatchError) as raised:
        attempt()
    assert raised.value.code == "order.line_currency_mismatch"
    assert raised.value.field == field
    assert raised.value.offending_currency == "GBP"
    assert state_of(placed_order) == before


def test_remove_line_and_change_line_raise_line_not_found_for_an_unknown_line_id(
    placed_order: Order,
    at: Callable[[int], datetime],
    state_of: Callable[[Order], State],
) -> None:
    unknown = UniqueId.new()
    before = state_of(placed_order)
    with pytest.raises(OrderLineNotFoundError) as removed:
        placed_order.remove_line(line_id=unknown, occurred_at=at(5))
    with pytest.raises(OrderLineNotFoundError) as changed:
        placed_order.change_line(
            line_id=unknown,
            quantity=Quantity(1),
            unit_price=Money(10, "EUR"),
            line_discount=Money(0, "EUR"),
            occurred_at=at(5),
        )
    assert removed.value.code == changed.value.code == "order.line_not_found"
    assert state_of(placed_order) == before


def test_place_keeps_the_order_reference_and_the_business_codes_it_was_given(
    place_order: Callable[..., Order],
) -> None:
    order = place_order(order_reference="ORD-000042", notes="deliver after 9")
    assert order.order_reference == OrderNumber("ORD-000042")
    assert order.status is OrderStatus.PLACED
    assert order.notes == "deliver after 9"
    assert order.cancellation_reason is None
    assert (order.retailer_code, order.company_code, order.currency) == ("RET-01", "CMP-01", "EUR")


def test_place_keeps_both_glns_the_order_date_and_the_two_creation_instants_it_was_given(
    place_order: Callable[..., Order],
    at: Callable[[int], datetime],
) -> None:
    # Pairwise-distinct: buyer GLN != supplier GLN, order_date (-60) != occurred_at (7).
    order = place_order(order_date=at(-60), occurred_at=at(7))
    assert order.buyer_gln == GLN("4012345000009")
    assert order.supplier_gln == GLN("5412345000006")
    assert order.order_date == at(-60)
    assert order.created_at == at(7)
    assert order.updated_at == at(7)
