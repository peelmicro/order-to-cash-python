"""R34 and F5: `release_order` (the domain half; the integration half is feature 17's H7)."""

from collections.abc import Callable
from datetime import UTC, datetime

from otc_fulfillment.domain.events import ReleaseReason, ReservationRef, StockReleased
from otc_fulfillment.domain.order_stock_reservation import (
    AlreadyReleased,
    Released,
    ReleaseOrderInput,
    StockContext,
    release_order,
)
from otc_fulfillment.domain.reservation import ReservationStatus
from otc_fulfillment.domain.stock_item import StockItem
from otc_shared_kernel import UniqueId

COMPANY = "ACME-CO"
RETAILER = "RET-9"
ORDER = "ORD-000042"
NOW = datetime(2026, 10, 8, 9, 0, 0, tzinfo=UTC)

Uid = Callable[[int], UniqueId]
BuildItem = Callable[..., StockItem]


def release_request(uid: Uid, reason: ReleaseReason) -> ReleaseOrderInput:
    return ReleaseOrderInput(order_reference=ORDER, reason=reason, correlation_id=uid(0xC0C0))


def test_r34_releases_the_reservations_decreases_reserved_units_and_emits_exactly_one_stock_released_v1(  # noqa: E501
    uid: Uid, build_item: BuildItem
) -> None:
    item_a = build_item(
        "PRD-A1",
        units=10,
        reserved=3 + 1,
        item_number=0xA1,
        reservations=[(0x71, ORDER, 3, ReservationStatus.RESERVED)],
    )
    item_b = build_item(
        "PRD-B2",
        units=20,
        reserved=5 + 2,
        item_number=0xB2,
        reservations=[(0x72, ORDER, 5, ReservationStatus.RESERVED)],
    )
    # the `reason` is the input's, not a constant: `order_cancelled` here, never the other value
    outcome = release_order(
        [item_a, item_b],
        release_request(uid, ReleaseReason.ORDER_CANCELLED),
        StockContext(occurred_at=NOW, causation_id=uid(0xCA05)),
        lambda: uid(0x5E),
    )

    refs = (
        ReservationRef(reservation_id=uid(0x71), product_code="PRD-A1", units=3),
        ReservationRef(reservation_id=uid(0x72), product_code="PRD-B2", units=5),
    )
    assert outcome == Released(released=refs)
    assert (item_a.reserved_units, item_b.reserved_units) == (1, 2)
    assert [r.status for r in (*item_a.reservations, *item_b.reservations)] == [
        ReservationStatus.RELEASED,
        ReservationStatus.RELEASED,
    ]
    [fact] = item_a.domain_events
    assert item_b.domain_events == ()
    assert isinstance(fact, StockReleased)
    assert fact.EVENT_TYPE == "stock.released.v1"
    assert fact.event_id == uid(0x5E)
    assert fact.aggregate_id == uid(0xA1)
    assert fact.correlation_id == uid(0xC0C0)
    assert fact.causation_id == uid(0xCA05)
    assert fact.occurred_at == NOW
    assert fact.released == refs, "`released` lists both reservations"
    assert fact.reason is ReleaseReason.ORDER_CANCELLED
    assert (fact.order_reference, fact.company_code, fact.retailer_code) == (
        ORDER,
        COMPANY,
        RETAILER,
    )


def test_f5_releasing_an_order_whose_reservations_are_all_released_changes_nothing_and_emits_nothing(  # noqa: E501
    uid: Uid, build_item: BuildItem
) -> None:
    item = build_item(
        "PRD-A1",
        units=10,
        reserved=2,
        item_number=0xA1,
        reservations=[
            (0x71, ORDER, 3, ReservationStatus.RELEASED),
            (0x72, ORDER, 4, ReservationStatus.RELEASED),
        ],
    )
    before = item.to_snapshot()

    outcome = release_order(
        [item],
        release_request(uid, ReleaseReason.CREDIT_REJECTED),
        StockContext(occurred_at=NOW, causation_id=uid(0xCA05)),
        lambda: uid(0x5E),
    )

    assert outcome == AlreadyReleased()
    assert item.to_snapshot() == before
    assert item.domain_events == ()
