"""The ledger lifecycle of one order: consume (R40), release (R41), the structural readings of
"outstanding" and "active" (BC11, BC12) and the zero hold (BC38, gate point G1 as recommended)
(task B9).

Loop scope: nothing here is async.
"""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime

import pytest

from otc_billing.domain.buyer_credit import BuyerCredit, CreditContext, HoldRequest
from otc_billing.domain.credit_entry_type import CreditEntryType as T
from otc_billing.domain.errors import CreditReleaseUnderflowError, NoActiveHoldError
from otc_billing.domain.events import CreditReleased
from otc_billing.domain.exposure import LedgerLine, summarise
from otc_billing.domain.reasons import CreditReleaseReason
from otc_shared_kernel import Money, UniqueId

ORDER = "ORD-000101"
RETAILER = "RETAIL-77"
COMPANY = "SUPPLY-CO"
CODE = "CR-000321"
# Another order of the same line holds 400. The aggregate loads only ITS order's entries and takes
# the line's committed exposure as a scalar, so the 400 is inside `committed` (650 = 250 + 400) and
# stays there through every release below: available after a release is 600, which differs from the
# limit (1000) and from the value before it (350) - D1 of the round-1 review.
WHEN = datetime(2026, 10, 8, 9, 30, 15, 123000, tzinfo=UTC)

IdSourceFactory = Callable[[Sequence[UniqueId]], Callable[[], UniqueId]]


def test_r40_appends_a_consume_entry_at_invoice_issue_that_leaves_available_credit_numerically_unchanged_and_emits_no_fact(  # noqa: E501
    uid: Callable[[int], UniqueId],
    id_source: IdSourceFactory,
    build_credit: Callable[..., BuyerCredit],
    context: CreditContext,
) -> None:
    credit = build_credit(limit=1000, committed=250, entries=[(0x10, ORDER, 250, T.HOLD)])
    available_before = credit.available_credit
    entry = credit.consume(ORDER, context, id_source([uid(0xA1)]))
    assert (entry.type, entry.amount, entry.order_reference) == (
        T.CONSUME,
        Money(250, "EUR"),
        ORDER,
    )
    assert credit.appended_entries == (entry,)
    assert credit.domain_events == (), "consume emitted a fact"
    assert credit.available_credit == available_before == Money(750, "EUR"), (
        "R40: a consume entry moved the available credit"
    )
    order = credit.summary.by_order[0]
    assert (order.active_hold, order.open_exposure) == (0, 250)


def test_r41_releases_with_reason_invoice_paid_on_payment_and_with_reason_order_cancelled_on_cancellation_restoring_available_credit_without_going_below_zero(  # noqa: E501
    uid: Callable[[int], UniqueId],
    id_source: IdSourceFactory,
    build_credit: Callable[..., BuyerCredit],
    context: CreditContext,
) -> None:
    for reason, shape in (
        (
            CreditReleaseReason.INVOICE_PAID,
            [(0x10, ORDER, 250, T.HOLD), (0x11, ORDER, 250, T.CONSUME)],
        ),
        (CreditReleaseReason.ORDER_CANCELLED, [(0x10, ORDER, 250, T.HOLD)]),
    ):
        credit = build_credit(limit=1000, committed=650, entries=shape)
        assert credit.available_credit == Money(350, "EUR"), "fixture: the pre-release value"
        entry = credit.release(ORDER, reason, uid(0xC0), context, id_source([uid(0xA1), uid(0xA2)]))
        assert entry is not None
        assert (entry.type, entry.amount) == (T.RELEASE, Money(250, "EUR"))
        events = credit.domain_events
        assert len(events) == 1, f"{reason}: expected exactly one fact, got {len(events)}"
        assert events[0] == CreditReleased(
            event_id=uid(0xA2),
            aggregate_id=uid(0x1D),
            correlation_id=uid(0xC0),
            causation_id=uid(0xCA0),
            occurred_at=WHEN,
            order_reference=ORDER,
            retailer_code=RETAILER,
            company_code=COMPANY,
            credit_code=CODE,
            currency="EUR",
            released_amount=250,
            available_credit_after=600,
            reason=reason,
        )
        assert CreditReleased.EVENT_TYPE == "credit.released.v1"
        assert credit.available_credit == Money(600, "EUR"), (
            "R41: the release did not restore exactly its own 250 (not the limit, not 350)"
        )
        assert credit.committed_exposure.amount >= 0


def test_a_negative_exposure_in_a_loaded_ledger_is_refused_by_a_release(
    uid: Callable[[int], UniqueId],
    id_source: IdSourceFactory,
    build_credit: Callable[..., BuyerCredit],
    context: CreditContext,
) -> None:
    corrupt = build_credit(
        limit=1000,
        committed=0,
        entries=[(0x10, ORDER, 100, T.HOLD), (0x11, ORDER, 150, T.RELEASE)],
    )
    before = corrupt.to_snapshot()
    with pytest.raises(CreditReleaseUnderflowError) as raised:
        corrupt.release(
            ORDER, CreditReleaseReason.ORDER_CANCELLED, uid(0xC0), context, id_source([])
        )
    assert raised.value.code == "credit.release_underflow"
    assert "-0.50 EUR" in raised.value.message
    assert corrupt.to_snapshot() == before
    assert corrupt.domain_events == ()
    # control row: a ledger released exactly is a no-op, not an error
    settled = build_credit(
        limit=1000,
        committed=0,
        entries=[(0x10, ORDER, 100, T.HOLD), (0x11, ORDER, 100, T.RELEASE)],
    )
    assert (
        settled.release(
            ORDER, CreditReleaseReason.ORDER_CANCELLED, uid(0xC0), context, id_source([])
        )
        is None
    )


def test_bc11_releases_the_outstanding_exposure_once_and_reports_a_no_op_on_a_second_release(
    uid: Callable[[int], UniqueId],
    id_source: IdSourceFactory,
    build_credit: Callable[..., BuyerCredit],
    context: CreditContext,
) -> None:
    credit = build_credit(limit=1000, committed=650, entries=[(0x10, ORDER, 250, T.HOLD)])
    first = credit.release(
        ORDER,
        CreditReleaseReason.ORDER_CANCELLED,
        uid(0xC0),
        context,
        id_source([uid(0xA1), uid(0xA2)]),
    )
    assert first is not None
    assert len(credit.domain_events) == 1
    assert credit.available_credit == Money(600, "EUR"), "BC11: the release was not counted once"
    assert isinstance(credit.domain_events[0], CreditReleased)
    assert credit.domain_events[0].available_credit_after == 600
    snapshot = credit.to_snapshot()
    # a second release: nothing outstanding; a source with NO ids proves nothing was minted
    second = credit.release(
        ORDER, CreditReleaseReason.ORDER_CANCELLED, uid(0xC0), context, id_source([])
    )
    assert second is None
    assert len(credit.domain_events) == 1, "the no-op release emitted a fact"
    assert credit.to_snapshot() == snapshot
    assert len(credit.appended_entries) == 1
    # an order never held is a no-op too
    never = build_credit(limit=1000, committed=400, entries=[])
    assert (
        never.release(ORDER, CreditReleaseReason.ORDER_CANCELLED, uid(0xC0), context, id_source([]))
        is None
    )
    assert never.domain_events == ()


def test_bc12_consume_leaves_available_credit_unchanged_emits_no_fact_and_refuses_an_order_with_no_active_hold(  # noqa: E501
    uid: Callable[[int], UniqueId],
    id_source: IdSourceFactory,
    build_credit: Callable[..., BuyerCredit],
    context: CreditContext,
) -> None:
    refused = {
        "never held": [],
        "consumed": [(0x10, ORDER, 250, T.HOLD), (0x11, ORDER, 250, T.CONSUME)],
        "released": [(0x10, ORDER, 250, T.HOLD), (0x11, ORDER, 250, T.RELEASE)],
    }
    for case, entries in refused.items():
        credit = build_credit(limit=1000, committed=0, entries=entries)
        before = credit.to_snapshot()
        with pytest.raises(NoActiveHoldError):
            credit.consume(ORDER, context, id_source([uid(0xA1)]))
        assert credit.to_snapshot() == before, f"{case}: the refused consume changed the aggregate"
        assert credit.domain_events == ()
    # control row: an active hold is consumed with no fact
    credit = build_credit(limit=1000, committed=250, entries=[(0x10, ORDER, 250, T.HOLD)])
    credit.consume(ORDER, context, id_source([uid(0xA1)]))
    assert credit.domain_events == ()


def test_bc38_a_zero_hold_is_approved_consumed_and_released_with_one_fact_each_where_owed(
    uid: Callable[[int], UniqueId],
    id_source: IdSourceFactory,
    build_credit: Callable[..., BuyerCredit],
    hold_request: Callable[..., HoldRequest],
    context: CreditContext,
) -> None:
    credit = build_credit(limit=1000, committed=300, entries=[])
    entry = credit.approve(hold_request(ORDER, 0), context, id_source([uid(0xA1), uid(0xA2)]))
    assert entry.amount == Money(0, "EUR")
    assert len(credit.domain_events) == 1, "a zero hold must emit exactly one credit.approved.v1"
    assert credit.available_credit == Money(700, "EUR")

    try:
        consumed = credit.consume(ORDER, context, id_source([uid(0xA3)]))
    except NoActiveHoldError:
        pytest.fail("BC38: a zero hold could not be consumed at invoice issue")
    assert (consumed.type, consumed.amount) == (T.CONSUME, Money(0, "EUR"))
    assert len(credit.domain_events) == 1, "consume emitted a fact"
    with pytest.raises(NoActiveHoldError):
        credit.consume(ORDER, context, id_source([uid(0xA4)]))

    released = credit.release(
        ORDER,
        CreditReleaseReason.INVOICE_PAID,
        uid(0xC0),
        context,
        id_source([uid(0xA5), uid(0xA6)]),
    )
    assert released is not None, "BC38: a zero hold was not released (nothing outstanding)"
    assert (released.type, released.amount) == (T.RELEASE, Money(0, "EUR"))
    assert len(credit.domain_events) == 2
    assert credit.available_credit == Money(700, "EUR")
    again = credit.release(
        ORDER, CreditReleaseReason.INVOICE_PAID, uid(0xC0), context, id_source([])
    )
    assert again is None
    assert len(credit.domain_events) == 2


def test_the_structural_and_the_amount_readings_agree_on_every_positive_ledger_shape(
    uid: Callable[[int], UniqueId],
    id_source: IdSourceFactory,
    build_credit: Callable[..., BuyerCredit],
    context: CreditContext,
) -> None:
    """`design.md` 5.1: the structural reading (a `hold` entry and no `release`; a `hold` and
    neither `consume` nor `release`) selects the same orders as #7's and #8's amount reading
    (`exposure > 0`; `active_hold > 0`) on the four positive shapes the system can write."""
    shapes = {
        "held": [(1, ORDER, 250, T.HOLD)],
        "held + consumed": [(1, ORDER, 250, T.HOLD), (2, ORDER, 250, T.CONSUME)],
        "held + released": [(1, ORDER, 250, T.HOLD), (2, ORDER, 250, T.RELEASE)],
        "held + consumed + released": [
            (1, ORDER, 250, T.HOLD),
            (2, ORDER, 250, T.CONSUME),
            (3, ORDER, 250, T.RELEASE),
        ],
    }
    for case, entries in shapes.items():
        order = summarise(LedgerLine(o, t, a) for _, o, a, t in entries).by_order[0]
        credit = build_credit(limit=1000, committed=order.exposure, entries=entries)
        released = credit.release(
            ORDER,
            CreditReleaseReason.ORDER_CANCELLED,
            uid(0xC0),
            context,
            id_source([uid(0xA1), uid(0xA2)]),
        )
        assert (released is not None) == (order.exposure > 0), f"{case}: release reading differs"

        credit = build_credit(limit=1000, committed=order.exposure, entries=entries)
        try:
            credit.consume(ORDER, context, id_source([uid(0xA3)]))
            consumed = True
        except NoActiveHoldError:
            consumed = False
        assert consumed == (order.active_hold > 0), f"{case}: consume reading differs"
