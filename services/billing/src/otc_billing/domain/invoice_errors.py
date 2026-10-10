"""The ten domain errors of the invoice aggregate (`specs/billing_invoicing/design.md` 5.6).

Codes are dotted lower-case literals (Orders' and feature 19's convention); `code` is what machines
branch on. Every message that names an amount renders it with the shared ISO 4217 money-text
formatter (`BI36`, #8 id 102), never as raw minor units; the machine-readable attributes
(`amount`, `discount`, ...) stay integer minor units. The application-level
`InvoiceCurrencyMismatchError` lives in `application/errors.py`; `NoActiveHoldError` and
`CreditLineNotFoundError` are reused from feature 19.
"""

from otc_shared_kernel import DomainError, format_money


class EmptyInvoiceLinesError(DomainError):
    CODE = "invoice.empty_lines"

    def __init__(self) -> None:
        super().__init__(self.CODE, "An invoice needs at least one line.")


class InvoiceLineCurrencyMismatchError(DomainError):
    CODE = "invoice.line_currency_mismatch"

    def __init__(self, expected: str, received: str) -> None:
        super().__init__(
            self.CODE,
            f"An amount in {received!r} cannot be part of an invoice in {expected!r}.",
        )
        self.expected = expected
        self.received = received


class NegativeInvoiceTotalError(DomainError):
    CODE = "invoice.negative_total"

    def __init__(self, amount: int, discount: int, currency: str) -> None:
        super().__init__(
            self.CODE,
            f"A discount of {format_money(discount, currency)} exceeds the invoice amount of "
            f"{format_money(amount, currency)}: the total would be negative.",
        )
        self.amount = amount
        self.discount = discount
        self.currency = currency


class InvoiceTotalOverflowError(DomainError):
    CODE = "invoice.total_overflow"

    def __init__(self, what: str) -> None:
        super().__init__(
            self.CODE,
            f"The invoice {what} exceeds the range of a signed 64-bit amount of minor units.",
        )
        self.what = what


class InvalidInvoiceSnapshotError(DomainError):
    CODE = "invoice.invalid_snapshot"

    def __init__(self, reason: str) -> None:
        super().__init__(self.CODE, f"The stored invoice cannot be restored: {reason}.")
        self.reason = reason


class InvalidInvoiceStateError(DomainError):
    CODE = "invoice_state.invalid_paid_at"

    def __init__(self, offending: object) -> None:
        super().__init__(
            self.CODE,
            f"A paid invoice needs a timezone-aware instant, not {offending!r}.",
        )


class UnknownInvoiceStatusError(DomainError):
    CODE = "invoice_status.unknown"

    def __init__(self, token: object) -> None:
        super().__init__(self.CODE, f"{token!r} is not an invoice status.")


class InvoiceAlreadyPaidError(DomainError):
    CODE = "invoice.already_paid"

    def __init__(self, invoice_reference: str) -> None:
        super().__init__(self.CODE, f"Invoice {invoice_reference} is already paid.")
        self.invoice_reference = invoice_reference


class InvoicePaymentAmountMismatchError(DomainError):
    CODE = "invoice.payment_amount_mismatch"

    def __init__(self, expected: int, received: int, currency: str) -> None:
        super().__init__(
            self.CODE,
            f"A payment of {format_money(received, currency)} does not settle an invoice of "
            f"{format_money(expected, currency)}.",
        )
        self.expected = expected
        self.received = received
        self.currency = currency


class InvoicePaymentCurrencyMismatchError(DomainError):
    CODE = "invoice.payment_currency_mismatch"

    def __init__(self, expected: str, received: str) -> None:
        super().__init__(
            self.CODE,
            f"A payment in {received!r} cannot settle an invoice in {expected!r}.",
        )
        self.expected = expected
        self.received = received
