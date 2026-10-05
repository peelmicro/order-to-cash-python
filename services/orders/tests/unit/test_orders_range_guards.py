"""Acceptance 5 (unit part) - the write-boundary range guard, with no database.

A mapped integer attribute refuses a value its column cannot hold with a `DomainError` carrying a
stable code, at assignment, before any statement exists.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Integer, literal, literal_column

from otc_orders.infrastructure.persistence.models import Order, OrderItem, SagaCommand
from otc_orders.infrastructure.persistence.range_guards import (
    IntegerOutOfRangeError,
    QuantityOutOfRangeError,
    ensure_in_range,
)
from otc_shared_kernel import DomainError

INT32_MAX = 2**31 - 1


def test_quantity_column_max_is_accepted() -> None:
    item = OrderItem(quantity=INT32_MAX)
    assert item.quantity == INT32_MAX


def test_quantity_column_max_plus_one_is_a_domain_refusal_with_a_stable_code() -> None:
    with pytest.raises(QuantityOutOfRangeError) as raised:
        OrderItem(quantity=2**31)
    assert isinstance(raised.value, DomainError)
    assert raised.value.code == "quantity.out_of_range"
    assert "order_items.quantity" in str(raised.value)


def test_quantity_column_min_minus_one_is_refused_too() -> None:
    with pytest.raises(QuantityOutOfRangeError):
        OrderItem(quantity=-(2**31) - 1)


def test_assignment_after_construction_is_guarded_as_well() -> None:
    item = OrderItem(quantity=1)
    with pytest.raises(QuantityOutOfRangeError):
        item.quantity = 2**31


def test_a_bigint_money_column_refuses_int64_overflow_with_the_generic_code() -> None:
    order = Order(total_amount=2**63 - 1)
    assert order.total_amount == 2**63 - 1
    with pytest.raises(IntegerOutOfRangeError) as raised:
        order.total_amount = 2**63
    assert raised.value.code == "storage.integer_out_of_range"
    assert not isinstance(raised.value, QuantityOutOfRangeError)


@pytest.mark.parametrize("bad", [True, 1.0, "5"])
def test_a_non_int_value_is_refused_not_coerced(bad: object) -> None:
    with pytest.raises(QuantityOutOfRangeError):
        ensure_in_range(bad, -(2**31), 2**31 - 1, "order_items.quantity", QuantityOutOfRangeError)


def test_the_guard_does_not_touch_other_types() -> None:
    now = datetime(2026, 10, 5, tzinfo=UTC)
    item = OrderItem(id=uuid4(), description="d", created_at=now, quantity=None)
    assert item.quantity is None  # NULL is nullability's business, not the range's


def test_a_sql_expression_assigned_to_a_guarded_attribute_passes_through() -> None:
    """204(c): `attempts = attempts + 1` is SQLAlchemy's atomic server-side increment. It is a
    ClauseElement, not a value: refusing it as "out of range" (the first version of the guard did)
    is false, and it blocks the saga sweeper's natural write."""
    command = SagaCommand(attempts=1)
    command.attempts = SagaCommand.attempts + 1  # must not raise
    command.attempts = literal_column("attempts + 1", Integer)  # a typed ClauseElement
    assert command.attempts is not None
    with pytest.raises(IntegerOutOfRangeError):  # a plain int overflow is still refused
        command.attempts = 2**31


# --- backlog 207: only an Integer-typed expression passes through --------------------------------
# PostgreSQL silently ROUNDS a non-integer expression into an integer column (measured: literal(3.7)
# stored as 4, `x * 0.5` as 0, `x + 0.6` as 1, while a raw 3.7 is refused), so the pass-through is
# gated on the expression's SQL type, not on "is a ClauseElement".
@pytest.mark.parametrize(
    "expression",
    [
        pytest.param(SagaCommand.attempts * 0.5, id="integer column times a float"),
        pytest.param(SagaCommand.attempts + 0.6, id="integer column plus a float"),
        pytest.param(literal(3.7), id="float literal"),
        pytest.param(literal(Decimal("3.7")), id="numeric literal"),
        pytest.param(literal_column("attempts + 1"), id="untyped literal_column (NullType)"),
    ],
)
def test_a_non_integer_typed_expression_is_refused_not_rounded_by_the_engine(
    expression: Any,
) -> None:
    command = SagaCommand(attempts=1)
    with pytest.raises(IntegerOutOfRangeError):
        command.attempts = expression


@pytest.mark.parametrize(
    "expression",
    [
        pytest.param(SagaCommand.attempts + 1, id="integer column plus an int"),
        pytest.param(SagaCommand.attempts - 1, id="integer column minus an int"),
        pytest.param(literal(3), id="int literal"),
        pytest.param(literal_column("attempts + 1", Integer), id="typed literal_column"),
    ],
)
def test_an_integer_typed_expression_still_passes_through(expression: Any) -> None:
    command = SagaCommand(attempts=1)
    command.attempts = expression  # must not raise
    assert command.attempts is expression
