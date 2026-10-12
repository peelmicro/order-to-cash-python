"""The Gateway's `RpcError` -> HTTP table, checked against the things it translates (feature 25,
acceptance items 3 and 7), and never against itself (#8 defect D1, `X == X` on both sides).

1. The twelve generic rows are EXACTLY `asyncapi.yaml`'s `RpcError.code` enum (read from the YAML
   and from the generated `Code`): a code added to the contract with no row fails here by name.
2. Every specific row's `details.code` is the `CODE` of a real Billing error class: the string the
   Gateway keys on is the string Billing sends, read from Billing, not retyped.
3. Every refusal `billing.payment.register` can answer is built by Billing's REAL `map_error` and
   fed to the Gateway's classifier; the statuses must equal the "Gateway maps it to" column that
   `test_billing_rpc_error_retryability.py` recorded when feature 22 shipped (parsed from that
   file's comment table), so the two documents of the mapping cannot drift.
"""

import re
from pathlib import Path

import yaml

from otc_billing.application.errors import CreditNotOutstandingError, PaymentReferenceReusedError
from otc_billing.domain.invoice_errors import (
    InvoiceAlreadyPaidError,
    InvoicePaymentAmountMismatchError,
    InvoicePaymentCurrencyMismatchError,
)
from otc_billing.presentation.credit_rpc_errors import map_error
from otc_contracts.generated.asyncapi import Code, RpcError
from otc_gateway.domain.rpc_error_classification import GENERIC, SPECIFIC, classify_rpc_error

REPO_ROOT = Path(__file__).resolve().parents[2]
TABLE_FILE = REPO_ROOT / "tests/architecture/test_billing_rpc_error_retryability.py"


def test_the_generic_rows_are_exactly_the_contracts_twelve_rpc_error_codes() -> None:
    contract = yaml.safe_load((REPO_ROOT / "specs/shared/asyncapi.yaml").read_text("utf-8"))
    declared = set(contract["components"]["schemas"]["RpcError"]["properties"]["code"]["enum"])

    assert set(GENERIC) == declared == {code.value for code in Code}
    assert len(declared) == 12


def test_every_specific_row_keys_on_a_real_billing_error_code_under_its_real_rpc_code() -> None:
    billing_codes = {
        "invoice.already_paid": InvoiceAlreadyPaidError.CODE,
        "invoice.payment_amount_mismatch": InvoicePaymentAmountMismatchError.CODE,
        "invoice.payment_currency_mismatch": InvoicePaymentCurrencyMismatchError.CODE,
        "payment.reference_reused": PaymentReferenceReusedError.CODE,
        "credit.not_outstanding": CreditNotOutstandingError.CODE,
    }

    assert {detail for _, detail in SPECIFIC} == set(billing_codes.values())
    for (rpc_code, detail_code), row in SPECIFIC.items():
        assert rpc_code in GENERIC, rpc_code
        assert detail_code in billing_codes.values(), detail_code
        assert row.status in {409, 422}


def comment_table() -> list[tuple[str, str, str]]:
    """(refusal, RpcError code, 'Gateway maps it to') of each row of the table in the comment."""
    rows = []
    for line in TABLE_FILE.read_text(encoding="utf-8").splitlines():
        match = re.match(
            r"^#\s{3}(?P<a>[^|]+?)\s*\|\s*(?P<b>[A-Z_]+)\s*\|\s*(?P<c>[^|]+?)\s*\|\s*(YES|no)\s*$",
            line,
        )
        if match and match["b"] != "RpcError":
            rows.append((match["a"], match["b"], match["c"]))
    return rows


def test_the_gateway_maps_every_real_billing_answer_as_the_feature_22_table_recorded() -> None:
    from datetime import UTC, datetime

    from otc_billing.application.errors import CreditNotOutstandingError as NotOutstanding
    from otc_billing.application.errors import InvoiceNotFoundError
    from otc_billing.application.ports.credit_store import StoreUnavailableError
    from otc_billing.presentation.payment_wire import InvalidPaymentRequestError

    now = datetime.now(UTC)
    answers: list[RpcError] = [
        map_error(InvalidPaymentRequestError("x"), now, None),
        map_error(InvoiceNotFoundError("0b0c0d0e-0000-4000-8000-000000000001", None), now, None),
        map_error(InvoiceAlreadyPaidError("INV-000001"), now, None),
        map_error(InvoicePaymentAmountMismatchError(100, 200, "EUR"), now, None),
        map_error(InvoicePaymentCurrencyMismatchError("EUR", "USD"), now, None),
        map_error(PaymentReferenceReusedError("BANK-REF-77"), now, None),
        map_error(NotOutstanding("ORD-000101"), now, None),
        map_error(StoreUnavailableError("deadlock victim"), now, None),
        map_error(RuntimeError("boom"), now, None),
    ]
    rows = comment_table()
    assert len(rows) == 9, rows  # a comment edited out of the shape this parser reads fails here

    for answer, (refusal, code, maps_to) in zip(answers, rows, strict=True):
        assert answer.code.value == code, refusal
        classified = classify_rpc_error(answer.code.value, answer.details)
        expected_status, _, expected_code = maps_to.partition(" ")
        assert str(classified.status) == expected_status, (refusal, classified, maps_to)
        if expected_code:
            assert classified.code == expected_code, (refusal, classified, maps_to)
