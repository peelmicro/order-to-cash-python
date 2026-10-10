"""`summarise`, the feature's arithmetic (tasks B4, B5; BC5, BC6, BC28, BC30), driven DIRECTLY: no
aggregate, no database.

Loop scope: nothing here is async.
"""

import pytest

from otc_billing.domain.credit_entry_type import CreditEntryType as T
from otc_billing.domain.errors import CreditLedgerOverflowError
from otc_billing.domain.exposure import LedgerLine, OrderExposure, summarise

A = "ORD-000101"
B = "ORD-000202"


def _lines(*rows: tuple[str, T, int]) -> list[LedgerLine]:
    return [LedgerLine(order_reference=o, type=t, amount=a) for o, t, a in rows]


# (shape, rows, committed exposure, exposure, open exposure, active hold) of order A
SHAPES = [
    ("never held", [], 0, None, None, None),
    ("held", [(A, T.HOLD, 410)], 410, 410, 0, 410),
    ("held + consumed", [(A, T.HOLD, 410), (A, T.CONSUME, 410)], 410, 410, 410, 0),
    ("held + released", [(A, T.HOLD, 410), (A, T.RELEASE, 410)], 0, 0, 0, 0),
    (
        "held + consumed + released",
        [(A, T.HOLD, 410), (A, T.CONSUME, 410), (A, T.RELEASE, 410)],
        0,
        0,
        0,
        0,
    ),
]


@pytest.mark.parametrize(
    ("rows", "committed", "exposure", "open_exposure", "active"),
    [s[1:] for s in SHAPES],
    ids=[s[0] for s in SHAPES],
)
def test_bc6_active_holds_plus_open_exposure_equal_the_limit_minus_available_credit_on_every_ledger_shape(  # noqa: E501
    rows: list[tuple[str, T, int]],
    committed: int,
    exposure: int | None,
    open_exposure: int | None,
    active: int | None,
) -> None:
    limit = 1000
    summary = summarise(_lines(*rows))
    # the committed exposure is asserted first, then the per-order split
    assert summary.committed_exposure == committed
    available = limit - summary.committed_exposure
    assert summary.active_holds + summary.open_exposure == limit - available
    assert summary.active_holds >= 0
    assert summary.open_exposure >= 0, "the cancelled-before-invoice shape went negative"
    if exposure is None:
        assert summary.by_order == ()
        return
    [order] = summary.by_order
    assert (order.exposure, order.open_exposure, order.active_hold) == (
        exposure,
        open_exposure,
        active,
    )


def test_bc6_two_orders_on_one_line_sum_and_keep_first_seen_order() -> None:
    summary = summarise(
        _lines(
            (B, T.HOLD, 300),
            (A, T.HOLD, 410),
            (A, T.CONSUME, 410),
            (B, T.HOLD, 11),
            (B, T.RELEASE, 311),
        )
    )
    assert [o.order_reference for o in summary.by_order] == [B, A]
    assert summary.by_order[0] == OrderExposure(
        order_reference=B,
        exposure=0,
        open_exposure=0,
        active_hold=0,
        has_hold_entry=True,
        has_consume_entry=False,
        has_release_entry=True,
    )
    assert summary.committed_exposure == 410
    assert (summary.active_holds, summary.open_exposure) == (0, 410)


def test_bc28_groups_by_exact_order_reference() -> None:
    upper, lower = "ORD-000AB1", "ord-000ab1"
    summary = summarise(_lines((upper, T.HOLD, 100), (lower, T.HOLD, 7)))
    assert [o.order_reference for o in summary.by_order] == [upper, lower], (
        "two references differing only by letter case were merged"
    )
    assert [o.exposure for o in summary.by_order] == [100, 7]
    assert summary.committed_exposure == 107


def _overflow(lines: list[LedgerLine]) -> CreditLedgerOverflowError:
    """The error `summarise` raises; a call that returns FAILS, naming the unbounded total."""
    try:
        summary = summarise(lines)
    except CreditLedgerOverflowError as error:
        return error
    pytest.fail(
        f"BC30: summarise returned a total outside int64 instead of raising: "
        f"committed_exposure={summary.committed_exposure}"
    )


def test_bc30_raises_ledger_overflow_when_one_orders_hold_total_exceeds_int64() -> None:
    half = (1 << 62) + 1
    # control row: one such hold is in range
    assert summarise(_lines((A, T.HOLD, half))).committed_exposure == half
    error = _overflow(_lines((A, T.HOLD, half), (A, T.HOLD, half)))
    assert error.code == "credit.ledger_overflow"


def test_bc30_raises_ledger_overflow_when_the_hold_total_exceeds_int64_though_the_exposure_does_not() -> (  # noqa: E501
    None
):
    # N1 of the round-1 review: the per-order sum of holds is checked on its OWN. Two holds of
    # 2**62 + 1 sum to 2**63 + 2; a release of 3 brings the exposure to exactly INT64_MAX, so the
    # exposure check alone (R9b) cannot raise - only the hold-total check can (R9a).
    half = (1 << 62) + 1
    ledger = _lines((A, T.HOLD, half), (A, T.HOLD, half), (A, T.RELEASE, 3))
    assert 2 * half - 3 == (1 << 63) - 1, "fixture: the exposure lands on INT64_MAX"
    error = _overflow(ledger)
    assert error.code == "credit.ledger_overflow"
    assert "hold ledger total of order ORD-000101" in error.message, (
        "BC30: the overflow was raised by a later check, not by the hold total"
    )


def test_bc30_raises_ledger_overflow_when_the_committed_exposure_across_orders_exceeds_int64() -> (
    None
):
    half = (1 << 62) + 1
    # control row: each order alone is in range, so only the cross-order total overflows
    assert summarise(_lines((A, T.HOLD, half), (B, T.HOLD, 1))).committed_exposure == half + 1
    error = _overflow(_lines((A, T.HOLD, half), (B, T.HOLD, half)))
    assert error.code == "credit.ledger_overflow"


def test_bc30_raises_ledger_overflow_when_a_consume_or_release_total_exceeds_int64() -> None:
    half = (1 << 62) + 1
    for kind in (T.CONSUME, T.RELEASE):
        assert _overflow(_lines((A, kind, half), (A, kind, half))).code == "credit.ledger_overflow"


def test_bc30_raises_ledger_overflow_when_the_exposure_difference_leaves_the_range() -> None:
    top = (1 << 63) - 1
    error = _overflow(_lines((A, T.RELEASE, top), (A, T.RELEASE, 2)))  # 0 - (2**63 + 1)
    assert error.code == "credit.ledger_overflow"
