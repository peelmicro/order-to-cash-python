"""The ONE place an `RpcError` becomes an HTTP status and `openapi.yaml`'s own `Problem.code`.

Every responder answers with the twelve-value vocabulary of `asyncapi.yaml` `RpcError.code` and
keeps its specific vocabulary in `details.code` (Billing: `invoice.already_paid`,
`invoice.payment_amount_mismatch`, `invoice.payment_currency_mismatch`, `payment.reference_reused`,
`credit.not_outstanding`; dotted, lower-case: `BC27`, `credit_rpc_errors.py`). `openapi.yaml`'s
`Problem.code` examples (`INVOICE_ALREADY_PAID`, `PAYMENT_MISMATCH`,
`PAYMENT_REFERENCE_REUSED`, ...)
name the specific vocabulary, so this module is the single translation step back.

Ported from #7 (`apps/gateway/src/domain/problem/rpc-error-mapping.ts:37-43`, the overrides, and
`:68-71`, their use) and #8 (`src/Gateway/Domain/Problem/RpcErrorClassification.cs:62-65`, the
overrides; `:77`, the generic `INVOICE_NOT_PAYABLE` row; `:100-106`, the shape heuristic), NOT
verbatim: both keyed their
overrides on `details.code` ALONE with the UPPER-CASE spellings of their own Billing
(`INVOICE_ALREADY_PAID`, `PAYMENT_REFERENCE_CONFLICT`), which #9's dotted codes never equal, and
#8 stood a SHAPE heuristic in for the missing code (`PRECONDITION_FAILED` carrying
`paymentReference`). #9's Billing sends the code, so the override is keyed on the pair
`(RpcError.code, details.code)`: a `details.code` is meaningful only under the `RpcError.code` that
its owner sends it with, so the same text under a sibling code (`VALIDATION_FAILED` +
`invoice.already_paid`) changes nothing.

Pure: no framework, no I/O, no contract import (the table of generic codes is asserted EQUAL to
`asyncapi.yaml`'s enum by `tests/architecture/test_gateway_rpc_error_mapping.py`, never retyped).
"""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Classified:
    status: int
    code: str
    title: str


# (RpcError.code, details.code) -> the more specific answer.
SPECIFIC: dict[tuple[str, str], Classified] = {
    ("INVOICE_NOT_PAYABLE", "invoice.already_paid"): Classified(
        409, "INVOICE_ALREADY_PAID", "Invoice already paid"
    ),
    ("PAYMENT_MISMATCH", "invoice.payment_amount_mismatch"): Classified(
        422, "PAYMENT_MISMATCH", "Payment amount does not match the invoice total"
    ),
    ("PAYMENT_MISMATCH", "invoice.payment_currency_mismatch"): Classified(
        422, "PAYMENT_MISMATCH", "Payment currency does not match the invoice total"
    ),
    ("PRECONDITION_FAILED", "payment.reference_reused"): Classified(
        409,
        "PAYMENT_REFERENCE_REUSED",
        "Payment reference reused for a different invoice or amount",
    ),
    ("PRECONDITION_FAILED", "credit.not_outstanding"): Classified(
        409, "PRECONDITION_FAILED", "The invoice has no outstanding credit exposure to release"
    ),
}

# RpcError.code -> status and Problem.code. One row per value of the wire enum.
GENERIC: dict[str, Classified] = {
    "VALIDATION_FAILED": Classified(
        400, "VALIDATION_FAILED", "The request was malformed or failed validation"
    ),
    "NOT_FOUND": Classified(404, "NOT_FOUND", "No such resource"),
    "CONFLICT": Classified(409, "CONFLICT", "The request conflicts with the current state"),
    "PRECONDITION_FAILED": Classified(
        409, "PRECONDITION_FAILED", "A precondition of this operation was not met"
    ),
    "ORDER_NOT_CANCELLABLE": Classified(409, "ORDER_NOT_CANCELLABLE", "Order is not cancellable"),
    "STOCK_UNAVAILABLE": Classified(409, "STOCK_UNAVAILABLE", "Insufficient stock at acceptance"),
    "INVOICE_NOT_PAYABLE": Classified(409, "INVOICE_NOT_PAYABLE", "Invoice is not payable"),
    "PAYMENT_MISMATCH": Classified(
        422, "PAYMENT_MISMATCH", "Payment amount or currency does not match the invoice"
    ),
    "DOMAIN_ERROR": Classified(422, "DOMAIN_ERROR", "A domain rule refused the request"),
    "INTERNAL_ERROR": Classified(500, "INTERNAL_ERROR", "An unexpected error occurred"),
    "UNAVAILABLE": Classified(503, "UPSTREAM_UNAVAILABLE", "The owning context is unreachable"),
    "TIMEOUT": Classified(
        503, "UPSTREAM_TIMEOUT", "The owning context did not answer within the deadline"
    ),
}

# A reply that is neither the success shape nor an `RpcError`: the Gateway could not read it, so it
# has no usable answer from the owning context, the same as no answer. 503 `UPSTREAM_UNAVAILABLE`
# as #7 and #8 answer it (SA-9; `UpstreamUnavailable` now covers "a reply the Gateway could not
# read"). The Problem `detail` still says the reply was unreadable (it is the error's own text).
PROTOCOL_ERROR = GENERIC["UNAVAILABLE"]

# What the caller itself concludes when there is no reply to read.
NO_REPLY_IN_TIME = "TIMEOUT"
NO_RESPONDER = "UNAVAILABLE"


def classify_rpc_error(rpc_code: str, details: Mapping[str, object] | None) -> Classified:
    detail_code = None if details is None else details.get("code")
    if isinstance(detail_code, str) and (rpc_code, detail_code) in SPECIFIC:
        return SPECIFIC[(rpc_code, detail_code)]
    return GENERIC.get(rpc_code, GENERIC["INTERNAL_ERROR"])
