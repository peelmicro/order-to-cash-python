"""Acceptance 7 (unit part) - the write-boundary range guard, with no database.

A mapped integer attribute refuses a value its column cannot hold with a `DomainError` carrying a
stable code, at assignment, before any statement exists.
"""

import pytest
from sqlalchemy import literal_column

from otc_fulfillment.infrastructure.persistence.models import (
    DespatchItem,
    DespatchNumberSequence,
    Outbox,
    Reservation,
    Stock,
)
from otc_fulfillment.infrastructure.persistence.range_guards import (
    IntegerOutOfRangeError,
    QuantityOutOfRangeError,
    ensure_in_range,
)
from otc_shared_kernel import DomainError

INT32_MAX = 2**31 - 1


@pytest.mark.parametrize(
    ("make", "column"),
    [
        (Stock, "units"),
        (Stock, "reserved_units"),
        (Stock, "low_stock_threshold"),
        (Reservation, "units"),
        (DespatchItem, "units"),
    ],
)
def test_a_unit_count_column_max_is_accepted_and_max_plus_one_is_a_quantity_refusal(
    make: type, column: str
) -> None:
    row = make(**{column: INT32_MAX})
    assert getattr(row, column) == INT32_MAX
    with pytest.raises(QuantityOutOfRangeError) as raised:
        make(**{column: INT32_MAX + 1})
    assert isinstance(raised.value, DomainError)
    assert raised.value.code == "quantity.out_of_range"
    assert column in str(raised.value)


def test_min_minus_one_and_assignment_after_construction_are_refused_too() -> None:
    with pytest.raises(QuantityOutOfRangeError):
        Stock(units=-(2**31) - 1)
    stock = Stock(units=1)
    with pytest.raises(QuantityOutOfRangeError):
        stock.units = 2**31


def test_counters_refuse_overflow_with_the_generic_code_not_the_quantity_code() -> None:
    seq = DespatchNumberSequence(next_value=INT32_MAX)
    with pytest.raises(IntegerOutOfRangeError) as raised:
        seq.next_value = INT32_MAX + 1
    assert raised.value.code == "storage.integer_out_of_range"
    assert not isinstance(raised.value, QuantityOutOfRangeError)
    outbox = Outbox(seq=2**63 - 1)
    with pytest.raises(IntegerOutOfRangeError) as raised_big:
        outbox.seq = 2**63
    assert raised_big.value.code == "storage.integer_out_of_range"


@pytest.mark.parametrize("bad", [True, 1.0, "5"])
def test_a_non_int_value_is_refused_not_coerced(bad: object) -> None:
    with pytest.raises(QuantityOutOfRangeError):
        ensure_in_range(bad, -(2**31), INT32_MAX, "stock.units", QuantityOutOfRangeError)


def test_null_passes_the_guard_because_nullability_is_the_columns_business() -> None:
    assert Stock(units=None).units is None


def test_a_sql_expression_assigned_to_a_guarded_attribute_passes_through() -> None:
    """204(c): `units = units - 1` is SQLAlchemy's atomic server-side update. It is a ClauseElement,
    not a value: refusing it as "out of range" would be false and would block the natural write."""
    stock = Stock(units=1)
    stock.units = Stock.units - 1  # must not raise
    stock.reserved_units = literal_column("reserved_units + 1")  # any ClauseElement
    assert stock.reserved_units is not None
    with pytest.raises(QuantityOutOfRangeError):  # a plain int overflow is still refused
        stock.units = 2**31
