"""`POST /invoices/{id}/payments` (R47 - R49): feature 25's acceptance items 6 and 7.

Item 6 (progress/impl_billing_remittance_intake.md section 12 item 4): the payment's
`x-correlation-id` is the invoice's ORDER id, resolved from the invoice list and then the read
model; an invoice whose order is not projected answers a retryable error, not a wrong
correlation. The fixture's order id, invoice id and request id are pairwise distinct, and so is
every other id the test supplies, so a header carrying the invoice id, a fresh id or the
Idempotency key cannot pass.

Item 7: one test per mapping row of `openapi.yaml:673-675`, each with its sibling-code twin: the
same `details.code` under another `RpcError.code` must NOT produce the row.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from otc_contracts.generated import asyncapi
from otc_gateway.application.errors import (
    RpcCallError,
    RpcRemoteError,
    RpcTimeoutError,
    RpcUnavailableError,
)

INVOICE_ID = UUID("f1f1f1f1-f1f1-41f1-81f1-f1f1f1f1f1f1")
OTHER_INVOICE_ID = UUID("e2e2e2e2-e2e2-42e2-82e2-e2e2e2e2e2e2")
ORDER_ID = UUID("0a0a0a0a-0a0a-40a0-80a0-0a0a0a0a0a0a")
PAYMENT = {
    "paymentReference": "PAY-2026-08-18-000019",
    "amount": {"amount": 124250, "currency": "EUR"},
    "valueDate": "2026-08-18T11:02:00.000Z",
    "source": "robot",
}
PAID_AT = datetime(2026, 8, 18, 11, 2, 0, 500000, tzinfo=UTC)


def invoice_view(invoice_id: UUID, reference: str, order_reference: str) -> asyncapi.InvoiceView:
    return asyncapi.InvoiceView(
        invoice_id=invoice_id,
        invoice_reference=reference,
        invoice_date=datetime(2026, 8, 17, 9, 0, 0, tzinfo=UTC),
        order_reference=order_reference,
        retailer_code="RET-A",
        company_code="CMP-B",
        currency="EUR",
        amount=130000,
        discount=5750,
        total_amount=124250,
        status=asyncapi.InvoiceStatus.issued,
    )


def invoice_page(*views: asyncapi.InvoiceView) -> asyncapi.InvoiceListReplyPayload:
    return asyncapi.InvoiceListReplyPayload(
        items=list(views), page=asyncapi.PageInfo(page=1, page_size=200, total=len(views))
    )


def payment_reply(outcome: asyncapi.Outcome3) -> asyncapi.PaymentRegisterReplyPayload:
    return asyncapi.PaymentRegisterReplyPayload(
        outcome=outcome,
        payment_reference="PAY-2026-08-18-000019",
        invoice_reference="INV-000027",
        order_reference="ORD-000042",
        invoice_status=asyncapi.InvoiceStatus.paid,
        paid_at=PAID_AT,
    )


def arrange(harness: Any, *, projected: bool = True) -> None:
    harness.rpc.will_reply(
        "billing.invoice.list",
        invoice_page(
            invoice_view(OTHER_INVOICE_ID, "INV-000026", "ORD-000041"),
            invoice_view(INVOICE_ID, "INV-000027", "ORD-000042"),
        ),
    )
    if projected:
        harness.read_model.by_reference["ORD-000042"] = ORDER_ID


async def pay(harness: Any, invoice_id: UUID = INVOICE_ID) -> Any:
    return await harness.client.post(
        f"/invoices/{invoice_id}/payments", json=PAYMENT, headers=harness.bearer()
    )


def payment_call(harness: Any) -> Any:
    [call] = [c for c in harness.rpc.calls if c.subject == "billing.payment.register"]
    return call


# ------------------------------------------------------------------------------ acceptance 6


async def test_the_payment_x_correlation_id_is_the_invoices_order_id_read_from_the_read_model(
    harness: Any,
) -> None:
    arrange(harness)
    harness.rpc.will_reply("billing.payment.register", payment_reply(asyncapi.Outcome3.accepted))

    response = await pay(harness)

    assert response.status_code == 201
    call = payment_call(harness)
    assert call.correlation_id == ORDER_ID
    assert call.correlation_id != INVOICE_ID  # not the id of the path
    assert call.correlation_id != call.request_id  # not the attempt's id either
    assert call.request_id not in (ORDER_ID, INVOICE_ID)
    assert harness.read_model.lookups == ["ORD-000042"]  # the reference the invoice list gave
    # the response header names the same correlation
    assert response.headers["x-correlation-id"] == str(ORDER_ID)


async def test_the_payment_body_carries_the_invoice_id_and_the_remittance_as_the_contract_says(
    harness: Any,
) -> None:
    arrange(harness)
    harness.rpc.will_reply("billing.payment.register", payment_reply(asyncapi.Outcome3.accepted))

    await pay(harness)

    assert payment_call(harness).wire == {
        "invoiceId": str(INVOICE_ID),
        "paymentReference": "PAY-2026-08-18-000019",
        "amount": {"amount": 124250, "currency": "EUR"},
        "valueDate": "2026-08-18T11:02:00.000Z",
        "source": "robot",
    }


async def test_the_invoice_is_found_on_a_later_page_and_a_full_last_page_is_not_a_404(
    harness: Any,
) -> None:
    full_page = invoice_page(
        *(invoice_view(UUID(int=i + 1), f"INV-{i + 1:06d}", f"ORD-{i + 1:06d}") for i in range(200))
    )
    harness.rpc.will_reply(
        "billing.invoice.list",
        full_page,
        invoice_page(invoice_view(INVOICE_ID, "INV-000027", "ORD-000042")),
    )
    harness.read_model.by_reference["ORD-000042"] = ORDER_ID
    harness.rpc.will_reply("billing.payment.register", payment_reply(asyncapi.Outcome3.accepted))

    assert (await pay(harness)).status_code == 201

    pages = [c.wire["page"] for c in harness.rpc.calls if c.subject == "billing.invoice.list"]
    assert pages == [1, 2]
    assert {c.wire["pageSize"] for c in harness.rpc.calls[:2]} == {200}


async def test_an_invoice_that_is_nowhere_in_the_list_is_a_404(harness: Any) -> None:
    harness.rpc.will_reply("billing.invoice.list", invoice_page())

    response = await pay(harness)

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"
    assert [c.subject for c in harness.rpc.calls] == ["billing.invoice.list"]  # nothing paid


async def test_a_scan_that_used_its_budget_on_full_pages_is_a_503_never_a_false_404(
    harness: Any,
) -> None:
    full_page = invoice_page(
        *(invoice_view(UUID(int=i + 1), f"INV-{i + 1:06d}", f"ORD-{i + 1:06d}") for i in range(200))
    )
    harness.rpc.will_reply("billing.invoice.list", full_page)

    response = await pay(harness)

    assert response.status_code == 503
    assert response.json()["code"] == "SCAN_BUDGET_EXCEEDED"
    assert len([c for c in harness.rpc.calls if c.subject == "billing.invoice.list"]) == 5


async def test_an_invoice_whose_order_is_not_projected_yet_is_a_retryable_503_and_nothing_is_paid(
    harness: Any,
) -> None:
    arrange(harness, projected=False)

    response = await pay(harness)

    assert response.status_code == 503
    assert response.json()["code"] == "UPSTREAM_UNAVAILABLE"
    assert response.headers["retry-after"] == "2"
    assert "billing.payment.register" not in [c.subject for c in harness.rpc.calls]


# ------------------------------------------------------------------------------ outcomes


async def test_an_accepted_payment_is_a_201_and_a_duplicate_is_a_200_with_the_replay_header(
    harness: Any,
) -> None:
    arrange(harness)
    harness.rpc.will_reply("billing.payment.register", payment_reply(asyncapi.Outcome3.duplicate))

    response = await pay(harness)

    assert response.status_code == 200
    assert response.headers["idempotent-replay"] == "true"
    assert "x-correlation-id" not in response.headers
    assert response.json() == {
        "outcome": "duplicate",
        "paymentReference": "PAY-2026-08-18-000019",
        "invoiceReference": "INV-000027",
        "orderReference": "ORD-000042",
        "invoiceStatus": "paid",
        "paidAt": "2026-08-18T11:02:00.500Z",
    }


async def test_an_accepted_payment_carries_no_replay_header(harness: Any) -> None:
    arrange(harness)
    harness.rpc.will_reply("billing.payment.register", payment_reply(asyncapi.Outcome3.accepted))

    response = await pay(harness)

    assert response.status_code == 201
    assert response.json()["outcome"] == "accepted"
    assert "idempotent-replay" not in response.headers


async def test_a_malformed_payment_body_is_a_400_before_any_rpc(harness: Any) -> None:
    for body in (
        {**PAYMENT, "amount": {"amount": 124250.0, "currency": "EUR"}},
        {**PAYMENT, "amount": 124250},
        {**PAYMENT, "source": "carrier-pigeon"},
        {**PAYMENT, "valueDate": "yesterday"},
        {k: v for k, v in PAYMENT.items() if k != "paymentReference"},
    ):
        response = await harness.client.post(
            f"/invoices/{INVOICE_ID}/payments", json=body, headers=harness.bearer()
        )
        assert response.status_code == 400, body
    assert harness.rpc.calls == []


# ------------------------------------------------------------------------------ acceptance 7

ROWS: list[tuple[str, str, int, str]] = [
    # (RpcError.code, details.code, HTTP status, Problem.code)
    ("INVOICE_NOT_PAYABLE", "invoice.already_paid", 409, "INVOICE_ALREADY_PAID"),
    ("PAYMENT_MISMATCH", "invoice.payment_amount_mismatch", 422, "PAYMENT_MISMATCH"),
    ("PAYMENT_MISMATCH", "invoice.payment_currency_mismatch", 422, "PAYMENT_MISMATCH"),
    ("PRECONDITION_FAILED", "payment.reference_reused", 409, "PAYMENT_REFERENCE_REUSED"),
    ("PRECONDITION_FAILED", "credit.not_outstanding", 409, "PRECONDITION_FAILED"),
]
# The two PAYMENT_MISMATCH rows and the credit row answer the same status and `code` as their
# generic row, and differ from it ONLY in `title`: so a row that went missing (falling back to the
# generic one) is seen only by the title. Titles are for humans and are never parsed by a client;
# here they identify WHICH row answered.
TITLES = {
    "invoice.already_paid": "Invoice already paid",
    "invoice.payment_amount_mismatch": "Payment amount does not match the invoice total",
    "invoice.payment_currency_mismatch": "Payment currency does not match the invoice total",
    "payment.reference_reused": "Payment reference reused for a different invoice or amount",
    "credit.not_outstanding": "The invoice has no outstanding credit exposure to release",
}


@pytest.mark.parametrize(("rpc_code", "detail_code", "status", "problem_code"), ROWS)
async def test_item_7_each_billing_refusal_row_is_the_status_and_code_the_contract_declares(
    harness: Any, rpc_code: str, detail_code: str, status: int, problem_code: str
) -> None:
    arrange(harness)
    harness.rpc.will_reply(
        "billing.payment.register",
        RpcRemoteError("billing.payment.register", rpc_code, "refused", {"code": detail_code}),
    )

    response = await pay(harness)

    assert response.status_code == status
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == problem_code
    assert response.json()["status"] == status
    assert response.json()["title"] == TITLES[detail_code]  # the SPECIFIC row answered


SIBLING = {  # a code that is NOT the row's, carrying the row's details.code
    "INVOICE_NOT_PAYABLE": "VALIDATION_FAILED",
    "PAYMENT_MISMATCH": "DOMAIN_ERROR",
    "PRECONDITION_FAILED": "CONFLICT",
}


@pytest.mark.parametrize(("rpc_code", "detail_code", "status", "problem_code"), ROWS)
async def test_item_7_the_same_detail_code_under_a_sibling_rpc_code_is_not_the_row(
    harness: Any, rpc_code: str, detail_code: str, status: int, problem_code: str
) -> None:
    arrange(harness)
    harness.rpc.will_reply(
        "billing.payment.register",
        RpcRemoteError(
            "billing.payment.register", SIBLING[rpc_code], "refused", {"code": detail_code}
        ),
    )

    response = await pay(harness)

    assert response.json()["code"] == SIBLING[rpc_code]  # the generic row of the sibling code
    assert response.json()["code"] != problem_code


async def test_item_7_a_reused_reference_is_not_a_credit_refusal_and_the_reverse(
    harness: Any,
) -> None:
    """The two PRECONDITION_FAILED rows differ ONLY by `details.code`: swapping them breaks one."""
    arrange(harness)
    outcomes = {}
    for detail_code in ("payment.reference_reused", "credit.not_outstanding"):
        harness.rpc.replies.pop("billing.payment.register", None)
        harness.rpc.will_reply(
            "billing.payment.register",
            RpcRemoteError(
                "billing.payment.register",
                "PRECONDITION_FAILED",
                "refused",
                {"code": detail_code},
            ),
        )
        outcomes[detail_code] = (await pay(harness)).json()["code"]

    assert outcomes == {
        "payment.reference_reused": "PAYMENT_REFERENCE_REUSED",
        "credit.not_outstanding": "PRECONDITION_FAILED",
    }


async def test_item_7_a_refusal_with_no_detail_code_is_the_generic_row_of_its_rpc_code(
    harness: Any,
) -> None:
    arrange(harness)
    harness.rpc.will_reply(
        "billing.payment.register",
        RpcRemoteError("billing.payment.register", "INVOICE_NOT_PAYABLE", "refused", None),
    )

    response = await pay(harness)

    assert (response.status_code, response.json()["code"]) == (409, "INVOICE_NOT_PAYABLE")


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (RpcTimeoutError("billing.payment.register", 5000), 503, "UPSTREAM_TIMEOUT"),
        (
            RpcUnavailableError("billing.payment.register", "no responder"),
            503,
            "UPSTREAM_UNAVAILABLE",
        ),
    ],
)
async def test_the_payment_route_maps_a_timeout_and_a_missing_responder_to_503(
    harness: Any, error: RpcCallError, status: int, code: str
) -> None:
    arrange(harness)
    harness.rpc.will_reply("billing.payment.register", error)

    response = await pay(harness)

    assert (response.status_code, response.json()["code"]) == (status, code)
