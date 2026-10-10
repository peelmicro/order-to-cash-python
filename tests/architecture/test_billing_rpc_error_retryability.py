"""BC27 / L23: a transient Billing failure maps to a code Orders' saga adapter RETRIES.

The two services are imported side by side (tests are outside import-linter's `root_packages`
contracts, which keep services from importing each other). The terminal set is read from Orders'
own module, `TERMINAL_RPC_ERROR_CODES`, never a retyped list (#8 id 51).

New in Billing: the input population includes EVERY `DomainError` subclass defined anywhere in
`otc_billing`, found by a `__subclasses__` walk and counted against a literal, so an error cannot be
added without its row here (and so without its code being a decision).

Feature 21 CHANGED THE INSTRUMENT (changing an instrument swaps its premises), so the new premises
are listed and each is armed (`progress/impl_billing_invoicing.md`, E6):

* the walk imports EVERY module of the package (`pkgutil.walk_packages`, `onerror` raising), so an
  error in a module nobody named (`domain/invoice_errors.py`, `range_guards.py`) is in the
  population: it was invisible to the old two-module walk;
* a module that cannot be imported FAILS the walk (the import is not inside a `try`), it does not
  shrink the population;
* every walked class has an instance in `EVERY_INPUT` (the set-equality assertion), and the expected
  count is a literal re-derived from the classes on disk (24).
"""

import importlib
import pkgutil
import uuid
from datetime import UTC, datetime

import otc_billing
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
from otc_billing.infrastructure.persistence.credit_transactions import (
    CONNECTION_EXCEPTION_CLASS,
    TRANSIENT_SQLSTATES,
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
from otc_contracts.generated.asyncapi import Code
from otc_orders.infrastructure.messaging.nats_saga_commands import TERMINAL_RPC_ERROR_CODES
from otc_shared_kernel import DomainError, UniqueId

NOW = datetime(2026, 10, 8, 9, 0, 0, tzinfo=UTC)
CORRELATION = UniqueId(uuid.UUID(int=0xC0))

TRANSIENT_STATES = [*sorted(TRANSIENT_SQLSTATES), CONNECTION_EXCEPTION_CLASS + "006"]
TRANSIENT_STORE_FAILURES: list[Exception] = [
    *(StoreUnavailableError(state) for state in TRANSIENT_STATES),
    RuntimeError("an unclassified failure"),  # INTERNAL_ERROR: also retried
]
DOMAIN_ERRORS: list[DomainError] = [
    CreditLimitExceededError(5, 1, "EUR"),
    CreditRefusalMismatchError("over_limit", 5, 1, "EUR"),
    CreditReleaseUnderflowError("ORD-000101", -5, "EUR"),
    NoActiveHoldError("ORD-000101"),
    InvalidBuyerCreditSnapshotError("x"),
    FactAggregateMismatchError("a", "b"),
    CreditLedgerOverflowError("x"),
    UnknownCreditEntryTypeError("x"),
    NegativeLedgerAmountError(-5, "EUR"),
    CreditLineNotFoundError("RETAIL-77", "SUPPLY-CO"),
    CreditCurrencyMismatchError("EUR", "USD"),
    # feature 21 (design 5.6, 8.4)
    InvoiceCurrencyMismatchError("EUR", "USD"),
    EmptyInvoiceLinesError(),
    InvoiceLineCurrencyMismatchError("EUR", "USD"),
    NegativeInvoiceTotalError(100, 200, "EUR"),
    InvoiceTotalOverflowError("amount"),
    InvalidInvoiceSnapshotError("x"),
    InvalidInvoiceStateError(None),
    UnknownInvoiceStatusError("Paid"),
    InvoiceAlreadyPaidError("INV-000001"),
    InvoicePaymentAmountMismatchError(100, 200, "EUR"),
    InvoicePaymentCurrencyMismatchError("EUR", "USD"),
    # feature 22 (`billing.payment.register`): see PAYMENT_REFUSALS for the table
    InvoiceNotFoundError("0b0c0d0e-0000-4000-8000-000000000001", None),
    PaymentReferenceReusedError("BANK-REF-77"),
    CreditNotOutstandingError("ORD-000101"),
    # the write-boundary range guards: real inputs the two-module walk never saw
    IntegerOutOfRangeError("credit_items.amount", 2**63, -(2**63), 2**63 - 1),
    QuantityOutOfRangeError("invoice_items.units", 2**31, 1, 2**31 - 1),
]
EVERY_INPUT: list[Exception] = [
    *TRANSIENT_STORE_FAILURES,
    InvalidCreditRequestError("x"),
    InvalidInvoiceRequestError("x"),
    InvalidPaymentRequestError("x"),
    InvalidCreditHeadersError("x"),
    *DOMAIN_ERRORS,
]
# 9 (domain/errors) + 6 (application/errors) + 10 (domain/invoice_errors) + 2 (range_guards),
# re-derived from the classes on disk (feature 22 added three to application/errors)
EXPECTED_DOMAIN_ERROR_COUNT = 27

# Feature 22: EVERY refusal `billing.payment.register` can answer is a retry-or-reject decision for
# its caller (the Gateway today; a caller that retried would hammer a refusal that can never turn
# into a yes). One row per refusal: the error, the `RpcError` code it is answered with, and
# whether the caller retries. All are TERMINAL in Orders' own set (the only classifier that exists;
# the Gateway's mapping is feature 28's); the first column is the decision, the test below reads
# the answered code from `map_error` and the terminal set from Orders, never a retyped list.
#
#   refusal                          | RpcError code       | Gateway maps it to         | retry
#   ---------------------------------+---------------------+----------------------------+------
#   a malformed request or headers   | VALIDATION_FAILED   | 400                        | no
#   an unknown invoice               | NOT_FOUND           | 404                        | no
#   already paid, another reference  | INVOICE_NOT_PAYABLE | 409 INVOICE_ALREADY_PAID   | no
#   an amount mismatch               | PAYMENT_MISMATCH    | 422 PAYMENT_MISMATCH       | no
#   a currency mismatch              | PAYMENT_MISMATCH    | 422 PAYMENT_MISMATCH       | no
#   a reference reused               | PRECONDITION_FAILED | 409 PAYMENT_REFERENCE_REUSED | no
#   no outstanding credit exposure   | PRECONDITION_FAILED | 409 PRECONDITION_FAILED   | no
#   a deadlock victim, lost link     | UNAVAILABLE         | 503                        | YES
#   anything unclassified            | INTERNAL_ERROR      | 500                        | YES
PAYMENT_REFUSALS: list[tuple[Exception, Code]] = [
    (InvalidPaymentRequestError("x"), Code.validation_failed),
    (InvalidCreditHeadersError("x"), Code.validation_failed),
    (InvoiceNotFoundError("0b0c0d0e-0000-4000-8000-000000000001", None), Code.not_found),
    (InvoiceAlreadyPaidError("INV-000001"), Code.invoice_not_payable),
    (InvoicePaymentAmountMismatchError(100, 200, "EUR"), Code.payment_mismatch),
    (InvoicePaymentCurrencyMismatchError("EUR", "USD"), Code.payment_mismatch),
    (PaymentReferenceReusedError("BANK-REF-77"), Code.precondition_failed),
    (CreditNotOutstandingError("ORD-000101"), Code.precondition_failed),
]


def _import_every_module() -> list[str]:
    """Import EVERY module of the package. `onerror` raises, and the import is not guarded, so a
    module that cannot be imported FAILS the walk instead of shrinking the population."""

    def onerror(name: str) -> None:
        raise ImportError(f"the walk could not import the package {name}")

    names = [m.name for m in pkgutil.walk_packages(otc_billing.__path__, "otc_billing.", onerror)]
    for name in names:
        importlib.import_module(name)
    return names


def _walked_domain_errors() -> set[type[DomainError]]:
    """Every `DomainError` subclass defined in any `otc_billing` module."""
    _import_every_module()
    found: set[type[DomainError]] = set()
    pending: list[type[DomainError]] = [DomainError]
    while pending:
        for subclass in pending.pop().__subclasses__():
            pending.append(subclass)
            if subclass.__module__.startswith("otc_billing."):
                found.add(subclass)
    return found


def test_bc27_every_transient_store_failure_maps_to_a_code_the_saga_adapter_retries() -> None:
    assert "40P01" in TRANSIENT_STATES, "the deadlock victim is in the population"
    assert len(TRANSIENT_STORE_FAILURES) == 7, "the population is the literal set plus class 08"
    for failure in TRANSIENT_STORE_FAILURES:
        code = map_error(failure, NOW, CORRELATION).code
        assert code not in TERMINAL_RPC_ERROR_CODES, (
            f"{type(failure).__name__}({failure}) is answered {code.value}, which Orders' saga "
            "adapter treats as a terminal rejection"
        )
        assert code in {Code.unavailable, Code.internal_error, Code.timeout}


def test_bc27_no_input_produces_conflict() -> None:
    walked = _walked_domain_errors()
    assert len(walked) == EXPECTED_DOMAIN_ERROR_COUNT, (
        f"a DomainError subclass was added or removed: {sorted(c.__name__ for c in walked)}"
    )
    with_input = {type(error) for error in DOMAIN_ERRORS}
    assert walked == with_input, (
        f"a walked class has no input here: {sorted(c.__name__ for c in walked - with_input)}"
    )

    codes = {map_error(error, NOW, CORRELATION).code for error in EVERY_INPUT}

    assert Code.conflict not in codes
    for error in DOMAIN_ERRORS:
        mapped = map_error(error, NOW, CORRELATION).code
        assert mapped in TERMINAL_RPC_ERROR_CODES, (
            f"{type(error).__name__} is answered {mapped.value}, which Orders' saga adapter "
            "would retry; BI25/BI26 require a terminal code"
        )
    assert Code.conflict in TERMINAL_RPC_ERROR_CODES, "the premise: CONFLICT is terminal in Orders"
    assert len(codes) >= 5, "the inputs exercise the mapping's rows, not one"


def test_bi26_no_active_hold_is_answered_with_a_code_in_the_saga_adapters_terminal_set() -> None:
    """The set is Orders' own `TERMINAL_RPC_ERROR_CODES`, imported, never retyped: a `BI5` refusal
    must stop the `invoice.issue` command row immediately with the reason recorded."""
    answered = map_error(NoActiveHoldError("ORD-000101"), NOW, CORRELATION)
    assert answered.code in TERMINAL_RPC_ERROR_CODES, (
        f"BI26: a NoActiveHoldError is answered {answered.code.value}, which Orders' saga adapter "
        "would retry instead of stopping the row"
    )
    assert answered.code is Code.precondition_failed
    assert answered.details == {"code": "credit.no_active_hold"}
    # the premise, read from the dispatcher's own set rather than restated
    assert Code.precondition_failed in TERMINAL_RPC_ERROR_CODES
    assert Code.unavailable not in TERMINAL_RPC_ERROR_CODES


def test_r49_every_payment_refusal_is_answered_with_its_tabulated_terminal_code() -> None:
    """Each row of `PAYMENT_REFUSALS`: the code `map_error` answers equals the table's, is in
    Orders' terminal set (re-asking can never turn it into a yes) and is never `CONFLICT`."""
    assert len(PAYMENT_REFUSALS) == 8
    for error, expected in PAYMENT_REFUSALS:
        answered = map_error(error, NOW, CORRELATION).code
        assert answered is expected, (
            f"{type(error).__name__} is answered {answered.value}, the table says {expected.value}"
        )
        assert answered in TERMINAL_RPC_ERROR_CODES, (
            f"{type(error).__name__} is answered {answered.value}, which a retrying caller would "
            "hammer"
        )
        assert answered is not Code.conflict
    # the two retried rows of the table: transient failures stay retryable on this subject too
    assert map_error(StoreUnavailableError("40P01"), NOW, CORRELATION).code is Code.unavailable
    assert map_error(RuntimeError("x"), NOW, CORRELATION).code is Code.internal_error
    assert Code.unavailable not in TERMINAL_RPC_ERROR_CODES
    assert Code.internal_error not in TERMINAL_RPC_ERROR_CODES
