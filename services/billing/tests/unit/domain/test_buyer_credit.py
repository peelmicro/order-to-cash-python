"""The `BuyerCredit` aggregate: B1 - B3 at the boundary of the snapshot, B2's append-only ledger
(R37), BC5's derived available credit (task B7).

Loop scope: nothing here is async.
"""

import dataclasses
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

import pytest

from otc_billing.domain.buyer_credit import BuyerCredit, CreditContext, HoldRequest
from otc_billing.domain.credit_entry_type import CreditEntryType as T
from otc_billing.domain.errors import (
    CreditLimitExceededError,
    CreditRefusalMismatchError,
    FactAggregateMismatchError,
    InvalidBuyerCreditSnapshotError,
    NegativeLedgerAmountError,
)
from otc_billing.domain.events import CreditApproved
from otc_billing.domain.reasons import CreditRejectionReason, CreditReleaseReason
from otc_billing.domain.snapshot import BuyerCreditSnapshot, CreditLedgerEntrySnapshot
from otc_shared_kernel import Money, UniqueId

ORDER = "ORD-000101"
OTHER = "ORD-000202"


def test_r37_keeps_active_holds_plus_open_exposure_within_the_credit_limit_and_raises_on_any_update_or_deletion_of_a_ledger_entry(  # noqa: E501
    uid: Callable[[int], UniqueId],
    id_source: Callable[[Sequence[UniqueId]], Callable[[], UniqueId]],
    build_credit: Callable[..., BuyerCredit],
    hold_request: Callable[..., HoldRequest],
    context: CreditContext,
) -> None:
    credit = build_credit(limit=1000)
    credit.approve(hold_request(ORDER, 700), context, id_source([uid(0xB1), uid(0xB2)]))
    before = credit.entries
    assert isinstance(before, tuple)
    assert [e.type for e in before] == [T.HOLD]
    summary = credit.summary
    assert summary.active_holds + summary.open_exposure == 700 <= credit.credit_limit.amount

    # a reversal APPENDS a release; it never rewrites the hold
    released = credit.release(
        ORDER,
        CreditReleaseReason.ORDER_CANCELLED,
        uid(0xC0),
        context,
        id_source([uid(0xB3), uid(0xB4)]),
    )
    after = credit.entries
    assert released is not None
    assert after[: len(before)] == before, "a loaded entry was rewritten"
    assert [e.type for e in after] == [T.HOLD, T.RELEASE]
    assert credit.appended_entries == after

    # an update or a deletion raises: the entry is frozen, the view is a tuple
    with pytest.raises(dataclasses.FrozenInstanceError):
        after[0].amount = Money(1, "EUR")  # type: ignore[misc]
    with pytest.raises(TypeError):
        after[0] = after[1]  # type: ignore[index]
    with pytest.raises(TypeError):
        del after[0]  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        credit.entries = ()  # type: ignore[misc]
    assert credit.entries == after

    # the outer bound: a hold over the limit is refused, whatever the caller does
    with pytest.raises(CreditLimitExceededError):
        credit.approve(hold_request(OTHER, 1001), context, id_source([uid(0xB5), uid(0xB6)]))


def test_bc5_derives_available_credit_as_the_limit_minus_holds_plus_releases_so_a_consume_entry_moves_it_by_nothing(  # noqa: E501
    uid: Callable[[int], UniqueId],
    id_source: Callable[[Sequence[UniqueId]], Callable[[], UniqueId]],
    build_credit: Callable[..., BuyerCredit],
    hold_request: Callable[..., HoldRequest],
    context: CreditContext,
) -> None:
    credit = build_credit(limit=1000, committed=150, entries=[])
    assert credit.available_credit == Money(850, "EUR")
    credit.approve(hold_request(ORDER, 250), context, id_source([uid(0xB1), uid(0xB2)]))
    assert credit.available_credit == Money(600, "EUR")
    assert credit.committed_exposure == Money(400, "EUR")
    credit.consume(ORDER, context, id_source([uid(0xB3)]))
    assert credit.available_credit == Money(600, "EUR"), "a consume entry moved the credit"
    credit.release(
        ORDER,
        CreditReleaseReason.INVOICE_PAID,
        uid(0xC0),
        context,
        id_source([uid(0xB4), uid(0xB5)]),
    )
    assert credit.available_credit == Money(850, "EUR")
    assert credit.to_snapshot().committed_exposure == 150


def _snapshot(
    uid: Callable[[int], UniqueId],
    *,
    limit: int = 1000,
    committed: int = 0,
    entries: Sequence[tuple[int, str, str]] = (),
) -> BuyerCreditSnapshot:
    return BuyerCreditSnapshot(
        id=uid(0x1D),
        code="CR-000321",
        retailer_code="RETAIL-77",
        company_code="SUPPLY-CO",
        currency="EUR",
        credit_limit=limit,
        committed_exposure=committed,
        entries=tuple(
            CreditLedgerEntrySnapshot(
                entry_id=uid(number),
                order_reference=order,
                amount=Money(10, currency),
                type=T.HOLD,
                entry_date=datetime(2026, 10, 8, tzinfo=UTC),
            )
            for number, order, currency in entries
        ),
    )


def test_rehydrate_refuses_a_snapshot_over_its_limit_a_foreign_currency_entry_and_another_orders_entry(  # noqa: E501
    uid: Callable[[int], UniqueId],
) -> None:
    # control row: a snapshot exactly at its limit with an entry in the line's currency is accepted
    ok = BuyerCredit.rehydrate(
        _snapshot(uid, limit=1000, committed=1000, entries=[(1, ORDER, "EUR")])
    )
    assert ok.available_credit == Money(0, "EUR")

    refused = {
        "over its limit": _snapshot(uid, limit=1000, committed=1001),
        "a negative limit": _snapshot(uid, limit=-1),
        "a foreign-currency entry": _snapshot(uid, entries=[(1, ORDER, "USD")]),
        "entries of two orders": _snapshot(uid, entries=[(1, ORDER, "EUR"), (2, OTHER, "EUR")]),
    }
    for case, snapshot in refused.items():
        try:
            BuyerCredit.rehydrate(snapshot)
        except InvalidBuyerCreditSnapshotError as error:
            code = error.code
        else:
            pytest.fail(f"rehydrate accepted a snapshot {case}")
        assert code == "buyer_credit.invalid_snapshot", case


def test_every_refused_call_leaves_the_snapshot_and_the_events_unchanged(
    uid: Callable[[int], UniqueId],
    id_source: Callable[[Sequence[UniqueId]], Callable[[], UniqueId]],
    build_credit: Callable[..., BuyerCredit],
    hold_request: Callable[..., HoldRequest],
    context: CreditContext,
) -> None:
    credit = build_credit(limit=1000, committed=300, entries=[(0x10, ORDER, 300, T.HOLD)])
    before = credit.to_snapshot()
    attempts: dict[str, tuple[type[Exception], Callable[[], object]]] = {
        "an over-limit approve": (
            CreditLimitExceededError,
            lambda: credit.approve(
                hold_request(OTHER, 701), context, id_source([uid(0xB1), uid(0xB2)])
            ),
        ),
        "a negative approve": (
            NegativeLedgerAmountError,
            lambda: credit.approve(
                hold_request(OTHER, -5), context, id_source([uid(0xB1), uid(0xB2)])
            ),
        ),
        "a re-approve of a held order": (
            CreditRefusalMismatchError,
            lambda: credit.approve(
                hold_request(ORDER, 5), context, id_source([uid(0xB1), uid(0xB2)])
            ),
        ),
        "a foreign-currency approve": (
            CreditRefusalMismatchError,
            lambda: credit.approve(
                hold_request(OTHER, 5, currency="USD"), context, id_source([uid(0xB1), uid(0xB2)])
            ),
        ),
        "an over_limit refusal of a hold that fits": (
            CreditRefusalMismatchError,
            lambda: credit.refuse(
                hold_request(OTHER, 5),
                CreditRejectionReason.OVER_LIMIT,
                context,
                id_source([uid(0xB1)]),
            ),
        ),
    }
    for case, (expected, attempt) in attempts.items():
        with pytest.raises(expected):
            attempt()
        assert credit.to_snapshot() == before, f"{case} changed the aggregate"
        assert credit.domain_events == (), f"{case} left an event behind"
        assert credit.appended_entries == (), f"{case} appended an entry"


def test_a_fact_about_another_aggregate_is_refused_and_one_about_this_line_is_recorded(
    uid: Callable[[int], UniqueId],
    build_credit: Callable[..., BuyerCredit],
) -> None:
    credit = build_credit()
    fact = CreditApproved(
        event_id=uid(0xF1),
        aggregate_id=uid(0x1D),
        correlation_id=uid(0xC0),
        causation_id=uid(0xCA0),
        occurred_at=datetime(2026, 10, 8, tzinfo=UTC),
        order_reference=ORDER,
        retailer_code="RETAIL-77",
        company_code="SUPPLY-CO",
        credit_code="CR-000321",
        currency="EUR",
        held_amount=1,
        available_credit_after=999,
    )
    credit.record_fact(fact)
    assert credit.domain_events == (fact,)
    with pytest.raises(FactAggregateMismatchError):
        credit.record_fact(dataclasses.replace(fact, aggregate_id=uid(0x1E)))
    assert credit.domain_events == (fact,)
