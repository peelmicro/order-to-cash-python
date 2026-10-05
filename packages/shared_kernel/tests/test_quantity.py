"""R3: a quantity is a strictly positive `int`."""

import enum
import math
from decimal import Decimal
from typing import Any

import pytest

from otc_shared_kernel import DomainError, Quantity, QuantityMustBePositiveError


def quantity(value: Any) -> Quantity:
    """Construct with arguments the type checker would refuse (runtime refusal is under test)."""
    return Quantity(value)


QUANTITY_MEMBERS = {
    "value",
    "__post_init__",
    "__str__",
    "__eq__",
    "__hash__",
    "__init__",
    "__repr__",
    "__setattr__",
    "__delattr__",
    "__getstate__",
    "__setstate__",
    "__replace__",
    "__match_args__",
    "__slots__",
    "__dataclass_fields__",
    "__dataclass_params__",
    "__annotate_func__",
    "__annotations_cache__",
    "__static_attributes__",
    "__firstlineno__",
    "__module__",
    "__doc__",
}


class _Count(enum.IntEnum):
    TWO = 2


@pytest.mark.parametrize("value", [1, 2, 12, 10**9, 2**63])
def test_r3_quantity_accepts_a_strictly_positive_int(value: int) -> None:
    assert Quantity(value).value == value
    assert str(Quantity(value)) == str(value)


@pytest.mark.parametrize(
    "bad",
    [
        0,
        -1,
        -(10**9),
        True,
        False,
        1.0,
        2.0,
        2.5,
        0.5,
        math.nan,
        math.inf,
        -math.inf,
        "3",
        "",
        None,
        Decimal(3),
        3 + 0j,
        _Count.TWO,
        [3],
    ],
    ids=lambda v: f"{type(v).__name__}-{v!r}",
)
def test_r3_quantity_refuses_zero_negative_fractional_bool_and_non_int_and_creates_nothing(
    bad: Any,
) -> None:
    with pytest.raises(QuantityMustBePositiveError) as raised:
        quantity(bad)
    assert isinstance(raised.value, DomainError)
    assert raised.value.code == "quantity.must_be_strictly_positive_integer"


def test_r3_quantity_has_no_float_accepting_entry_point() -> None:
    # #8 added `Quantity.From(double)` only because C# cannot say "fractional" in a constructor
    # signature; here the runtime type check refuses 2.5. Every name in `vars(Quantity)` of every
    # kind is allowlisted, so a `from_number`, `__float__` or `_major` fails.
    assert set(vars(Quantity)) == QUANTITY_MEMBERS


def test_quantity_is_immutable_and_compares_by_value() -> None:
    assert Quantity(3) == Quantity(3)
    assert Quantity(3) != Quantity(4)
    assert hash(Quantity(3)) == hash(Quantity(3))
    with pytest.raises(AttributeError):
        Quantity(3).value = 4  # type: ignore[misc]
