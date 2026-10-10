"""`CreditLedgerEntry` and the closed entry-type set (task B2; BC37 for the parse, R37 for the
frozen value, BC38 for the zero).

Loop scope: nothing here is async.
"""

import dataclasses
from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from otc_billing.domain.credit_entry_type import CreditEntryType, parse_credit_entry_type
from otc_billing.domain.errors import NegativeLedgerAmountError, UnknownCreditEntryTypeError
from otc_billing.domain.ledger_entry import CreditLedgerEntry
from otc_shared_kernel import Money, UniqueId

WHEN = datetime(2026, 10, 8, 9, 30, tzinfo=UTC)


def _entry(uid: Callable[[int], UniqueId], amount: int) -> CreditLedgerEntry:
    return CreditLedgerEntry(
        entry_id=uid(0xE1),
        order_reference="ORD-000101",
        amount=Money(amount, "EUR"),
        type=CreditEntryType.HOLD,
        entry_date=WHEN,
    )


def test_parse_credit_entry_type_is_exact_and_refuses_everything_outside_the_closed_set() -> None:
    assert parse_credit_entry_type("hold") is CreditEntryType.HOLD
    assert parse_credit_entry_type("consume") is CreditEntryType.CONSUME
    assert parse_credit_entry_type("release") is CreditEntryType.RELEASE
    for refused in ("Hold", " hold", "hold ", "HOLD", "reserve", "", 1, None, b"hold"):
        try:
            parsed = parse_credit_entry_type(refused)
        except UnknownCreditEntryTypeError as error:
            code = error.code
        else:
            pytest.fail(f"BC37: the closed set accepted {refused!r} as {parsed}")
        assert code == "credit_entry.unknown_type", f"{refused!r} was refused with {code}"


def test_parse_credit_entry_type_refuses_a_str_subclass() -> None:
    class Sneaky(str):
        __slots__ = ()

    with pytest.raises(UnknownCreditEntryTypeError):
        parse_credit_entry_type(Sneaky("hold"))


def test_a_ledger_entry_refuses_a_negative_amount_and_cannot_be_assigned(
    uid: Callable[[int], UniqueId],
) -> None:
    try:
        negative = _entry(uid, -1)
    except NegativeLedgerAmountError as error:
        code = error.code
    else:
        pytest.fail(f"R37: a ledger entry accepted the negative amount {negative.amount}")
    assert code == "credit_entry.negative_amount"
    # the control row: the same constructor accepts a positive amount and a zero one (BC38)
    entry = _entry(uid, 4210)
    assert entry.amount == Money(4210, "EUR")
    assert _entry(uid, 0).amount == Money(0, "EUR")
    with pytest.raises(dataclasses.FrozenInstanceError):
        entry.amount = Money(1, "EUR")  # type: ignore[misc]
    assert entry.amount == Money(4210, "EUR"), "the failed assignment changed the entry"
