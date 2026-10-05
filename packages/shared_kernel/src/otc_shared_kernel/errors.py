"""Domain errors: every refusal raised inside the domain carries a stable, machine-readable `code`.

Codes are part of the contract (they are mapped to HTTP problems and asserted by tests), so they
are literals here and never derived from a class name. Most are the strings #8 used
(`money.cross_currency`, `money.invalid_currency_code`, `gln.invalid`, `order_number.invalid`,
`quantity.must_be_strictly_positive_integer`). New in #9: `money.invalid_amount` (the int-only /
int64 boundary, which #8 expressed as the type system), `unique_id.invalid` (#8's is
`unique_id.empty`, `../order-to-cash-dotnet/src/SharedKernel/Errors/InvalidUniqueIdError.cs:11`),
and `despatch_reference.invalid`, `invoice_reference.invalid`, `credit_line_reference.invalid`.
"""


class DomainError(Exception):
    """Base of every domain refusal. `code` is stable and never blank."""

    def __init__(self, code: str, message: str) -> None:
        if type(code) is not str or not code.strip():
            raise ValueError("a domain error code must be a non-blank string")
        super().__init__(message)
        self.code = code
        self.message = message


class InvalidCurrencyCodeError(DomainError):
    CODE = "money.invalid_currency_code"

    def __init__(self, offending: object) -> None:
        super().__init__(
            self.CODE,
            f"{offending!r} is not a valid ISO 4217 alpha-3 currency code (three letters A-Z)",
        )


class InvalidMoneyAmountError(DomainError):
    CODE = "money.invalid_amount"

    def __init__(self, offending: object) -> None:
        super().__init__(
            self.CODE,
            f"{offending!r} is not a valid money amount: it must be an int count of minor units "
            "within the signed 64-bit range",
        )


class CurrencyMismatchError(DomainError):
    CODE = "money.cross_currency"

    def __init__(self, left_currency: str, right_currency: str) -> None:
        super().__init__(
            self.CODE,
            "cannot combine or compare amounts in different currencies: "
            f"{left_currency!r} and {right_currency!r}",
        )
        self.left_currency = left_currency
        self.right_currency = right_currency


class QuantityMustBePositiveError(DomainError):
    CODE = "quantity.must_be_strictly_positive_integer"

    def __init__(self, offending: object) -> None:
        super().__init__(
            self.CODE, f"{offending!r} is not a valid quantity: it must be a strictly positive int"
        )


class InvalidGlnError(DomainError):
    CODE = "gln.invalid"

    def __init__(self, offending: object, reason: str) -> None:
        super().__init__(self.CODE, f"{offending!r} is not a valid GLN: {reason}")


class InvalidBusinessReferenceError(DomainError):
    """A malformed or non-positive business reference; `code` is per reference kind."""

    def __init__(self, code: str, prefix: str, offending: object) -> None:
        super().__init__(
            code,
            f"{offending!r} is not a valid {prefix}- business reference: the prefix, then a "
            "strictly positive sequence zero-padded to at least six digits, without extra zeros",
        )


class InvalidUniqueIdError(DomainError):
    CODE = "unique_id.invalid"

    def __init__(self, offending: object) -> None:
        super().__init__(self.CODE, f"{offending!r} is not a valid, non-nil UUID")
