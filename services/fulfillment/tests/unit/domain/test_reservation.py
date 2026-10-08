"""R32, R33, R35, FS8, FS13, FS24: the reservation state machine and `reserve_order`.

Fixtures: product codes none of which contains another (`PRD-A1`, `PRD-B2`, `PRD-C3`); the
correlation id, the causation id and every item id pairwise distinct; `company_code` differs from
`retailer_code`. Builders live in `conftest.py`.
"""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime

import pytest

from otc_fulfillment.domain.errors import ReservationTerminalError, UnknownReservationStatusError
from otc_fulfillment.domain.events import (
    RejectionReason,
    ReleaseReason,
    ReservationRef,
    Shortage,
    StockRejected,
    StockReleased,
    StockReserved,
)
from otc_fulfillment.domain.order_stock_reservation import (
    NoCarrier,
    Rejected,
    ReleaseOrderInput,
    Reserved,
    ReserveLine,
    ReserveOrderInput,
    StockContext,
    release_order,
    reserve_order,
)
from otc_fulfillment.domain.reservation import (
    Reservation,
    ReservationStatus,
    parse_reservation_status,
)
from otc_fulfillment.domain.stock_item import StockItem
from otc_shared_kernel import Quantity, UniqueId

COMPANY = "ACME-CO"
RETAILER = "RET-9"
ORDER = "ORD-000042"
NOW = datetime(2026, 10, 8, 9, 0, 0, tzinfo=UTC)

Uid = Callable[[int], UniqueId]
BuildItem = Callable[..., StockItem]
IdSource = Callable[[Sequence[UniqueId]], Callable[[], UniqueId]]


def request(uid: Uid, *lines: tuple[str, int]) -> ReserveOrderInput:
    return ReserveOrderInput(
        order_reference=ORDER,
        company_code=COMPANY,
        retailer_code=RETAILER,
        lines=tuple(ReserveLine(product_code=code, units=Quantity(n)) for code, n in lines),
        correlation_id=uid(0xC0C0),
    )


def context(uid: Uid) -> StockContext:
    return StockContext(occurred_at=NOW, causation_id=uid(0xCA05))


def counting_ids(uid: Uid, start: int = 0x900) -> Callable[[], UniqueId]:
    counter = iter(range(start, start + 100))
    return lambda: uid(next(counter))


# ------------------------------------------------------------------------------------------ R35


def _reservation(uid: Uid, status: ReservationStatus) -> Reservation:
    return Reservation.rehydrate(
        reservation_id=uid(0x77),
        order_reference=ORDER,
        retailer_code=RETAILER,
        units=4,
        status=status,
    )


@pytest.mark.parametrize("terminal", [ReservationStatus.RELEASED, ReservationStatus.CONSUMED])
@pytest.mark.parametrize("operation", ["release", "consume"])
def test_r35_refuses_every_transition_out_of_released_and_out_of_consumed_and_changes_nothing(
    uid: Uid, terminal: ReservationStatus, operation: str
) -> None:
    reservation = _reservation(uid, terminal)
    before = reservation.view()

    with pytest.raises(ReservationTerminalError) as refusal:
        reservation.release() if operation == "release" else reservation.consume()

    assert refusal.value.code == "reservation.terminal"
    assert reservation.view() == before, "a refused transition must change nothing"
    assert reservation.status is terminal


def test_r35_allows_exactly_reserved_to_released_and_reserved_to_consumed(uid: Uid) -> None:
    released = _reservation(uid, ReservationStatus.RESERVED)
    consumed = _reservation(uid, ReservationStatus.RESERVED)

    released.release()
    consumed.consume()

    assert released.status is ReservationStatus.RELEASED
    assert consumed.status is ReservationStatus.CONSUMED


def test_parse_reservation_status_is_exact_and_refuses_everything_outside_the_closed_set() -> None:
    assert parse_reservation_status("reserved") is ReservationStatus.RESERVED
    assert parse_reservation_status("released") is ReservationStatus.RELEASED
    assert parse_reservation_status("consumed") is ReservationStatus.CONSUMED
    for refused in ("Reserved", " reserved", "reserved ", "cancelled", "", 1, None, b"reserved"):
        with pytest.raises(UnknownReservationStatusError):
            parse_reservation_status(refused)


# ------------------------------------------------------------------------------------------ R32


def test_r32_creates_one_reservation_per_line_increases_reserved_units_and_emits_exactly_one_stock_reserved_v1(  # noqa: E501
    uid: Uid, build_item: BuildItem
) -> None:
    item_a = build_item("PRD-A1", units=10, reserved=1, item_number=0xA1)
    item_b = build_item("PRD-B2", units=20, reserved=2, item_number=0xB2)
    ids = [uid(0x501), uid(0x502), uid(0x503), uid(0x5E)]
    supplied = iter(ids)

    outcome = reserve_order(
        {"PRD-A1": item_a, "PRD-B2": item_b},
        request(uid, ("PRD-A1", 3), ("PRD-B2", 5), ("PRD-A1", 2)),
        context(uid),
        lambda: next(supplied),
    )

    # A repeated product on two lines yields two reservations: three in all, refs in line order.
    assert outcome == Reserved(
        reservations=(
            ReservationRef(reservation_id=uid(0x501), product_code="PRD-A1", units=3),
            ReservationRef(reservation_id=uid(0x502), product_code="PRD-B2", units=5),
            ReservationRef(reservation_id=uid(0x503), product_code="PRD-A1", units=2),
        )
    )
    assert (item_a.reserved_units, item_a.units) == (1 + 3 + 2, 10)
    assert (item_b.reserved_units, item_b.units) == (2 + 5, 20)
    assert [r.status for r in item_a.reservations] == [ReservationStatus.RESERVED] * 2
    assert [r.units for r in item_a.reservations] == [3, 2]
    # Exactly ONE fact, on the carrier (the first line's item); the other item carries none.
    [fact] = item_a.domain_events
    assert item_b.domain_events == ()
    assert isinstance(fact, StockReserved)
    assert fact.EVENT_TYPE == "stock.reserved.v1"
    assert fact.event_id == uid(0x5E)
    assert fact.aggregate_id == uid(0xA1)
    assert fact.correlation_id == uid(0xC0C0)
    assert fact.causation_id == uid(0xCA05)
    assert fact.occurred_at == NOW
    assert (fact.order_reference, fact.company_code, fact.retailer_code) == (
        ORDER,
        COMPANY,
        RETAILER,
    )
    assert fact.reservations == outcome.reservations


# ------------------------------------------------------------------------------------------ R33


def test_r33_creates_no_reservation_at_all_and_emits_stock_rejected_v1_naming_requested_and_available_units_when_one_line_is_short(  # noqa: E501
    uid: Uid, build_item: BuildItem
) -> None:
    item_a = build_item("PRD-A1", units=10, reserved=1, item_number=0xA1)
    item_b = build_item("PRD-B2", units=20, reserved=2, item_number=0xB2)
    item_c = build_item("PRD-C3", units=8, reserved=3, item_number=0xC3)  # available: 5
    before = [i.to_snapshot() for i in (item_a, item_b, item_c)]

    # The THIRD line is short, and PRD-C3 is requested twice: the shortage sums its lines (4 + 3).
    outcome = reserve_order(
        {"PRD-A1": item_a, "PRD-B2": item_b, "PRD-C3": item_c},
        request(uid, ("PRD-A1", 2), ("PRD-B2", 4), ("PRD-C3", 4), ("PRD-C3", 3)),
        context(uid),
        counting_ids(uid),
    )

    assert outcome == Rejected(
        shortages=(Shortage(product_code="PRD-C3", requested=7, available=5),),
        reason=RejectionReason.INSUFFICIENT_STOCK,
    )
    # Zero reservations on ALL three items, counters unchanged (F3).
    assert [i.to_snapshot() for i in (item_a, item_b, item_c)] == before
    [fact] = item_a.domain_events
    assert item_b.domain_events == ()
    assert item_c.domain_events == ()
    assert isinstance(fact, StockRejected)
    assert fact.EVENT_TYPE == "stock.rejected.v1"
    assert fact.shortages == (Shortage(product_code="PRD-C3", requested=7, available=5),), (
        "only the short product is listed, with the summed requested units"
    )
    assert fact.reason is RejectionReason.INSUFFICIENT_STOCK
    assert (fact.order_reference, fact.company_code, fact.retailer_code) == (
        ORDER,
        COMPANY,
        RETAILER,
    )
    assert fact.aggregate_id == uid(0xA1)
    assert fact.correlation_id == uid(0xC0C0)
    assert fact.causation_id == uid(0xCA05)


def test_r33_lists_every_short_product_in_first_appearance_order_and_only_those(
    uid: Uid, build_item: BuildItem
) -> None:
    item_a = build_item("PRD-A1", units=10, item_number=0xA1)  # available 10: requested 2, fine
    item_b = build_item("PRD-B2", units=4, item_number=0xB2)  # requested 6: short by 2
    item_c = build_item("PRD-C3", units=1, item_number=0xC3)  # requested 9: short

    outcome = reserve_order(
        {"PRD-A1": item_a, "PRD-B2": item_b, "PRD-C3": item_c},
        request(uid, ("PRD-C3", 9), ("PRD-A1", 2), ("PRD-B2", 6)),
        context(uid),
        counting_ids(uid),
    )

    assert isinstance(outcome, Rejected)
    assert outcome.shortages == (
        Shortage(product_code="PRD-C3", requested=9, available=1),
        Shortage(product_code="PRD-B2", requested=6, available=4),
    )


# ------------------------------------------------------------------------------------------ FS8


def test_fs8_rejects_the_whole_order_with_reason_unknown_product_and_available_zero_when_any_line_names_an_unstocked_product(  # noqa: E501
    uid: Uid, build_item: BuildItem
) -> None:
    item_a = build_item("PRD-A1", units=10, item_number=0xA1)
    before = item_a.to_snapshot()

    outcome = reserve_order(
        {"PRD-A1": item_a},
        request(uid, ("PRD-A1", 2), ("PRD-Z9", 5)),
        context(uid),
        counting_ids(uid),
    )

    assert outcome == Rejected(
        shortages=(Shortage(product_code="PRD-Z9", requested=5, available=0),),
        reason=RejectionReason.UNKNOWN_PRODUCT,
    )
    assert item_a.to_snapshot() == before, "the satisfiable line is not reserved either"
    [fact] = item_a.domain_events
    assert isinstance(fact, StockRejected)
    assert fact.reason is RejectionReason.UNKNOWN_PRODUCT

    # The mixed case: one unknown AND one short-known product. `unknown_product` wins.
    short = build_item("PRD-B2", units=1, item_number=0xB2)
    mixed = reserve_order(
        {"PRD-B2": short},
        request(uid, ("PRD-B2", 9), ("PRD-Z9", 5)),
        context(uid),
        counting_ids(uid),
    )
    assert isinstance(mixed, Rejected)
    assert mixed.reason is RejectionReason.UNKNOWN_PRODUCT
    assert mixed.shortages == (
        Shortage(product_code="PRD-B2", requested=9, available=1),
        Shortage(product_code="PRD-Z9", requested=5, available=0),
    )


def test_a_known_short_product_alone_is_insufficient_stock_not_unknown_product(
    uid: Uid, build_item: BuildItem
) -> None:
    short = build_item("PRD-B2", units=1, item_number=0xB2)

    outcome = reserve_order(
        {"PRD-B2": short}, request(uid, ("PRD-B2", 9)), context(uid), counting_ids(uid)
    )

    assert isinstance(outcome, Rejected)
    assert outcome.reason is RejectionReason.INSUFFICIENT_STOCK


# ----------------------------------------------------------------------------------------- FS13


def test_fs13_stamps_the_first_known_lines_item_on_reserved_and_rejected_and_the_first_released_reservations_item_on_released(  # noqa: E501
    uid: Uid, build_item: BuildItem
) -> None:
    # Reserved: the first LINE's item (B2), not the first item in any other order (A1).
    item_a = build_item("PRD-A1", units=10, item_number=0xA1)
    item_b = build_item("PRD-B2", units=10, item_number=0xB2)
    reserve_order(
        {"PRD-A1": item_a, "PRD-B2": item_b},
        request(uid, ("PRD-B2", 2), ("PRD-A1", 1)),
        context(uid),
        counting_ids(uid),
    )
    [reserved] = item_b.domain_events
    assert isinstance(reserved, StockReserved)
    assert reserved.aggregate_id == uid(0xB2)
    assert item_a.domain_events == ()

    # Rejected: the FIRST line is unknown, the second line's item is the carrier, not the third's.
    item_a = build_item("PRD-A1", units=10, item_number=0xA1)
    item_b = build_item("PRD-B2", units=10, item_number=0xB2)
    reserve_order(
        {"PRD-A1": item_a, "PRD-B2": item_b},
        request(uid, ("PRD-Z9", 1), ("PRD-B2", 2), ("PRD-A1", 1)),
        context(uid),
        counting_ids(uid),
    )
    [rejected] = item_b.domain_events
    assert isinstance(rejected, StockRejected)
    assert rejected.aggregate_id == uid(0xB2)
    assert item_a.domain_events == ()

    # Released: the item of the first RELEASED reservation, in the order the items are given. The
    # first item holds nothing for the order, so it is not the carrier.
    empty = build_item("PRD-A1", units=10, item_number=0xA1)
    second = build_item(
        "PRD-B2",
        units=10,
        reserved=2,
        item_number=0xB2,
        reservations=[(0x71, ORDER, 2, ReservationStatus.RESERVED)],
    )
    third = build_item(
        "PRD-C3",
        units=10,
        reserved=3,
        item_number=0xC3,
        reservations=[(0x72, ORDER, 3, ReservationStatus.RESERVED)],
    )
    release_order(
        [empty, second, third],
        ReleaseOrderInput(
            order_reference=ORDER,
            reason=ReleaseReason.ORDER_CANCELLED,
            correlation_id=uid(0xC0C0),
        ),
        context(uid),
        counting_ids(uid),
    )
    [released] = second.domain_events
    assert isinstance(released, StockReleased)
    assert released.aggregate_id == uid(0xB2)
    assert empty.domain_events == ()
    assert third.domain_events == ()


def test_no_known_line_is_no_carrier(uid: Uid, build_item: BuildItem) -> None:
    item_a = build_item("PRD-A1", units=10, item_number=0xA1)
    before = item_a.to_snapshot()

    outcome = reserve_order(
        {"PRD-A1": item_a},
        request(uid, ("PRD-Z9", 1), ("PRD-Y8", 2)),
        context(uid),
        counting_ids(uid),
    )

    assert outcome == NoCarrier()
    assert item_a.to_snapshot() == before
    assert item_a.domain_events == ()


# ----------------------------------------------------------------------------------------- FS24


def _supplied(uid: Uid, *numbers: int) -> tuple[list[UniqueId], Callable[[], UniqueId]]:
    ids = [uid(n) for n in numbers]
    queue = list(ids)

    def new_id() -> UniqueId:
        assert queue, "the domain asked for more identifiers than the test supplied"
        return queue.pop(0)

    return ids, new_id


def test_fs24_every_reservation_id_and_fact_event_id_is_the_one_the_id_source_supplied(
    uid: Uid, build_item: BuildItem
) -> None:
    # Site 1 and 2: each reservation id, then the reserved fact's event id, by EQUALITY with the
    # supplied value at its position.
    item_a = build_item("PRD-A1", units=10, item_number=0xA1)
    item_b = build_item("PRD-B2", units=10, item_number=0xB2)
    ids, new_id = _supplied(uid, 0x6001, 0x6002, 0x6003)
    reserve_order(
        {"PRD-A1": item_a, "PRD-B2": item_b},
        request(uid, ("PRD-A1", 1), ("PRD-B2", 2)),
        context(uid),
        new_id,
    )
    reserved_ids = [r.id for r in (*item_a.reservations, *item_b.reservations)]
    assert reserved_ids == [ids[0], ids[1]], "a reservation id was not the supplied one"
    [reserved_fact] = item_a.domain_events
    assert isinstance(reserved_fact, StockReserved)
    assert reserved_fact.event_id == ids[2], "the reserved fact's event id was not the supplied one"

    # Site 3: the rejected fact's event id.
    short = build_item("PRD-C3", units=1, item_number=0xC3)
    ids, new_id = _supplied(uid, 0x6101)
    reserve_order({"PRD-C3": short}, request(uid, ("PRD-C3", 5)), context(uid), new_id)
    [rejected_fact] = short.domain_events
    assert isinstance(rejected_fact, StockRejected)
    assert rejected_fact.event_id == ids[0], "the rejected fact's event id was not the supplied one"

    # Site 4: the released fact's event id.
    held = build_item(
        "PRD-A1",
        units=10,
        reserved=2,
        item_number=0xA1,
        reservations=[(0x71, ORDER, 2, ReservationStatus.RESERVED)],
    )
    ids, new_id = _supplied(uid, 0x6201)
    release_order(
        [held],
        ReleaseOrderInput(
            order_reference=ORDER,
            reason=ReleaseReason.CREDIT_REJECTED,
            correlation_id=uid(0xC0C0),
        ),
        context(uid),
        new_id,
    )
    [released_fact] = held.domain_events
    assert isinstance(released_fact, StockReleased)
    assert released_fact.event_id == ids[0], "the released fact's event id was not the supplied one"
