"""Acceptance 4 (range guard, unit part) - the write-boundary range guard, with no database.

A mapped integer attribute refuses a value its column cannot hold with a `DomainError` carrying a
stable code, at assignment, before any statement exists. `invoice_items.units` carries the quantity
code; money (`bigint`) and counters carry the generic code.
"""

from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import BigInteger, Integer, literal, literal_column

from otc_billing.infrastructure.persistence.models import (
    Credit,
    Invoice,
    InvoiceItem,
    InvoiceNumberSequence,
    Outbox,
    Payment,
)
from otc_billing.infrastructure.persistence.range_guards import (
    IntegerOutOfRangeError,
    QuantityOutOfRangeError,
    ensure_in_range,
)
from otc_shared_kernel import DomainError

INT32_MAX = 2**31 - 1
INT64_MAX = 2**63 - 1


def test_the_unit_count_column_max_is_accepted_and_max_plus_one_is_a_quantity_refusal() -> None:
    row = InvoiceItem(units=INT32_MAX)
    assert row.units == INT32_MAX
    with pytest.raises(QuantityOutOfRangeError) as raised:
        InvoiceItem(units=INT32_MAX + 1)
    assert isinstance(raised.value, DomainError)
    assert raised.value.code == "quantity.out_of_range"
    assert "units" in str(raised.value)


@pytest.mark.parametrize(
    ("make", "column"),
    [
        (Credit, "credit_limit"),
        (Invoice, "amount"),
        (Invoice, "discount"),
        (Invoice, "total_amount"),
        (InvoiceItem, "price"),
        (Payment, "amount"),
    ],
)
def test_money_columns_accept_int64_max_and_refuse_max_plus_one_with_the_generic_code(
    make: type, column: str
) -> None:
    row = make(**{column: INT64_MAX})
    assert getattr(row, column) == INT64_MAX
    with pytest.raises(IntegerOutOfRangeError) as raised:
        make(**{column: INT64_MAX + 1})
    assert raised.value.code == "storage.integer_out_of_range"
    assert not isinstance(raised.value, QuantityOutOfRangeError)
    assert column in str(raised.value)


def test_min_minus_one_and_assignment_after_construction_are_refused_too() -> None:
    with pytest.raises(QuantityOutOfRangeError):
        InvoiceItem(units=-(2**31) - 1)
    item = InvoiceItem(units=1)
    with pytest.raises(QuantityOutOfRangeError):
        item.units = 2**31


def test_counters_refuse_overflow_with_the_generic_code_not_the_quantity_code() -> None:
    seq = InvoiceNumberSequence(next_value=INT32_MAX)
    with pytest.raises(IntegerOutOfRangeError) as raised:
        seq.next_value = INT32_MAX + 1
    assert raised.value.code == "storage.integer_out_of_range"
    assert not isinstance(raised.value, QuantityOutOfRangeError)
    outbox = Outbox(seq=INT64_MAX)
    with pytest.raises(IntegerOutOfRangeError) as raised_big:
        outbox.seq = 2**63
    assert raised_big.value.code == "storage.integer_out_of_range"


@pytest.mark.parametrize("bad", [True, 1.0, "5"])
def test_a_non_int_value_is_refused_not_coerced(bad: object) -> None:
    with pytest.raises(QuantityOutOfRangeError):
        ensure_in_range(bad, -(2**31), INT32_MAX, "invoice_items.units", QuantityOutOfRangeError)


def test_null_passes_the_guard_because_nullability_is_the_columns_business() -> None:
    assert InvoiceItem(units=None).units is None


def test_a_sql_expression_assigned_to_a_guarded_attribute_passes_through() -> None:
    """204(c): `units = units - 1` is SQLAlchemy's atomic server-side update. It is a ClauseElement,
    not a value: refusing it as "out of range" would be false and would block the natural write."""
    item = InvoiceItem(units=1)
    item.units = InvoiceItem.units - 1  # must not raise
    item.price = literal_column("price + 1", BigInteger)  # typed ClauseElement
    assert item.price is not None
    with pytest.raises(QuantityOutOfRangeError):  # a plain int overflow is still refused
        item.units = 2**31


# --- backlog 207: only an Integer-typed expression passes through --------------------------------
# PostgreSQL silently ROUNDS a non-integer expression into an integer column (measured: literal(3.7)
# stored as 4, `x * 0.5` as 0, `x + 0.6` as 1, while a raw 3.7 is refused), so the pass-through is
# gated on the expression's SQL type, not on "is a ClauseElement".
@pytest.mark.parametrize(
    "expression",
    [
        pytest.param(InvoiceItem.units * 0.5, id="integer column times a float"),
        pytest.param(InvoiceItem.units + 0.6, id="integer column plus a float"),
        pytest.param(literal(3.7), id="float literal"),
        pytest.param(literal(Decimal("3.7")), id="numeric literal"),
        pytest.param(literal_column("units + 1"), id="untyped literal_column (NullType)"),
    ],
)
def test_a_non_integer_typed_expression_is_refused_not_rounded_by_the_engine(
    expression: Any,
) -> None:
    item = InvoiceItem(units=1)
    with pytest.raises(IntegerOutOfRangeError):
        item.units = expression


@pytest.mark.parametrize(
    "expression",
    [
        pytest.param(InvoiceItem.units + 1, id="integer column plus an int"),
        pytest.param(InvoiceItem.units - 1, id="integer column minus an int"),
        pytest.param(literal(3), id="int literal"),
        pytest.param(literal_column("units + 1", Integer), id="typed literal_column"),
    ],
)
def test_an_integer_typed_expression_still_passes_through(expression: Any) -> None:
    item = InvoiceItem(units=1)
    item.units = expression  # must not raise
    assert item.units is expression
