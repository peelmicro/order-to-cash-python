"""The hold decision of the aggregate: approve, refuse and the evaluation order (task B8; R38, R39,
BC10, BC14, BC26).

Every case asserts that exactly ONE fact was raised and opens EVERY field of it against the
test-supplied, pairwise-distinct values (the credit line 0x1D, the correlation 0xC0, the causation
0xCA0, the supplied event ids; retailer `RETAIL-77` is neither the company `SUPPLY-CO` nor
contained in it).

Loop scope: nothing here is async.
"""

import dataclasses
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

import pytest

from otc_billing.domain.buyer_credit import (
    AlreadyHeld,
    BuyerCredit,
    CreditContext,
    CurrencyMismatch,
    Fits,
    HoldRequest,
    OverLimit,
)
from otc_billing.domain.credit_entry_type import CreditEntryType as T
from otc_billing.domain.errors import CreditLimitExceededError, CreditRefusalMismatchError
from otc_billing.domain.events import CreditApproved, CreditRejected
from otc_billing.domain.reasons import (
    AdapterRejectionReason,
    CreditRejectionReason,
    to_rejection_reason,
)
from otc_shared_kernel import Money, UniqueId

ORDER = "ORD-000101"
OTHER = "ORD-000202"
RETAILER = "RETAIL-77"
COMPANY = "SUPPLY-CO"
CODE = "CR-000321"
WHEN = datetime(2026, 10, 8, 9, 30, 15, 123000, tzinfo=UTC)


def _approved(uid: Callable[[int], UniqueId], held: int, after: int) -> CreditApproved:
    return CreditApproved(
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
        held_amount=held,
        available_credit_after=after,
    )


def _rejected(
    uid: Callable[[int], UniqueId], requested: int, available: int, reason: CreditRejectionReason
) -> CreditRejected:
    return CreditRejected(
        event_id=uid(0xA3),
        aggregate_id=uid(0x1D),
        correlation_id=uid(0xC0),
        causation_id=uid(0xCA0),
        occurred_at=WHEN,
        order_reference=ORDER,
        retailer_code=RETAILER,
        company_code=COMPANY,
        credit_code=CODE,
        currency="EUR",
        requested_amount=requested,
        available_credit=available,
        reason=reason,
    )


def test_r38_appends_a_hold_entry_and_emits_exactly_one_credit_approved_v1_carrying_the_held_amount_and_the_resulting_available_credit(  # noqa: E501
    uid: Callable[[int], UniqueId],
    id_source: Callable[[Sequence[UniqueId]], Callable[[], UniqueId]],
    build_credit: Callable[..., BuyerCredit],
    hold_request: Callable[..., HoldRequest],
    context: CreditContext,
) -> None:
    credit = build_credit(limit=1000, committed=300, entries=[])
    entry = credit.approve(hold_request(ORDER, 250), context, id_source([uid(0xA1), uid(0xA2)]))

    events = credit.domain_events
    assert len(events) == 1, f"expected exactly one fact, got {len(events)}"
    assert isinstance(events[0], CreditApproved)
    assert events[0].EVENT_TYPE == "credit.approved.v1"
    assert events[0] == _approved(uid, held=250, after=450), (
        "R38: a field of the credit.approved.v1 fact is not the supplied/derived value"
    )
    assert credit.appended_entries == (entry,)
    assert (entry.type, entry.amount, entry.order_reference) == (T.HOLD, Money(250, "EUR"), ORDER)
    assert (entry.entry_id, entry.entry_date) == (uid(0xA1), WHEN)


def test_r39_appends_no_ledger_entry_and_emits_credit_rejected_v1_with_a_machine_readable_reason_when_the_amount_exceeds_the_available_credit_or_the_credit_port_refuses(  # noqa: E501
    uid: Callable[[int], UniqueId],
    id_source: Callable[[Sequence[UniqueId]], Callable[[], UniqueId]],
    build_credit: Callable[..., BuyerCredit],
    hold_request: Callable[..., HoldRequest],
    context: CreditContext,
) -> None:
    # over limit: 700 available, 701 requested
    credit = build_credit(limit=1000, committed=300, entries=[])
    request = hold_request(ORDER, 701)
    evaluation = credit.evaluate_hold(request)
    assert evaluation == OverLimit(available_credit=Money(700, "EUR"))
    credit.refuse(request, CreditRejectionReason.OVER_LIMIT, context, id_source([uid(0xA3)]))
    assert credit.appended_entries == ()
    assert len(credit.domain_events) == 1, "expected exactly one fact on the over-limit refusal"
    assert credit.domain_events[0] == _rejected(uid, 701, 700, CreditRejectionReason.OVER_LIMIT), (
        "R39: a field of the over-limit credit.rejected.v1 fact is wrong"
    )
    assert credit.available_credit == Money(700, "EUR"), "a refusal moved the available credit"

    # a port reason: the hold fits (250 <= 700) and the adapter says no
    credit = build_credit(limit=1000, committed=300, entries=[])
    request = hold_request(ORDER, 250)
    assert credit.evaluate_hold(request) == Fits()
    credit.refuse(
        request,
        to_rejection_reason(AdapterRejectionReason.SIMULATED_CENTS_RULE),
        context,
        id_source([uid(0xA3)]),
    )
    assert credit.appended_entries == ()
    assert len(credit.domain_events) == 1, "expected exactly one fact on the port refusal"
    assert credit.domain_events[0] == _rejected(
        uid, 250, 700, CreditRejectionReason.SIMULATED_CENTS_RULE
    ), "R39/BC14: a field of the port-refusal credit.rejected.v1 fact is wrong"
    assert CreditRejected.EVENT_TYPE == "credit.rejected.v1"


def test_bc10_available_credit_after_is_recomputed_with_the_appended_hold(
    uid: Callable[[int], UniqueId],
    id_source: Callable[[Sequence[UniqueId]], Callable[[], UniqueId]],
    build_credit: Callable[..., BuyerCredit],
    hold_request: Callable[..., HoldRequest],
    context: CreditContext,
) -> None:
    credit = build_credit(limit=1000, committed=300, entries=[])
    pre_hold = credit.available_credit.amount
    credit.approve(hold_request(ORDER, 250), context, id_source([uid(0xA1), uid(0xA2)]))
    [fact] = credit.domain_events
    assert isinstance(fact, CreditApproved)
    assert pre_hold == 700
    assert fact.available_credit_after == 450, "the fact carries the pre-hold value"
    assert fact.available_credit_after == credit.available_credit.amount


def test_bc14_an_adapter_refusal_differs_from_an_over_limit_refusal_only_in_reason(
    uid: Callable[[int], UniqueId],
    id_source: Callable[[Sequence[UniqueId]], Callable[[], UniqueId]],
    build_credit: Callable[..., BuyerCredit],
    hold_request: Callable[..., HoldRequest],
    context: CreditContext,
) -> None:
    """Both facts come from ONE fixture and are compared after normalising `event_id`,
    `occurred_at` and `reason`; the amount is the one that is over the limit in the first run and
    under it in the second, so the two requests are the SAME request against two lines."""
    over = build_credit(limit=300, committed=0, entries=[])
    over.refuse(
        hold_request(ORDER, 300 + 1),
        CreditRejectionReason.OVER_LIMIT,
        context,
        id_source([uid(0xA3)]),
    )
    port = build_credit(limit=1000, committed=0, entries=[])
    port.refuse(
        hold_request(ORDER, 300 + 1),
        to_rejection_reason(AdapterRejectionReason.SIMULATED_FAILURE_RATE),
        context,
        id_source([uid(0xA4)]),
    )
    [a] = over.domain_events
    [b] = port.domain_events
    assert isinstance(a, CreditRejected)
    assert isinstance(b, CreditRejected)
    assert a.reason is CreditRejectionReason.OVER_LIMIT
    assert b.reason is CreditRejectionReason.SIMULATED_FAILURE_RATE

    # the available credit differs because the two lines differ; align it, then compare the rest
    def normalised(fact: CreditRejected) -> CreditRejected:
        return dataclasses.replace(
            fact,
            event_id=uid(1),
            occurred_at=WHEN,
            reason=CreditRejectionReason.OVER_LIMIT,
            available_credit=0,
        )

    assert normalised(a) == normalised(b)
    assert (a.requested_amount, b.requested_amount) == (301, 301)


def test_bc14_a_refusal_with_the_over_limit_reason_is_refused_when_the_hold_fits(
    uid: Callable[[int], UniqueId],
    id_source: Callable[[Sequence[UniqueId]], Callable[[], UniqueId]],
    build_credit: Callable[..., BuyerCredit],
    hold_request: Callable[..., HoldRequest],
    context: CreditContext,
) -> None:
    credit = build_credit(limit=1000, committed=0, entries=[])
    with pytest.raises(CreditRefusalMismatchError):
        credit.refuse(
            hold_request(ORDER, 1000),  # exactly the limit still fits
            CreditRejectionReason.OVER_LIMIT,
            context,
            id_source([uid(0xA3)]),
        )
    assert credit.domain_events == ()
    # control: one unit more is a genuine over-limit refusal
    credit.refuse(
        hold_request(ORDER, 1001), CreditRejectionReason.OVER_LIMIT, context, id_source([uid(0xA3)])
    )
    assert len(credit.domain_events) == 1


def test_bc26_already_held_ranks_above_currency_mismatch_and_currency_mismatch_above_over_limit(
    build_credit: Callable[..., BuyerCredit],
    hold_request: Callable[..., HoldRequest],
) -> None:
    # one request satisfying all three: a hold is recorded, the currency differs, the amount is
    # over the limit
    credit = build_credit(limit=1000, committed=400, entries=[(0x10, ORDER, 400, T.HOLD)])
    all_three = hold_request(ORDER, 5000, currency="USD")
    assert credit.evaluate_hold(all_three) == AlreadyHeld(held_amount=Money(400, "EUR")), (
        "BC26: already_held must rank above currency_mismatch"
    )

    # currency mismatch and over the limit, nothing held: the currency wins
    nothing_held = build_credit(limit=1000, committed=400, entries=[])
    assert nothing_held.evaluate_hold(hold_request(OTHER, 5000, currency="USD")) == (
        CurrencyMismatch(expected="EUR", received="USD")
    ), "BC26: currency_mismatch must rank above over_limit"
    # control: with the right currency the same amount is over the limit, and 600 fits
    assert nothing_held.evaluate_hold(hold_request(OTHER, 5000)) == OverLimit(Money(600, "EUR"))
    assert nothing_held.evaluate_hold(hold_request(OTHER, 600)) == Fits()
    # already held and merely over the limit: already held
    assert credit.evaluate_hold(hold_request(ORDER, 5000)) == AlreadyHeld(Money(400, "EUR"))


def test_approve_refuses_an_over_limit_amount_by_its_own_evaluation(
    uid: Callable[[int], UniqueId],
    id_source: Callable[[Sequence[UniqueId]], Callable[[], UniqueId]],
    build_credit: Callable[..., BuyerCredit],
    hold_request: Callable[..., HoldRequest],
    context: CreditContext,
) -> None:
    credit = build_credit(limit=1000, committed=400, entries=[])
    with pytest.raises(CreditLimitExceededError) as raised:
        credit.approve(hold_request(ORDER, 601), context, id_source([uid(0xA1), uid(0xA2)]))
    assert (raised.value.requested, raised.value.available) == (601, 600)
    assert credit.domain_events == ()
