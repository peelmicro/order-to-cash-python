"""R30, FS10, FS11, FS12 and the aggregate's guards (`StockItem`, `design.md` 5.1).

Every refused operation is checked for "changes nothing": `to_snapshot()` before and after.
"""

from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from otc_fulfillment.domain.errors import (
    FactAggregateMismatchError,
    InsufficientStockError,
    InvalidStockItemSnapshotError,
    ReservationTerminalError,
)
from otc_fulfillment.domain.events import RejectionReason, Shortage, StockRejected
from otc_fulfillment.domain.reservation import ReservationStatus
from otc_fulfillment.domain.snapshot import ReservationSnapshot, StockItemSnapshot
from otc_fulfillment.domain.stock_item import StockItem
from otc_shared_kernel import Quantity, UniqueId

ORDER = "ORD-000042"
OTHER_ORDER = "ORD-000077"
RETAILER = "RET-9"

Uid = Callable[[int], UniqueId]
BuildItem = Callable[..., StockItem]


def test_r30_rejects_in_full_any_operation_that_would_push_reserved_units_above_units_and_changes_no_stock_item(  # noqa: E501
    uid: Uid, build_item: BuildItem
) -> None:
    item = build_item("PRD-A1", units=10, reserved=4, item_number=0xA1)  # available: 6
    before = item.to_snapshot()

    # one more than available: refused, nothing changed
    with pytest.raises(InsufficientStockError) as refusal:
        item.reserve(
            reservation_id=uid(0x1),
            order_reference=ORDER,
            retailer_code=RETAILER,
            units=Quantity(7),
        )

    assert refusal.value.code == "stock.insufficient"
    assert (refusal.value.requested, refusal.value.available) == (7, 6)
    assert item.to_snapshot() == before
    assert item.can_reserve(7) is False

    # the boundary: exactly the available units succeed, and F1 holds with equality
    assert item.can_reserve(6) is True
    item.reserve(
        reservation_id=uid(0x2), order_reference=ORDER, retailer_code=RETAILER, units=Quantity(6)
    )
    assert (item.units, item.reserved_units, item.available_units) == (10, 10, 0)

    # and nothing at all fits now
    with pytest.raises(InsufficientStockError):
        item.reserve(
            reservation_id=uid(0x3),
            order_reference=ORDER,
            retailer_code=RETAILER,
            units=Quantity(1),
        )
    assert item.reserved_units == 10


def test_rehydrate_refuses_a_breach_of_f1_a_negative_a_non_int_and_a_foreign_reservation(
    uid: Uid,
) -> None:
    def snapshot(**changes: object) -> StockItemSnapshot:
        base: dict[str, object] = {
            "id": uid(0xA1),
            "company_code": "ACME-CO",
            "product_code": "PRD-A1",
            "units": 10,
            "reserved_units": 4,
            "low_stock_threshold": 3,
            "reservations": (),
        }
        return StockItemSnapshot(**(base | changes))  # type: ignore[arg-type]

    assert StockItem.rehydrate(snapshot()).available_units == 6
    for broken in (
        snapshot(reserved_units=11),  # F1
        snapshot(units=-1, reserved_units=0),
        snapshot(reserved_units=-1),
        snapshot(low_stock_threshold=-1),
        snapshot(units=10.0),
        snapshot(units=True),
        snapshot(
            reservations=(
                ReservationSnapshot(
                    id=uid(0x9),
                    stock_id=uid(0xB2),  # another item's reservation
                    product_code="PRD-A1",
                    order_reference=ORDER,
                    retailer_code=RETAILER,
                    units=1,
                    status=ReservationStatus.RESERVED,
                ),
            )
        ),
        snapshot(
            reservations=(
                ReservationSnapshot(
                    id=uid(0x9),
                    stock_id=uid(0xA1),
                    product_code="PRD-B2",  # right item id, another product
                    order_reference=ORDER,
                    retailer_code=RETAILER,
                    units=1,
                    status=ReservationStatus.RESERVED,
                ),
            )
        ),
        snapshot(
            reservations=(
                ReservationSnapshot(
                    id=uid(0x9),
                    stock_id=uid(0xA1),
                    product_code="PRD-A1",
                    order_reference=ORDER,
                    retailer_code=RETAILER,
                    units=0,  # a reservation of no units
                    status=ReservationStatus.RESERVED,
                ),
            )
        ),
    ):
        with pytest.raises(InvalidStockItemSnapshotError) as refusal:
            StockItem.rehydrate(broken)
        assert refusal.value.code == "stock_item.invalid_snapshot"


def test_fs10_refuses_to_release_a_consumed_reservation_and_changes_nothing(
    build_item: BuildItem,
) -> None:
    # One `reserved` and one `consumed` reservation of the SAME order on one item: the consumed one
    # is found BEFORE the reserved one is released, so nothing moves.
    item = build_item(
        "PRD-A1",
        units=10,
        reserved=3,
        item_number=0xA1,
        reservations=[
            (0x71, ORDER, 3, ReservationStatus.RESERVED),
            (0x72, ORDER, 2, ReservationStatus.CONSUMED),
        ],
    )
    before = item.to_snapshot()

    with pytest.raises(ReservationTerminalError) as refusal:
        item.release(ORDER)

    assert refusal.value.code == "reservation.terminal"
    assert item.to_snapshot() == before, "the `reserved` row must not have been released"
    assert item.reserved_units == 3


def test_fs11_consume_moves_the_orders_reservations_to_consumed_decreases_units_and_reserved_units_by_the_same_total_and_appends_no_event(  # noqa: E501
    build_item: BuildItem,
) -> None:
    item = build_item(
        "PRD-A1",
        units=20,
        reserved=3 + 4 + 5,
        item_number=0xA1,
        reservations=[
            (0x71, ORDER, 3, ReservationStatus.RESERVED),
            (0x72, ORDER, 4, ReservationStatus.RESERVED),
            (0x73, OTHER_ORDER, 5, ReservationStatus.RESERVED),  # a second order: untouched
        ],
    )

    consumed = item.consume(ORDER)

    assert [r.units for r in consumed] == [3, 4]
    assert (item.units, item.reserved_units) == (20 - 7, 12 - 7)
    statuses = {r.id: r.status for r in item.reservations}
    assert [r.status for r in consumed] == [ReservationStatus.CONSUMED] * 2
    assert list(statuses.values()) == [
        ReservationStatus.CONSUMED,
        ReservationStatus.CONSUMED,
        ReservationStatus.RESERVED,
    ]
    assert item.domain_events == (), "consume appends no domain event"


def test_fs12_rehydrates_and_keeps_reserved_units_equal_to_the_sum_of_reserved_reservations_after_reserve_release_and_consume(  # noqa: E501
    uid: Uid, build_item: BuildItem
) -> None:
    item = build_item(
        "PRD-A1",
        units=30,
        reserved=6,
        item_number=0xA1,
        reservations=[(0x71, OTHER_ORDER, 6, ReservationStatus.RESERVED)],
    )

    def reserved_sum() -> int:
        return sum(r.units for r in item.reservations if r.status is ReservationStatus.RESERVED)

    assert item.reserved_units == reserved_sum() == 6
    item.reserve(
        reservation_id=uid(0x1), order_reference=ORDER, retailer_code=RETAILER, units=Quantity(5)
    )
    item.reserve(
        reservation_id=uid(0x2), order_reference=ORDER, retailer_code=RETAILER, units=Quantity(2)
    )
    assert item.reserved_units == reserved_sum() == 13

    item.release(ORDER)
    assert item.reserved_units == reserved_sum() == 6

    item.reserve(
        reservation_id=uid(0x3), order_reference=ORDER, retailer_code=RETAILER, units=Quantity(4)
    )
    assert item.reserved_units == reserved_sum() == 10
    item.consume(ORDER)
    assert item.reserved_units == reserved_sum() == 6
    assert item.units == 30 - 4
    # a snapshot round-trips: rehydrating what `to_snapshot` returns gives the same snapshot
    assert StockItem.rehydrate(item.to_snapshot()).to_snapshot() == item.to_snapshot()


def test_record_order_fact_refuses_a_fact_of_another_aggregate(
    uid: Uid, build_item: BuildItem
) -> None:
    item = build_item("PRD-A1", units=10, item_number=0xA1)
    foreign = StockRejected(
        event_id=uid(0x5),
        aggregate_id=uid(0xB2),  # not this item
        correlation_id=uid(0xC0C0),
        causation_id=uid(0xCA05),
        occurred_at=datetime(2026, 10, 8, tzinfo=UTC),
        order_reference=ORDER,
        company_code="ACME-CO",
        retailer_code=RETAILER,
        shortages=(Shortage(product_code="PRD-A1", requested=1, available=0),),
        reason=RejectionReason.INSUFFICIENT_STOCK,
    )

    with pytest.raises(FactAggregateMismatchError) as refusal:
        item.record_order_fact(foreign)

    assert refusal.value.code == "stock.fact_aggregate_mismatch"
    assert item.domain_events == ()
