"""`Money`: int minor units plus an ISO 4217 alpha-3 code (R1, R2; invariants M1-M4).

M1 -- `amount` is an `int` count of minor units; there is no float, Decimal or major-unit surface.
M2 -- adding, subtracting or ordering two currencies raises `CurrencyMismatchError`. Equality
      (`==`) is a different question ("are these the same value?") and answers `False`, exactly as
      #7's `equals` and #8's record-struct equality do; ordering ("which is larger?") needs a rate
      this model does not have, so it raises.
M3 -- `add`, `subtract` and `multiply(Quantity)` are closed; division is not offered (no `/`, `//`,
      `%`, `divmod`, `float()`, `int()`, `round()`).
M4 -- a negative amount is representable; rejecting a negative *total* is the aggregate's rule.
"""

from dataclasses import dataclass

from otc_shared_kernel.errors import (
    CurrencyMismatchError,
    InvalidCurrencyCodeError,
    InvalidMoneyAmountError,
)
from otc_shared_kernel.quantity import Quantity

MIN_MINOR_UNITS = -(1 << 63)
MAX_MINOR_UNITS = (1 << 63) - 1  # the write model's bigint column


def _is_alpha3(currency: object) -> bool:
    return (
        type(currency) is str
        and len(currency) == 3
        and all("A" <= character <= "Z" for character in currency)
    )


@dataclass(frozen=True, slots=True)
class Money:
    """Format-validated currency (three ASCII capitals); whether a code is *seeded* is the Orders
    reference catalogue's concern, not the value object's (#7 `money.ts:4`, #8 `Money.cs:28`)."""

    amount: int
    currency: str

    def __post_init__(self) -> None:
        # `type(...) is int` refuses bool (an int subclass) and integral floats such as 100.0.
        if type(self.amount) is not int or not MIN_MINOR_UNITS <= self.amount <= MAX_MINOR_UNITS:
            raise InvalidMoneyAmountError(self.amount)
        if not _is_alpha3(self.currency):
            raise InvalidCurrencyCodeError(self.currency)

    @classmethod
    def zero(cls, currency: str) -> Money:
        return cls(0, currency)

    @property
    def is_negative(self) -> bool:
        return self.amount < 0

    @property
    def is_zero(self) -> bool:
        return self.amount == 0

    def add(self, other: Money) -> Money:
        self._require_same_currency(other)
        return Money(self.amount + other.amount, self.currency)

    def subtract(self, other: Money) -> Money:
        self._require_same_currency(other)
        return Money(self.amount - other.amount, self.currency)

    def multiply(self, quantity: Quantity) -> Money:
        return Money(self.amount * quantity.value, self.currency)

    def compare(self, other: Money) -> int:
        """-1, 0 or 1; raises on a currency mismatch (M2)."""
        self._require_same_currency(other)
        return (self.amount > other.amount) - (self.amount < other.amount)

    def __add__(self, other: object) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        return self.add(other)

    def __sub__(self, other: object) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        return self.subtract(other)

    def __mul__(self, other: object) -> Money:
        if not isinstance(other, Quantity):
            return NotImplemented
        return self.multiply(other)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        return self.compare(other) < 0

    def __le__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        return self.compare(other) <= 0

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        return self.compare(other) > 0

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        return self.compare(other) >= 0

    def __str__(self) -> str:
        return f"{self.amount} {self.currency}"

    def _require_same_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            raise CurrencyMismatchError(self.currency, other.currency)
