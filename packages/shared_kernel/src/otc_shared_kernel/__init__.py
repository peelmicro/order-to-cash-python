"""The Order-To-Cash shared kernel: dependency-free value objects and domain base types."""

from otc_shared_kernel.business_reference import (
    BusinessReference,
    CreditLineReference,
    DespatchReference,
    InvoiceReference,
    OrderNumber,
)
from otc_shared_kernel.currency_exponent import (
    DEFAULT_EXPONENT,
    NON_DEFAULT_EXPONENTS,
    exponent_of,
)
from otc_shared_kernel.entity import AggregateRoot, Entity
from otc_shared_kernel.errors import (
    CurrencyMismatchError,
    DomainError,
    InvalidBusinessReferenceError,
    InvalidCurrencyCodeError,
    InvalidGlnError,
    InvalidMoneyAmountError,
    InvalidUniqueIdError,
    QuantityMustBePositiveError,
)
from otc_shared_kernel.gln import GLN
from otc_shared_kernel.money import Money
from otc_shared_kernel.quantity import Quantity
from otc_shared_kernel.unique_id import UniqueId

__all__ = [
    "DEFAULT_EXPONENT",
    "GLN",
    "NON_DEFAULT_EXPONENTS",
    "AggregateRoot",
    "BusinessReference",
    "CreditLineReference",
    "CurrencyMismatchError",
    "DespatchReference",
    "DomainError",
    "Entity",
    "InvalidBusinessReferenceError",
    "InvalidCurrencyCodeError",
    "InvalidGlnError",
    "InvalidMoneyAmountError",
    "InvalidUniqueIdError",
    "InvoiceReference",
    "Money",
    "OrderNumber",
    "Quantity",
    "QuantityMustBePositiveError",
    "UniqueId",
    "exponent_of",
]
