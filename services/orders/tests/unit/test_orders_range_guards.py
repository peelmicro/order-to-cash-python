"""Acceptance 5 (unit part) - the write-boundary range guard, with no database.

A mapped integer attribute refuses a value its column cannot hold with a `DomainError` carrying a
stable code, at assignment, before any statement exists.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import literal_column

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
    command.attempts = literal_column("attempts + 1")  # any ClauseElement
    assert command.attempts is not None
    with pytest.raises(IntegerOutOfRangeError):  # a plain int overflow is still refused
        command.attempts = 2**31
