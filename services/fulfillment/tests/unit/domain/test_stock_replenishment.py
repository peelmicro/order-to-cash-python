"""R61 (the domain half): replenishing adds on-hand units only and emits nothing."""

from collections.abc import Callable

from otc_fulfillment.domain.reservation import ReservationStatus
from otc_fulfillment.domain.stock_item import StockItem
from otc_shared_kernel import Quantity

ORDER = "ORD-000042"

BuildItem = Callable[..., StockItem]


def test_r61_increases_units_by_the_requested_quantity_leaves_reserved_units_and_every_reservation_unchanged_and_appends_no_domain_event(  # noqa: E501
    build_item: BuildItem,
) -> None:
    item = build_item(
        "PRD-A1",
        units=10,
        reserved=4,
        item_number=0xA1,
        reservations=[(0x71, ORDER, 4, ReservationStatus.RESERVED)],
    )
    reservations_before = item.reservations

    item.replenish(Quantity(37))

    assert item.units == 10 + 37
    assert item.reserved_units == 4
    assert item.available_units == 47 - 4
    assert item.reservations == reservations_before
    assert item.domain_events == ()
