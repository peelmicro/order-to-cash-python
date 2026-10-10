"""The nine domain errors of the buyer-credit aggregate (`specs/billing_credit/design.md` 5.5).

Codes are `<subject>.<snake_case_reason>` (Orders' convention, inherited from the kernel). A message
carries the specifics; `code` is what machines branch on. Every message that names an amount renders
it with the shared ISO 4217 money-text formatter (`BC39`, #8 id 102), never as raw minor units; the
machine-readable attributes (`requested`, `available`, ...) stay integer minor units.
"""

from otc_shared_kernel import DomainError, format_money


class CreditLimitExceededError(DomainError):
    CODE = "credit.limit_exceeded"

    def __init__(self, requested: int, available: int, currency: str) -> None:
        super().__init__(
            self.CODE,
            f"A hold of {format_money(requested, currency)} exceeds the available credit of "
            f"{format_money(available, currency)}.",
        )
        self.requested = requested
        self.available = available
        self.currency = currency


class CreditRefusalMismatchError(DomainError):
    CODE = "credit.refusal_mismatch"

    def __init__(self, reason: str, requested: int, available: int, currency: str) -> None:
        super().__init__(
            self.CODE,
            f"A hold of {format_money(requested, currency)} cannot be refused as {reason!r}: the "
            f"available credit is {format_money(available, currency)}.",
        )
        self.reason = reason
        self.requested = requested
        self.available = available
        self.currency = currency


class CreditReleaseUnderflowError(DomainError):
    CODE = "credit.release_underflow"

    def __init__(self, order_reference: str, exposure: int, currency: str) -> None:
        super().__init__(
            self.CODE,
            f"Order {order_reference} has a negative exposure of "
            f"{format_money(exposure, currency)}: a release would drive it below zero.",
        )
        self.order_reference = order_reference
        self.exposure = exposure
        self.currency = currency


class NoActiveHoldError(DomainError):
    CODE = "credit.no_active_hold"

    def __init__(self, order_reference: str) -> None:
        super().__init__(
            self.CODE,
            f"Order {order_reference} has no active hold: it was never held, or its hold was "
            "already consumed or released.",
        )
        self.order_reference = order_reference


class InvalidBuyerCreditSnapshotError(DomainError):
    CODE = "buyer_credit.invalid_snapshot"

    def __init__(self, reason: str) -> None:
        super().__init__(self.CODE, f"The stored credit line cannot be restored: {reason}.")
        self.reason = reason


class FactAggregateMismatchError(DomainError):
    CODE = "credit.fact_aggregate_mismatch"

    def __init__(self, credit_id: object, fact_aggregate_id: object) -> None:
        super().__init__(
            self.CODE,
            f"A fact about aggregate {fact_aggregate_id} cannot be recorded on credit line "
            f"{credit_id}.",
        )


class CreditLedgerOverflowError(DomainError):
    CODE = "credit.ledger_overflow"

    def __init__(self, what: str) -> None:
        super().__init__(
            self.CODE,
            f"The {what} exceeds the range of a signed 64-bit amount of minor units.",
        )
        self.what = what


class UnknownCreditEntryTypeError(DomainError):
    CODE = "credit_entry.unknown_type"

    def __init__(self, token: object) -> None:
        super().__init__(self.CODE, f"{token!r} is not a credit ledger entry type.")


class NegativeLedgerAmountError(DomainError):
    CODE = "credit_entry.negative_amount"

    def __init__(self, amount: int, currency: str) -> None:
        super().__init__(
            self.CODE,
            f"A ledger entry cannot carry the negative amount {format_money(amount, currency)}: "
            "it would raise the available credit.",
        )
        self.amount = amount
        self.currency = currency
