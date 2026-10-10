"""The application errors of a credit or invoice request (`design.md` 5.5, #8 section 5.4's
placement).

All are contract violations, not statements about the buyer's credit: no ledger entry and no fact
(BC3, BC4).
"""

from otc_shared_kernel import DomainError


class CreditLineNotFoundError(DomainError):
    CODE = "credit_line.not_found"

    def __init__(self, retailer_code: str, company_code: str) -> None:
        super().__init__(
            self.CODE,
            f"No credit line exists for retailer {retailer_code!r} and company {company_code!r}.",
        )
        self.retailer_code = retailer_code
        self.company_code = company_code


class CreditCurrencyMismatchError(DomainError):
    CODE = "credit.currency_mismatch"

    def __init__(self, expected: str, received: str) -> None:
        super().__init__(
            self.CODE,
            f"The hold is in {received!r} but the credit line is in {expected!r}.",
        )
        self.expected = expected
        self.received = received


class InvoiceCurrencyMismatchError(DomainError):
    CODE = "invoice.currency_mismatch"

    def __init__(self, expected: str, received: str) -> None:
        super().__init__(
            self.CODE,
            f"The invoice is in {received!r} but the credit line is in {expected!r}.",
        )
        self.expected = expected
        self.received = received


class InvoiceNotFoundError(DomainError):
    """The invoice a remittance names does not exist (`billing.payment.register`): a contract
    violation, nothing written."""

    CODE = "invoice.not_found"

    def __init__(self, invoice_id: str | None, invoice_reference: str | None) -> None:
        super().__init__(
            self.CODE,
            f"No invoice matches id {invoice_id!r} and reference {invoice_reference!r}.",
        )
        self.invoice_id = invoice_id
        self.invoice_reference = invoice_reference


class PaymentReferenceReusedError(DomainError):
    """One `paymentReference` used to mean two different things: recorded against another invoice,
    or against the same invoice with another amount or currency (R48; `openapi.yaml` 673)."""

    CODE = "payment.reference_reused"

    def __init__(self, payment_reference: str) -> None:
        super().__init__(
            self.CODE,
            f"Payment reference {payment_reference!r} is already recorded for another invoice "
            "or another amount.",
        )
        self.payment_reference = payment_reference


class CreditNotOutstandingError(DomainError):
    """The order's credit exposure is not outstanding at payment time (`release` answered `None`):
    an issued invoice implies an outstanding hold, so the ledger is inconsistent. The payment is
    refused with nothing changed, because accepting it would emit `payment.received.v1` without
    its `credit.released.v1` and strand the order at `paid` (#8's N3, #7 the same)."""

    CODE = "credit.not_outstanding"

    def __init__(self, order_reference: str) -> None:
        super().__init__(
            self.CODE,
            f"Order {order_reference} has no outstanding credit exposure to release; "
            "the payment was not recorded.",
        )
        self.order_reference = order_reference
