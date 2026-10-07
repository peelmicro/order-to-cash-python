"""`Order.rehydrate`: a stored order is restored, validated on every load (`design.md` section 8).

Each of the nine load checks has its OWN test, built from a fixture that corrupts exactly one thing,
so no earlier check can catch it by accident; where deleting a check lets a later step fail with a
different error (a deleted O2 check lets `Money.add` raise `money.cross_currency`), the test asserts
the CODE, so the substitute error does not satisfy it. #8 shipped two of four checks that survived
their own deletion; this file exists so that cannot happen here.
"""

import dataclasses
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import pytest

from otc_orders.domain.errors import (
    InstantNotUtcError,
    InvalidOrderSnapshotError,
    OrderMustHaveAtLeastOneLineError,
    OrderTotalMustNotBeNegativeError,
)
from otc_orders.domain.order import Order
from otc_orders.domain.snapshot import OrderLineSnapshot, OrderSnapshot
from otc_orders.domain.value_objects.cancellation_reason import CancellationReason
from otc_orders.domain.value_objects.order_status import OrderStatus
from otc_shared_kernel import DomainError, Money, Quantity, UniqueId

Snapshot = Callable[..., OrderSnapshot]

SNAPSHOT_FIELDS = {
    "id",
    "order_reference",
    "order_date",
    "retailer_code",
    "buyer_gln",
    "company_code",
    "supplier_gln",
    "currency",
    "status",
    "cancellation_reason",
    "notes",
    "lines",
    "created_at",
    "updated_at",
}


def test_rehydrate_restores_a_terminal_order_without_walking_the_state_machine_and_without_raising_any_event(  # noqa: E501
    make_snapshot: Snapshot, at: Callable[[int], datetime]
) -> None:
    completed = Order.rehydrate(make_snapshot(status=OrderStatus.COMPLETED))
    assert completed.status is OrderStatus.COMPLETED
    assert completed.domain_events == ()

    cancelled = Order.rehydrate(
        make_snapshot(
            status=OrderStatus.CANCELLED,
            cancellation_reason=CancellationReason.CREDIT_REJECTED,
        )
    )
    assert cancelled.status is OrderStatus.CANCELLED
    assert cancelled.cancellation_reason is CancellationReason.CREDIT_REJECTED
    assert cancelled.domain_events == ()

    placed = Order.rehydrate(make_snapshot(status=OrderStatus.PLACED))
    placed.mark_stock_reserved(occurred_at=at(10))
    assert placed.status is OrderStatus.STOCK_RESERVED
    assert placed.domain_events == ()


def test_rehydrate_derives_the_three_totals_from_the_lines_and_the_snapshot_has_no_totals_field(
    make_snapshot: Snapshot,
) -> None:
    restored = Order.rehydrate(make_snapshot())
    assert (
        restored.initial_amount,
        restored.initial_discount,
        restored.total_amount,
    ) == (Money(8465, "EUR"), Money(350, "EUR"), Money(8115, "EUR"))
    assert {field.name for field in dataclasses.fields(OrderSnapshot)} == SNAPSHOT_FIELDS
    assert not any("amount" in name or "total" in name for name in SNAPSHOT_FIELDS)


def test_rehydrate_refuses_a_status_that_is_not_an_order_status_member(
    make_snapshot: Snapshot,
) -> None:
    with pytest.raises(InvalidOrderSnapshotError) as raised:
        Order.rehydrate(make_snapshot(status="placed"))
    assert raised.value.code == "order.snapshot_invalid"


def test_rehydrate_refuses_a_cancellation_reason_that_is_not_a_member(
    make_snapshot: Snapshot,
) -> None:
    with pytest.raises(InvalidOrderSnapshotError) as raised:
        Order.rehydrate(
            make_snapshot(status=OrderStatus.CANCELLED, cancellation_reason="operator_cancelled")
        )
    assert raised.value.code == "order.snapshot_invalid"
    assert "CancellationReason" in raised.value.message


def test_rehydrate_refuses_cancelled_without_a_reason(make_snapshot: Snapshot) -> None:
    with pytest.raises(InvalidOrderSnapshotError) as raised:
        Order.rehydrate(make_snapshot(status=OrderStatus.CANCELLED, cancellation_reason=None))
    assert raised.value.code == "order.snapshot_invalid"
    assert raised.value.code != "order.cancellation_reason_not_applicable"  # #8 A3


def test_rehydrate_refuses_a_reason_on_an_order_that_is_not_cancelled(
    make_snapshot: Snapshot,
) -> None:
    with pytest.raises(InvalidOrderSnapshotError) as raised:
        Order.rehydrate(
            make_snapshot(
                status=OrderStatus.CONFIRMED,
                cancellation_reason=CancellationReason.OPERATOR_CANCELLED,
            )
        )
    assert raised.value.code == "order.snapshot_invalid"


def test_rehydrate_refuses_an_empty_lines_collection(make_snapshot: Snapshot) -> None:
    with pytest.raises(OrderMustHaveAtLeastOneLineError) as raised:
        Order.rehydrate(make_snapshot(lines=()))
    assert raised.value.code == "order.must_have_at_least_one_line"


NAIVE = datetime(2026, 10, 1, 9, 0, 0)
PLUS_ONE = datetime(2026, 10, 1, 9, 0, 0, tzinfo=timezone(timedelta(hours=1)))


@pytest.mark.parametrize("field", ["order_date", "created_at", "updated_at"])
@pytest.mark.parametrize("bad", [NAIVE, PLUS_ONE], ids=["naive", "plus-one-hour"])
def test_rehydrate_refuses_a_naive_or_non_utc_instant(
    field: str, bad: datetime, make_snapshot: Snapshot
) -> None:
    with pytest.raises(InstantNotUtcError) as raised:
        Order.rehydrate(make_snapshot(**{field: bad}))
    assert raised.value.code == "order.instant_not_utc"
    assert raised.value.field == field


def _with_line(snapshot: OrderSnapshot, *, price: Money, discount: Money) -> OrderSnapshot:
    corrupted = dataclasses.replace(snapshot.lines[1], unit_price=price, line_discount=discount)
    return dataclasses.replace(snapshot, lines=(snapshot.lines[0], corrupted))


def test_rehydrate_refuses_a_line_whose_unit_price_is_not_in_the_orders_currency(
    make_snapshot: Snapshot,
) -> None:
    # Only one line's unit price is GBP; its discount and the other line are EUR.
    snapshot = _with_line(make_snapshot(), price=Money(1234, "GBP"), discount=Money(100, "EUR"))
    with pytest.raises(DomainError) as raised:
        Order.rehydrate(snapshot)
    # The CODE, not just "something raised": a deleted check lets `Money.add` raise
    # `money.cross_currency` one step later, which must not satisfy this test.
    assert raised.value.code == "order.line_currency_mismatch"


def test_rehydrate_refuses_a_line_whose_line_discount_is_not_in_the_orders_currency(
    make_snapshot: Snapshot,
) -> None:
    # The case #8's single O2 load test could not see: only the discount is GBP.
    snapshot = _with_line(make_snapshot(), price=Money(1234, "EUR"), discount=Money(100, "GBP"))
    with pytest.raises(DomainError) as raised:
        Order.rehydrate(snapshot)
    # The CODE, not just "something raised": a deleted check lets `Money.add` raise
    # `money.cross_currency` one step later, which must not satisfy this test.
    assert raised.value.code == "order.line_currency_mismatch"


def test_rehydrate_refuses_lines_whose_derived_total_is_negative(make_snapshot: Snapshot) -> None:
    snapshot = _with_line(make_snapshot(), price=Money(100, "EUR"), discount=Money(90000, "EUR"))
    with pytest.raises(OrderTotalMustNotBeNegativeError) as raised:
        Order.rehydrate(snapshot)
    assert raised.value.code == "order.total_must_not_be_negative"


def test_rehydrate_orders_lines_by_ascending_line_id(make_snapshot: Snapshot) -> None:
    # Supplied in descending order. As decimal strings the three sort B < C < A, as integers
    # A < B < C, so a sort on any text form of the id would not give the order asserted below.
    low = UniqueId(uuid.UUID(int=9 * 10**20))
    middle = UniqueId(uuid.UUID(int=10**21))
    high = UniqueId(uuid.UUID(int=2 * 10**21))
    assert sorted(str(i.value.int) for i in (low, middle, high)) != [
        str(i.value.int) for i in (low, middle, high)
    ]

    def line(line_id: UniqueId, code: str) -> OrderLineSnapshot:
        return OrderLineSnapshot(
            id=line_id,
            product_code=code,
            description=None,
            quantity=Quantity(1),
            unit_price=Money(100, "EUR"),
            line_discount=Money(0, "EUR"),
        )

    supplied = (line(high, "H"), line(low, "L"), line(middle, "M"))
    restored = Order.rehydrate(make_snapshot(lines=supplied))
    assert [item.id for item in restored.lines] == [low, middle, high]
    assert [item.product_code for item in restored.lines] == ["L", "M", "H"]
    assert [item.id.value.int for item in restored.lines] == sorted(
        item.id.value.int for item in restored.lines
    )


def test_rehydrate_restores_every_field_of_the_snapshot_with_a_non_none_note(
    make_snapshot: Snapshot, at: Callable[[int], datetime]
) -> None:
    # Pairwise distinct: GLNs, retailer vs company code, order_date (-60), created_at (0),
    # updated_at (5); `notes` is non-None so a dropped note is visible.
    snapshot = make_snapshot(notes="leave at dock 4")
    restored = Order.rehydrate(snapshot)
    assert restored.id == snapshot.id
    assert restored.order_reference == snapshot.order_reference
    assert restored.order_date == at(-60)
    assert restored.retailer_code == "RET-01"
    assert restored.buyer_gln == snapshot.buyer_gln
    assert restored.company_code == "CMP-01"
    assert restored.supplier_gln == snapshot.supplier_gln
    assert restored.buyer_gln != restored.supplier_gln
    assert restored.currency == "EUR"
    assert restored.notes == "leave at dock 4"
    assert restored.created_at == at(0)
    assert restored.updated_at == at(5)
    by_id = {stored.id: stored for stored in snapshot.lines}
    assert len(restored.lines) == len(by_id) == 2
    for line in restored.lines:
        stored = by_id[line.id]
        assert (
            line.product_code,
            line.description,
            line.quantity,
            line.unit_price,
            line.line_discount,
        ) == (
            stored.product_code,
            stored.description,
            stored.quantity,
            stored.unit_price,
            stored.line_discount,
        )
