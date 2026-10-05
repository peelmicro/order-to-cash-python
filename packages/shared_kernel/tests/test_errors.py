"""Stable domain-error codes."""

from typing import Any

import pytest

from otc_shared_kernel import (
    CurrencyMismatchError,
    DomainError,
    InvalidBusinessReferenceError,
    InvalidCurrencyCodeError,
    InvalidGlnError,
    InvalidMoneyAmountError,
    InvalidUniqueIdError,
    QuantityMustBePositiveError,
)


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (InvalidCurrencyCodeError("x"), "money.invalid_currency_code"),
        (InvalidMoneyAmountError(1.5), "money.invalid_amount"),
        (CurrencyMismatchError("EUR", "GBP"), "money.cross_currency"),
        (QuantityMustBePositiveError(0), "quantity.must_be_strictly_positive_integer"),
        (InvalidGlnError("x", "why"), "gln.invalid"),
        (InvalidUniqueIdError("x"), "unique_id.invalid"),
        (InvalidBusinessReferenceError("order_number.invalid", "ORD", "x"), "order_number.invalid"),
    ],
    ids=lambda v: type(v).__name__ if isinstance(v, DomainError) else v,
)
def test_every_kernel_error_is_a_domain_error_with_its_literal_stable_code(
    error: DomainError, code: str
) -> None:
    assert isinstance(error, DomainError)
    assert error.code == code
    assert str(error) == error.message
    assert error.message


@pytest.mark.parametrize("blank", ["", "  ", "\t", None, 5])
def test_a_domain_error_refuses_a_blank_or_non_str_code(blank: Any) -> None:
    with pytest.raises(ValueError, match="code"):
        DomainError(blank, "message")
