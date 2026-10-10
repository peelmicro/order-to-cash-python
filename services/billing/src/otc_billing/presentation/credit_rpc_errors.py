"""Every failure of a Billing request becomes an `RpcError` (`design.md` 8.5; invoice rows 8.4).

Every code here is a saga decision. Orders' adapter splits the twelve codes into nine TERMINAL
(`TERMINAL_RPC_ERROR_CODES`) and three transient (`TIMEOUT`, `UNAVAILABLE`, `INTERNAL_ERROR`), so:

* a transient store failure (`StoreUnavailableError`) is `UNAVAILABLE`, and anything unclassified is
  `INTERNAL_ERROR`: both are retried by the caller;
* a contract violation (no line, a currency mismatch, a malformed request) and a domain refusal
  (including a ledger overflow, which would overflow again on every retry) are terminal;
* `CONFLICT` is produced by NO input on these subjects, nor is `TIMEOUT`;
* a business rejection (`credit.rejected.v1`) is never an `RpcError`: it is the `rejected` outcome.

`INTERNAL_ERROR` never carries the exception's text (it can hold SQL or a path); it is logged.
Messages that name an amount were rendered with the money-text formatter where they were raised
(`BC39`); `details` keep integer minor units or codes.
"""

from datetime import datetime

from otc_billing.application.errors import (
    CreditCurrencyMismatchError,
    CreditLineNotFoundError,
    CreditNotOutstandingError,
    InvoiceCurrencyMismatchError,
    InvoiceNotFoundError,
    PaymentReferenceReusedError,
)
from otc_billing.application.ports.credit_store import StoreUnavailableError
from otc_billing.domain.errors import CreditReleaseUnderflowError, NoActiveHoldError
from otc_billing.domain.invoice_errors import (
    EmptyInvoiceLinesError,
    InvoiceAlreadyPaidError,
    InvoiceLineCurrencyMismatchError,
    InvoicePaymentAmountMismatchError,
    InvoicePaymentCurrencyMismatchError,
    NegativeInvoiceTotalError,
)
from otc_billing.presentation.credit_headers import InvalidCreditHeadersError
from otc_billing.presentation.credit_wire import InvalidCreditRequestError
from otc_billing.presentation.invoice_wire import InvalidInvoiceRequestError
from otc_billing.presentation.payment_wire import InvalidPaymentRequestError
from otc_contracts.generated.asyncapi import Code, RpcError
from otc_shared_kernel import DomainError, UniqueId


def map_error(error: Exception, occurred_at: datetime, correlation_id: UniqueId | None) -> RpcError:
    """The `RpcError` for a failure of the request path. Order matters: the specific refusals come
    before the general ones they are subclasses of."""
    correlation = None if correlation_id is None else correlation_id.value

    def rpc(code: Code, message: str, details: dict[str, object] | None = None) -> RpcError:
        return RpcError(
            code=code,
            message=message,
            details=details,
            correlation_id=correlation,
            occurred_at=occurred_at,
        )

    match error:
        case (
            InvalidCreditRequestError()
            | InvalidInvoiceRequestError()
            | InvalidPaymentRequestError()
            | InvalidCreditHeadersError()
        ):
            return rpc(Code.validation_failed, str(error))
        case CreditLineNotFoundError():
            return rpc(
                Code.not_found,
                error.message,
                {"retailerCode": error.retailer_code, "companyCode": error.company_code},
            )
        case InvoiceNotFoundError():
            return rpc(
                Code.not_found,
                error.message,
                {"invoiceId": error.invoice_id, "invoiceReference": error.invoice_reference},
            )
        case InvoiceAlreadyPaidError():
            # R49: the Gateway maps INVOICE_NOT_PAYABLE (details.code `invoice.already_paid`) to
            # the 409 `INVOICE_ALREADY_PAID` of openapi.yaml 674
            return rpc(Code.invoice_not_payable, error.message, {"code": error.code})
        case InvoicePaymentAmountMismatchError() | InvoicePaymentCurrencyMismatchError():
            return rpc(Code.payment_mismatch, error.message, {"code": error.code})
        case PaymentReferenceReusedError():
            # PRECONDITION_FAILED, never CONFLICT (BC27: this service answers no CONFLICT); the
            # Gateway maps details.code `payment.reference_reused` to openapi.yaml 673
            return rpc(
                Code.precondition_failed,
                error.message,
                {"code": error.code, "paymentReference": error.payment_reference},
            )
        case CreditNotOutstandingError():
            return rpc(Code.precondition_failed, error.message, {"code": error.code})
        case CreditCurrencyMismatchError() | InvoiceCurrencyMismatchError():
            return rpc(
                Code.validation_failed,
                error.message,
                {"expected": error.expected, "received": error.received},
            )
        case (
            EmptyInvoiceLinesError()
            | InvoiceLineCurrencyMismatchError()
            | NegativeInvoiceTotalError()
        ):
            # statements about the request's lines; unreachable past the edge (BI2, BI33)
            return rpc(Code.validation_failed, error.message, {"code": error.code})
        case CreditReleaseUnderflowError() | NoActiveHoldError():
            return rpc(Code.precondition_failed, error.message, {"code": error.code})
        case DomainError():
            # includes CreditLedgerOverflowError and InvoiceTotalOverflowError: terminal, they
            # overflow again on every retry
            return rpc(Code.domain_error, error.message, {"code": error.code})
        case StoreUnavailableError():
            return rpc(Code.unavailable, str(error))
        case _:
            return rpc(Code.internal_error, "The request could not be processed.")
