"""One case per row of the error mapping (`design.md` 8.5): code AND details (task E6; BC39).

Loop scope: nothing here is async.
"""

import uuid
from datetime import UTC, datetime

import pytest

from otc_billing.application.errors import (
    CreditCurrencyMismatchError,
    CreditLineNotFoundError,
    CreditNotOutstandingError,
    InvoiceCurrencyMismatchError,
    InvoiceNotFoundError,
    PaymentReferenceReusedError,
)
from otc_billing.application.ports.credit_store import StoreUnavailableError
from otc_billing.domain.errors import (
    CreditLedgerOverflowError,
    CreditLimitExceededError,
    CreditRefusalMismatchError,
    CreditReleaseUnderflowError,
    FactAggregateMismatchError,
    InvalidBuyerCreditSnapshotError,
    NegativeLedgerAmountError,
    NoActiveHoldError,
    UnknownCreditEntryTypeError,
)
from otc_billing.domain.invoice_errors import (
    EmptyInvoiceLinesError,
    InvalidInvoiceSnapshotError,
    InvalidInvoiceStateError,
    InvoiceAlreadyPaidError,
    InvoiceLineCurrencyMismatchError,
    InvoicePaymentAmountMismatchError,
    InvoicePaymentCurrencyMismatchError,
    InvoiceTotalOverflowError,
    NegativeInvoiceTotalError,
    UnknownInvoiceStatusError,
)
from otc_billing.infrastructure.persistence.range_guards import (
    IntegerOutOfRangeError,
    QuantityOutOfRangeError,
)
from otc_billing.presentation.credit_headers import InvalidCreditHeadersError
from otc_billing.presentation.credit_rpc_errors import map_error
from otc_billing.presentation.credit_wire import InvalidCreditRequestError
from otc_billing.presentation.invoice_wire import InvalidInvoiceRequestError
from otc_billing.presentation.payment_wire import InvalidPaymentRequestError
from otc_contracts.generated.asyncapi import Code, RpcError
from otc_shared_kernel import DomainError, UniqueId

NOW = datetime(2026, 10, 8, 9, 0, 0, tzinfo=UTC)
CORRELATION = UniqueId(uuid.UUID(int=0xC0))


def mapped(error: Exception) -> RpcError:
    return map_error(error, NOW, CORRELATION)


ROWS: list[tuple[str, Exception, Code, dict[str, object] | None]] = [
    ("invalid request", InvalidCreditRequestError("bad"), Code.validation_failed, None),
    ("invalid headers", InvalidCreditHeadersError("bad"), Code.validation_failed, None),
    (
        "no credit line",
        CreditLineNotFoundError("RETAIL-77", "SUPPLY-CO"),
        Code.not_found,
        {"retailerCode": "RETAIL-77", "companyCode": "SUPPLY-CO"},
    ),
    (
        "currency mismatch",
        CreditCurrencyMismatchError("EUR", "USD"),
        Code.validation_failed,
        {"expected": "EUR", "received": "USD"},
    ),
    (
        "release underflow",
        CreditReleaseUnderflowError("ORD-000101", -50, "EUR"),
        Code.precondition_failed,
        {"code": "credit.release_underflow"},
    ),
    (
        "no active hold",
        NoActiveHoldError("ORD-000101"),
        Code.precondition_failed,
        {"code": "credit.no_active_hold"},
    ),
    (
        "ledger overflow",
        CreditLedgerOverflowError("committed exposure"),
        Code.domain_error,
        {"code": "credit.ledger_overflow"},
    ),
    (
        "range guard",
        IntegerOutOfRangeError("credit_items.amount", 2**63, -(2**63), 2**63 - 1),
        Code.domain_error,
        {"code": "storage.integer_out_of_range"},
    ),
    (
        "unknown entry type",
        UnknownCreditEntryTypeError("Hold"),
        Code.domain_error,
        {"code": "credit_entry.unknown_type"},
    ),
    (
        "invalid snapshot",
        InvalidBuyerCreditSnapshotError("x"),
        Code.domain_error,
        {"code": "buyer_credit.invalid_snapshot"},
    ),
    (
        "limit exceeded",
        CreditLimitExceededError(5, 1, "EUR"),
        Code.domain_error,
        {"code": "credit.limit_exceeded"},
    ),
    # ---- feature 21 (design 8.4): one row per invoice failure
    ("invalid invoice request", InvalidInvoiceRequestError("bad"), Code.validation_failed, None),
    (
        "invoice currency mismatch",
        InvoiceCurrencyMismatchError("EUR", "USD"),
        Code.validation_failed,
        {"expected": "EUR", "received": "USD"},
    ),
    (
        "empty invoice lines",
        EmptyInvoiceLinesError(),
        Code.validation_failed,
        {"code": "invoice.empty_lines"},
    ),
    (
        "invoice line currency mismatch",
        InvoiceLineCurrencyMismatchError("EUR", "USD"),
        Code.validation_failed,
        {"code": "invoice.line_currency_mismatch"},
    ),
    (
        "negative invoice total",
        NegativeInvoiceTotalError(100, 200, "EUR"),
        Code.validation_failed,
        {"code": "invoice.negative_total"},
    ),
    (
        "invoice total overflow",
        InvoiceTotalOverflowError("amount"),
        Code.domain_error,
        {"code": "invoice.total_overflow"},
    ),
    (
        "invalid invoice snapshot",
        InvalidInvoiceSnapshotError("x"),
        Code.domain_error,
        {"code": "invoice.invalid_snapshot"},
    ),
    (
        "invalid invoice state",
        InvalidInvoiceStateError(None),
        Code.domain_error,
        {"code": "invoice_state.invalid_paid_at"},
    ),
    (
        "unknown invoice status",
        UnknownInvoiceStatusError("Paid"),
        Code.domain_error,
        {"code": "invoice_status.unknown"},
    ),
    (
        "invoice already paid",
        InvoiceAlreadyPaidError("INV-000001"),
        Code.invoice_not_payable,
        {"code": "invoice.already_paid"},
    ),
    (
        "payment amount mismatch",
        InvoicePaymentAmountMismatchError(100, 200, "EUR"),
        Code.payment_mismatch,
        {"code": "invoice.payment_amount_mismatch"},
    ),
    (
        "payment currency mismatch",
        InvoicePaymentCurrencyMismatchError("EUR", "USD"),
        Code.payment_mismatch,
        {"code": "invoice.payment_currency_mismatch"},
    ),
    (
        "quantity range guard",
        QuantityOutOfRangeError("invoice_items.units", 2**31, 1, 2**31 - 1),
        Code.domain_error,
        {"code": "quantity.out_of_range"},
    ),
    # ---- feature 22: one row per remittance failure (R49; asyncapi.yaml 2856 - 2857)
    ("invalid payment request", InvalidPaymentRequestError("bad"), Code.validation_failed, None),
    (
        "invoice not found",
        InvoiceNotFoundError("0b0c0d0e-0000-4000-8000-000000000001", None),
        Code.not_found,
        {"invoiceId": "0b0c0d0e-0000-4000-8000-000000000001", "invoiceReference": None},
    ),
    (
        "payment reference reused",
        PaymentReferenceReusedError("BANK-REF-77"),
        Code.precondition_failed,
        {"code": "payment.reference_reused", "paymentReference": "BANK-REF-77"},
    ),
    (
        "credit not outstanding",
        CreditNotOutstandingError("ORD-000101"),
        Code.precondition_failed,
        {"code": "credit.not_outstanding"},
    ),
    ("store unavailable", StoreUnavailableError("40P01"), Code.unavailable, None),
    ("anything else", RuntimeError("select * from secrets"), Code.internal_error, None),
]


@pytest.mark.parametrize(("label", "error", "code", "details"), ROWS, ids=[r[0] for r in ROWS])
def test_each_row_of_the_mapping_answers_its_code_and_details(
    label: str, error: Exception, code: Code, details: dict[str, object] | None
) -> None:
    rpc = mapped(error)
    assert rpc.code is code, label
    assert rpc.details == details, label
    assert rpc.correlation_id == CORRELATION.value
    assert rpc.occurred_at == NOW
    assert rpc.message


def test_an_internal_error_never_carries_the_exceptions_text() -> None:
    assert "secrets" not in mapped(RuntimeError("select * from secrets")).message


def test_the_correlation_id_is_optional() -> None:
    assert map_error(InvalidCreditRequestError("x"), NOW, None).correlation_id is None


def test_no_row_of_the_mapping_produces_a_code_that_is_never_produced() -> None:
    never = {
        Code.conflict,
        Code.timeout,
        Code.order_not_cancellable,
        Code.stock_unavailable,
    }
    produced = {mapped(error).code for _, error, _, _ in ROWS}
    assert produced.isdisjoint(never)


def test_bc39_every_error_message_naming_an_amount_renders_it_with_the_money_text_formatter() -> (
    None
):
    limit = CreditLimitExceededError(9245, 100, "EUR")
    assert "92.45 EUR" in limit.message
    assert "1.00 EUR" in limit.message
    assert "9245" not in limit.message, "a raw minor-unit amount reached the message"
    # machine-readable fields stay integer minor units
    assert (limit.requested, limit.available) == (9245, 100)

    assert "9 245 JPY" in CreditLimitExceededError(9245, 100, "JPY").message
    assert "9.245 BHD" in CreditLimitExceededError(9245, 100, "BHD").message

    named: list[DomainError] = [
        CreditRefusalMismatchError("over_limit", 9245, 100, "EUR"),
        CreditReleaseUnderflowError("ORD-000101", -9245, "EUR"),
        NegativeLedgerAmountError(-9245, "EUR"),
    ]
    for error in named:
        assert "92.45 EUR" in error.message or "-92.45 EUR" in error.message, type(error).__name__
        assert "9245" not in error.message, type(error).__name__
    # the rpc message is the domain message, so the problem document inherits the rendering
    assert "92.45 EUR" in mapped(limit).message
    assert FactAggregateMismatchError("a", "b").code == "credit.fact_aggregate_mismatch"


def test_bi36_invoice_error_messages_render_amounts_with_the_money_text_formatter() -> None:
    negative = {
        "EUR": ("92.45 EUR", "184.90 EUR"),
        "JPY": ("9 245 JPY", "18 490 JPY"),
        "BHD": ("9.245 BHD", "18.490 BHD"),
    }
    for currency, (amount_text, discount_text) in negative.items():
        error = NegativeInvoiceTotalError(9245, 18490, currency)
        assert amount_text in error.message, f"{currency}: {error.message}"
        assert discount_text in error.message, f"{currency}: {error.message}"
        assert "9245" not in error.message, f"BI36: a raw minor-unit amount reached {currency}"
        assert "18490" not in error.message, f"BI36: a raw minor-unit amount reached {currency}"
        # machine-readable attributes stay integer minor units
        assert (error.amount, error.discount) == (9245, 18490)

        mismatch = InvoicePaymentAmountMismatchError(9245, 18490, currency)
        assert amount_text in mismatch.message, f"{currency}: {mismatch.message}"
        assert discount_text in mismatch.message, f"{currency}: {mismatch.message}"
        assert "9245" not in mismatch.message
        assert "18490" not in mismatch.message
        assert (mismatch.expected, mismatch.received) == (9245, 18490)
        # the rpc message is the domain message, so the problem document inherits the rendering
        assert amount_text in mapped(error).message
        assert error.code == "invoice.negative_total"
