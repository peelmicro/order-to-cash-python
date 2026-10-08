"""R36, F6, F7 and the id provenance of `despatch_order` / `DespatchAdvice.create` (pure).

Every identifier the operation mints is SUPPLIED by the test through `id_source`, in the order the
module documents (advice id, one line id per consumed reservation in consumption order, the fact's
event id), and every assertion is EQUALITY with the supplied value (#8 id 49: `assert x != y` or a
type check proves non-collision, never provenance). The three mint sites of `order_despatch.py`
(advice, line, event) are each guarded by their own test.
"""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime

import pytest

from otc_fulfillment.domain.despatch_advice import DespatchAdvice, DespatchLine
from otc_fulfillment.domain.errors import EmptyDespatchLinesError
from otc_fulfillment.domain.events import DespatchedLine, OrderDespatched
from otc_fulfillment.domain.order_despatch import (
    Despatched,
    DespatchOrderInput,
    NothingToDespatch,
    despatch_order,
)
from otc_fulfillment.domain.order_stock_reservation import StockContext
from otc_fulfillment.domain.reservation import ReservationStatus
from otc_fulfillment.domain.stock_item import StockItem
from otc_shared_kernel import DespatchReference, Quantity, UniqueId

COMPANY = "ACME-CO"
RETAILER = "RET-9"
ORDER = "ORD-000042"
OTHER_ORDER = "ORD-000077"
NOW = datetime(2026, 10, 8, 9, 0, 0, 123000, tzinfo=UTC)
REFERENCE = DespatchReference("DES-000031")

Uid = Callable[[int], UniqueId]
BuildItem = Callable[..., StockItem]
IdSource = Callable[[Sequence[UniqueId]], Callable[[], UniqueId]]

RESERVED = ReservationStatus.RESERVED


def request(uid: Uid) -> DespatchOrderInput:
    return DespatchOrderInput(order_reference=ORDER, correlation_id=uid(0xC0C0))


def context(uid: Uid) -> StockContext:
    return StockContext(occurred_at=NOW, causation_id=uid(0xCA05))


def two_items(build_item: BuildItem) -> tuple[StockItem, StockItem]:
    item_a = build_item(
        "PRD-A1",
        units=10,
        reserved=3 + 1,
        item_number=0xA1,
        reservations=[(0x71, ORDER, 3, RESERVED), (0x7F, OTHER_ORDER, 1, RESERVED)],
    )
    item_b = build_item(
        "PRD-B2",
        units=20,
        reserved=5 + 2,
        item_number=0xB2,
        reservations=[(0x72, ORDER, 5, RESERVED), (0x7E, OTHER_ORDER, 2, RESERVED)],
    )
    return item_a, item_b


def test_r36_consumes_every_reserved_reservation_of_the_order_lowers_both_counters_and_creates_one_advice_with_one_fact(  # noqa: E501
    uid: Uid, build_item: BuildItem, id_source: IdSource
) -> None:
    item_a, item_b = two_items(build_item)
    new_id = id_source([uid(0xAD), uid(0x11), uid(0x12), uid(0xE5)])

    outcome = despatch_order([item_a, item_b], request(uid), REFERENCE, context(uid), new_id)

    assert isinstance(outcome, Despatched)
    # the order's reservations are `consumed`; ANOTHER order's reservation on the same item is not
    assert [(r.id, r.status) for r in item_a.reservations] == [
        (uid(0x71), ReservationStatus.CONSUMED),
        (uid(0x7F), RESERVED),
    ]
    assert [(r.id, r.status) for r in item_b.reservations] == [
        (uid(0x72), ReservationStatus.CONSUMED),
        (uid(0x7E), RESERVED),
    ]
    # BOTH counters fall by the consumed units: on-hand 10 -> 7 and 20 -> 15, reserved 4 -> 1 and
    # 7 -> 2 (what is left is the other order's)
    assert (item_a.units, item_a.reserved_units) == (7, 1)
    assert (item_b.units, item_b.reserved_units) == (15, 2)
    # exactly one fact on the whole, and it is the advice's, never a stock item's
    assert item_a.domain_events == ()
    assert item_b.domain_events == ()
    [fact] = outcome.advice.domain_events
    assert isinstance(fact, OrderDespatched)
    assert fact.EVENT_TYPE == "order.despatched.v1"


def test_f7_every_line_traces_one_to_one_to_a_consumed_reservation_of_the_order_with_its_units(
    uid: Uid, build_item: BuildItem, id_source: IdSource
) -> None:
    # a repeated product: two reservations of PRD-A1 for the order, 3 and 4 units
    item_a = build_item(
        "PRD-A1",
        units=20,
        reserved=7,
        item_number=0xA1,
        reservations=[(0x71, ORDER, 3, RESERVED), (0x72, ORDER, 4, RESERVED)],
    )
    item_b = build_item(
        "PRD-B2",
        units=20,
        reserved=5,
        item_number=0xB2,
        reservations=[(0x73, ORDER, 5, RESERVED)],
    )
    new_id = id_source([uid(0xAD), uid(0x11), uid(0x12), uid(0x13), uid(0xE5)])

    outcome = despatch_order([item_a, item_b], request(uid), REFERENCE, context(uid), new_id)

    assert isinstance(outcome, Despatched)
    # one line per consumed reservation, never merged: units 3 and 4 stay two lines
    assert [(ln.product_code, ln.units.value) for ln in outcome.advice.lines] == [
        ("PRD-A1", 3),
        ("PRD-A1", 4),
        ("PRD-B2", 5),
    ]
    consumed = [
        (item.product_code, r.units)
        for item in (item_a, item_b)
        for r in item.reservations
        if r.status is ReservationStatus.CONSUMED
    ]
    assert consumed == [("PRD-A1", 3), ("PRD-A1", 4), ("PRD-B2", 5)], "the lines are these, 1:1"
    # the fact carries the same lines, the despatched units being the reserved ones
    [fact] = outcome.advice.domain_events
    assert isinstance(fact, OrderDespatched)
    assert fact.lines == (
        DespatchedLine(product_code="PRD-A1", units=3),
        DespatchedLine(product_code="PRD-A1", units=4),
        DespatchedLine(product_code="PRD-B2", units=5),
    )


def test_r36_the_fact_carries_the_requests_ids_the_clock_instant_the_reference_and_the_parties(
    uid: Uid, build_item: BuildItem, id_source: IdSource
) -> None:
    item_a, item_b = two_items(build_item)
    new_id = id_source([uid(0xAD), uid(0x11), uid(0x12), uid(0xE5)])

    outcome = despatch_order([item_a, item_b], request(uid), REFERENCE, context(uid), new_id)

    assert isinstance(outcome, Despatched)
    advice = outcome.advice
    [fact] = advice.domain_events
    assert isinstance(fact, OrderDespatched)
    assert fact.correlation_id == uid(0xC0C0), "the order id the command carried"
    assert fact.causation_id == uid(0xCA05), "the request id the command carried"
    assert fact.occurred_at == NOW
    assert fact.despatch_date == NOW
    assert advice.despatch_date == NOW
    assert fact.despatch_reference == REFERENCE
    assert advice.despatch_reference == REFERENCE
    assert (fact.order_reference, advice.order_reference) == (ORDER, ORDER)
    assert (fact.company_code, advice.company_code) == (COMPANY, COMPANY)
    assert (fact.retailer_code, advice.retailer_code) == (RETAILER, RETAILER)


def test_fs24_the_advice_id_is_the_first_supplied_id_and_is_the_facts_aggregate_id(
    uid: Uid, build_item: BuildItem, id_source: IdSource
) -> None:
    item_a, item_b = two_items(build_item)
    new_id = id_source([uid(0xAD), uid(0x11), uid(0x12), uid(0xE5)])

    outcome = despatch_order([item_a, item_b], request(uid), REFERENCE, context(uid), new_id)

    assert isinstance(outcome, Despatched)
    assert outcome.advice.id == uid(0xAD)
    [fact] = outcome.advice.domain_events
    assert isinstance(fact, OrderDespatched)
    assert fact.aggregate_id == uid(0xAD)


def test_fs24_each_line_id_is_the_supplied_id_of_its_reservation_in_consumption_order(
    uid: Uid, build_item: BuildItem, id_source: IdSource
) -> None:
    item_a, item_b = two_items(build_item)
    new_id = id_source([uid(0xAD), uid(0x11), uid(0x12), uid(0xE5)])

    outcome = despatch_order([item_a, item_b], request(uid), REFERENCE, context(uid), new_id)

    assert isinstance(outcome, Despatched)
    # PRD-A1's reservation was consumed first and so received the first line id (0x11), PRD-B2's
    # the second (0x12): equality with the values the test supplied, per product
    assert [(ln.product_code, ln.id) for ln in outcome.advice.lines] == [
        ("PRD-A1", uid(0x11)),
        ("PRD-B2", uid(0x12)),
    ]


def test_fs24_the_facts_event_id_is_the_last_supplied_id(
    uid: Uid, build_item: BuildItem, id_source: IdSource
) -> None:
    item_a, item_b = two_items(build_item)
    new_id = id_source([uid(0xAD), uid(0x11), uid(0x12), uid(0xE5)])

    outcome = despatch_order([item_a, item_b], request(uid), REFERENCE, context(uid), new_id)

    assert isinstance(outcome, Despatched)
    [fact] = outcome.advice.domain_events
    assert isinstance(fact, OrderDespatched)
    assert fact.event_id == uid(0xE5)


def test_fs24_the_operation_mints_exactly_one_id_per_site_and_no_more(
    uid: Uid, build_item: BuildItem
) -> None:
    item_a, item_b = two_items(build_item)
    minted: list[UniqueId] = []

    def new_id() -> UniqueId:
        minted.append(uid(0x900 + len(minted)))
        return minted[-1]

    despatch_order([item_a, item_b], request(uid), REFERENCE, context(uid), new_id)

    # one advice id + two line ids (two consumed reservations) + one event id
    assert minted == [uid(0x900), uid(0x901), uid(0x902), uid(0x903)]


def test_the_lines_are_held_in_the_canonical_order_product_code_then_line_id(
    uid: Uid, build_item: BuildItem, id_source: IdSource
) -> None:
    # two reservations of PRD-A1 whose line ids are supplied in DESCENDING order: the advice sorts
    # them (product code, then line id), and its snapshot and its fact follow that order
    item_a = build_item(
        "PRD-A1",
        units=20,
        reserved=7,
        item_number=0xA1,
        reservations=[(0x71, ORDER, 3, RESERVED), (0x72, ORDER, 4, RESERVED)],
    )
    new_id = id_source([uid(0xAD), uid(0x22), uid(0x21), uid(0xE5)])

    outcome = despatch_order([item_a], request(uid), REFERENCE, context(uid), new_id)

    assert isinstance(outcome, Despatched)
    assert [(ln.id, ln.units.value) for ln in outcome.advice.lines] == [
        (uid(0x21), 4),
        (uid(0x22), 3),
    ]
    assert [(ln.id, ln.units) for ln in outcome.advice.to_snapshot().lines] == [
        (uid(0x21), 4),
        (uid(0x22), 3),
    ]
    [fact] = outcome.advice.domain_events
    assert isinstance(fact, OrderDespatched)
    assert [ln.units for ln in fact.lines] == [4, 3]


@pytest.mark.parametrize(
    "statuses",
    [
        pytest.param([], id="no reservation of the order at all"),
        pytest.param([ReservationStatus.RELEASED], id="every reservation released"),
        pytest.param(
            [ReservationStatus.CONSUMED], id="every reservation already consumed (the F8 state)"
        ),
        pytest.param(
            [ReservationStatus.RELEASED, ReservationStatus.CONSUMED], id="released and consumed"
        ),
    ],
)
def test_r36_an_order_holding_no_reserved_reservation_creates_no_advice_and_no_fact_and_changes_nothing(  # noqa: E501
    uid: Uid,
    build_item: BuildItem,
    id_source: IdSource,
    statuses: list[ReservationStatus],
) -> None:
    item = build_item(
        "PRD-A1",
        units=10,
        reserved=1,  # another order's reservation
        item_number=0xA1,
        reservations=[
            *((0x71 + n, ORDER, 3, status) for n, status in enumerate(statuses)),
            (0x7F, OTHER_ORDER, 1, RESERVED),
        ],
    )
    before = item.to_snapshot()

    outcome = despatch_order(
        [item], request(uid), REFERENCE, context(uid), id_source([])
    )  # the source is EMPTY: asking it for an id would fail the test

    assert outcome == NothingToDespatch()
    assert item.to_snapshot() == before, "no counter and no status moved"
    assert item.domain_events == ()


def test_r36_control_the_same_item_with_one_reserved_reservation_does_despatch(
    uid: Uid, build_item: BuildItem, id_source: IdSource
) -> None:
    # the control row of the case above: only the status differs, and the outcome flips
    item = build_item(
        "PRD-A1",
        units=10,
        reserved=4,
        item_number=0xA1,
        reservations=[(0x71, ORDER, 3, RESERVED), (0x7F, OTHER_ORDER, 1, RESERVED)],
    )

    outcome = despatch_order(
        [item], request(uid), REFERENCE, context(uid), id_source([uid(0xAD), uid(0x11), uid(0xE5)])
    )

    assert isinstance(outcome, Despatched)


def test_f6_an_advice_without_a_line_is_refused_and_records_no_fact(uid: Uid) -> None:
    with pytest.raises(EmptyDespatchLinesError) as raised:
        DespatchAdvice.create(
            advice_id=uid(0xAD),
            event_id=uid(0xE5),
            despatch_reference=REFERENCE,
            despatch_date=NOW,
            order_reference=ORDER,
            company_code=COMPANY,
            retailer_code=RETAILER,
            lines=[],
            correlation_id=uid(0xC0C0),
            causation_id=uid(0xCA05),
        )

    assert raised.value.code == "despatch.empty_lines"
    assert ORDER in raised.value.message


def test_f6_control_an_advice_with_one_line_is_created_with_its_fact(uid: Uid) -> None:
    advice = DespatchAdvice.create(
        advice_id=uid(0xAD),
        event_id=uid(0xE5),
        despatch_reference=REFERENCE,
        despatch_date=NOW,
        order_reference=ORDER,
        company_code=COMPANY,
        retailer_code=RETAILER,
        lines=[DespatchLine(id=uid(0x11), product_code="PRD-A1", units=Quantity(3))],
        correlation_id=uid(0xC0C0),
        causation_id=uid(0xCA05),
    )

    assert len(advice.lines) == 1
    assert len(advice.domain_events) == 1


def test_the_snapshot_of_an_advice_carries_every_value_it_was_created_with(
    uid: Uid, build_item: BuildItem, id_source: IdSource
) -> None:
    item_a, item_b = two_items(build_item)
    new_id = id_source([uid(0xAD), uid(0x11), uid(0x12), uid(0xE5)])
    outcome = despatch_order([item_a, item_b], request(uid), REFERENCE, context(uid), new_id)
    assert isinstance(outcome, Despatched)

    snapshot = outcome.advice.to_snapshot()

    assert snapshot.id == uid(0xAD)
    assert snapshot.despatch_reference == REFERENCE
    assert snapshot.despatch_date == NOW
    assert snapshot.order_reference == ORDER
    assert (snapshot.company_code, snapshot.retailer_code) == (COMPANY, RETAILER)
    assert [(ln.id, ln.product_code, ln.units) for ln in snapshot.lines] == [
        (uid(0x11), "PRD-A1", 3),
        (uid(0x12), "PRD-B2", 5),
    ]


def test_r36_an_item_holding_only_released_reservations_of_the_order_is_left_alone_among_reserved_ones(  # noqa: E501
    uid: Uid, build_item: BuildItem, id_source: IdSource
) -> None:
    # #8's `ANonReservedItemAmongstReservedOnes`: PRD-A1 holds a RELEASED reservation of the order
    # (never despatched), PRD-B2 a reserved one. Only PRD-B2's is consumed and traced.
    item_a = build_item(
        "PRD-A1",
        units=10,
        reserved=0,
        item_number=0xA1,
        reservations=[(0x71, ORDER, 3, ReservationStatus.RELEASED)],
    )
    item_b = build_item(
        "PRD-B2",
        units=20,
        reserved=5,
        item_number=0xB2,
        reservations=[(0x72, ORDER, 5, RESERVED)],
    )
    before_a = item_a.to_snapshot()
    new_id = id_source([uid(0xAD), uid(0x11), uid(0xE5)])

    outcome = despatch_order([item_a, item_b], request(uid), REFERENCE, context(uid), new_id)

    assert isinstance(outcome, Despatched)
    assert item_a.to_snapshot() == before_a, "the released reservation and its counters are intact"
    assert [(ln.product_code, ln.units.value) for ln in outcome.advice.lines] == [("PRD-B2", 5)]
    assert (item_b.units, item_b.reserved_units) == (15, 0)
