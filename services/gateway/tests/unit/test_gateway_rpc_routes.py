"""The routes that are one RPC call each (`GET /stock`, `POST /stock/replenish`, `GET /invoices`,
`GET /credits`, the three catalog routes): the request each sends, the response each writes, and the
mapping of a timeout, a missing responder and every `RpcError` code to HTTP (acceptance item 3).

Money and counts are asserted field by field from fixtures whose values differ from each other.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from otc_contracts.generated import asyncapi
from otc_gateway.application.errors import (
    RpcProtocolError,
    RpcRemoteError,
    RpcTimeoutError,
    RpcUnavailableError,
)
from otc_gateway.domain.rpc_error_classification import GENERIC

INVOICE_ID = UUID("d4d4d4d4-d4d4-44d4-84d4-d4d4d4d4d4d4")


def stock_view() -> asyncapi.StockView:
    return asyncapi.StockView(
        company_code="IBERFOODS",
        product_code="PRD-0001",
        units=120,
        reserved_units=35,
        available_units=85,
        low_stock_threshold=20,
    )


async def test_list_stock_sends_the_filters_and_writes_each_count_from_its_own_field(
    harness: Any,
) -> None:
    harness.rpc.will_reply(
        "fulfillment.stock.list",
        asyncapi.StockListReplyPayload(
            items=[stock_view()], page=asyncapi.PageInfo(page=2, page_size=10, total=31)
        ),
    )

    response = await harness.client.get(
        "/stock?companyCode=IBERFOODS&productCode=PRD-0001&belowThreshold=true&page=2&pageSize=10",
        headers=harness.bearer(),
    )

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "companyCode": "IBERFOODS",
                "productCode": "PRD-0001",
                "units": 120,
                "reservedUnits": 35,
                "availableUnits": 85,
                "lowStockThreshold": 20,
            }
        ],
        "page": {"page": 2, "pageSize": 10, "total": 31},
    }
    [call] = harness.rpc.calls
    assert call.subject == "fulfillment.stock.list"
    assert call.wire == {
        "page": 2,
        "pageSize": 10,
        "companyCode": "IBERFOODS",
        "productCode": "PRD-0001",
        "belowThreshold": True,
    }


async def test_replenish_stock_sends_the_lines_as_a_delta_and_returns_the_items(
    harness: Any,
) -> None:
    harness.rpc.will_reply(
        "fulfillment.stock.replenish", asyncapi.StockReplenishReplyPayload(items=[stock_view()])
    )

    response = await harness.client.post(
        "/stock/replenish",
        json={"companyCode": "IBERFOODS", "lines": [{"productCode": "PRD-0001", "units": 100}]},
        headers=harness.bearer(),
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["units"] == 120
    assert harness.rpc.calls[0].wire == {
        "companyCode": "IBERFOODS",
        "lines": [{"productCode": "PRD-0001", "units": 100}],
    }


async def test_replenish_stock_refuses_a_zero_or_missing_line_before_any_rpc(harness: Any) -> None:
    for body in (
        {"companyCode": "IBERFOODS", "lines": []},
        {"companyCode": "IBERFOODS", "lines": [{"productCode": "PRD-0001", "units": 0}]},
        {"lines": [{"productCode": "PRD-0001", "units": 1}]},
    ):
        response = await harness.client.post(
            "/stock/replenish", json=body, headers=harness.bearer()
        )
        assert response.status_code == 400, body
    assert harness.rpc.calls == []


async def test_list_invoices_sends_every_filter_and_writes_each_amount_from_its_own_field(
    harness: Any,
) -> None:
    harness.rpc.will_reply(
        "billing.invoice.list",
        asyncapi.InvoiceListReplyPayload(
            items=[
                asyncapi.InvoiceView(
                    invoice_id=INVOICE_ID,
                    invoice_reference="INV-000027",
                    invoice_date=datetime(2026, 8, 17, 9, 0, 0, 250000, tzinfo=UTC),
                    order_reference="ORD-000042",
                    retailer_code="RET-A",
                    company_code="CMP-B",
                    currency="EUR",
                    amount=130000,
                    discount=5750,
                    total_amount=124250,
                    status=asyncapi.InvoiceStatus.paid,
                    paid_at=datetime(2026, 8, 18, 11, 2, 0, tzinfo=UTC),
                )
            ],
            page=asyncapi.PageInfo(page=1, page_size=25, total=1),
        ),
    )

    response = await harness.client.get(
        "/invoices?status=paid&retailerCode=RET-A&companyCode=CMP-B&orderReference=ORD-000042"
        "&issuedBeforeMinutes=30",
        headers=harness.bearer(),
    )

    assert response.status_code == 200
    assert response.json()["items"] == [
        {
            "invoiceId": str(INVOICE_ID),
            "invoiceReference": "INV-000027",
            "invoiceDate": "2026-08-17T09:00:00.250Z",
            "orderReference": "ORD-000042",
            "retailerCode": "RET-A",
            "companyCode": "CMP-B",
            "currency": "EUR",
            "amount": 130000,
            "discount": 5750,
            "totalAmount": 124250,
            "status": "paid",
            "paidAt": "2026-08-18T11:02:00.000Z",
        }
    ]
    assert harness.rpc.calls[0].wire == {
        "page": 1,
        "pageSize": 25,
        "status": "paid",
        "retailerCode": "RET-A",
        "companyCode": "CMP-B",
        "orderReference": "ORD-000042",
        "issuedBeforeMinutes": 30,
    }


async def test_list_credits_writes_each_amount_from_its_own_field(harness: Any) -> None:
    harness.rpc.will_reply(
        "billing.credit.list",
        asyncapi.CreditListReplyPayload(
            items=[
                asyncapi.CreditView(
                    credit_code="CR-000003",
                    retailer_code="RET-A",
                    company_code="CMP-B",
                    currency="EUR",
                    credit_limit=1000000,
                    active_holds=200000,
                    open_exposure=124250,
                    available_credit=675750,
                )
            ],
            page=asyncapi.PageInfo(page=1, page_size=25, total=1),
        ),
    )

    response = await harness.client.get(
        "/credits?retailerCode=RET-A&companyCode=CMP-B", headers=harness.bearer()
    )

    assert response.json()["items"] == [
        {
            "creditCode": "CR-000003",
            "retailerCode": "RET-A",
            "companyCode": "CMP-B",
            "currency": "EUR",
            "creditLimit": 1000000,
            "activeHolds": 200000,
            "openExposure": 124250,
            "availableCredit": 675750,
        }
    ]
    assert harness.rpc.calls[0].wire == {
        "page": 1,
        "pageSize": 25,
        "retailerCode": "RET-A",
        "companyCode": "CMP-B",
    }


async def test_each_catalog_route_asks_for_its_own_kind_and_returns_its_own_list(
    harness: Any,
) -> None:
    party = asyncapi.Party(
        code="CarrefourEs",
        name="Carrefour",
        country="ES",
        vat="ESA1",
        gln="8412345000013",
        currency="EUR",
        enabled=True,
    )
    product = asyncapi.Product(
        code="PRD-0001",
        ean="5400000000041",
        name="Aceite",
        description="1 L",
        price=24999,
        currency="EUR",
        enabled=True,
    )
    harness.rpc.will_reply(
        "catalog.reference.list",
        asyncapi.CatalogReferenceListReplyPayload(products=[product]),
        asyncapi.CatalogReferenceListReplyPayload(retailers=[party]),
        asyncapi.CatalogReferenceListReplyPayload(companies=[party]),
    )

    products = await harness.client.get("/catalog/products", headers=harness.bearer())
    retailers = await harness.client.get(
        "/catalog/retailers?includeDisabled=true", headers=harness.bearer()
    )
    companies = await harness.client.get("/catalog/companies", headers=harness.bearer())

    assert products.json()["items"][0]["price"] == 24999
    assert retailers.json()["items"][0]["code"] == "CarrefourEs"
    assert companies.json()["items"][0]["gln"] == "8412345000013"
    assert [(c.wire["kinds"], c.wire["includeDisabled"]) for c in harness.rpc.calls] == [
        (["products"], False),
        (["retailers"], True),
        (["companies"], False),
    ]


# ------------------------------------------------------------------------------ acceptance 3

RPC_ROUTES: list[tuple[str, str, dict[str, Any] | None, str]] = [
    ("POST", "/orders", {
        "retailerCode": "A", "companyCode": "B", "currency": "EUR",
        "lines": [{"productCode": "P", "quantity": 1}],
    }, "orders.create"),
    ("POST", f"/orders/{INVOICE_ID}/cancel", None, "orders.cancel"),
    ("GET", "/stock", None, "fulfillment.stock.list"),
    ("POST", "/stock/replenish", {
        "companyCode": "B", "lines": [{"productCode": "P", "units": 1}]
    }, "fulfillment.stock.replenish"),
    ("GET", "/invoices", None, "billing.invoice.list"),
    ("GET", "/credits", None, "billing.credit.list"),
    ("GET", "/catalog/products", None, "catalog.reference.list"),
    ("GET", "/catalog/retailers", None, "catalog.reference.list"),
    ("GET", "/catalog/companies", None, "catalog.reference.list"),
]  # fmt: skip


@pytest.mark.parametrize(("method", "path", "body", "subject"), RPC_ROUTES)
async def test_every_rpc_route_maps_a_timeout_to_503_upstream_timeout(
    harness: Any, method: str, path: str, body: Any, subject: str
) -> None:
    harness.rpc.will_reply(subject, RpcTimeoutError(subject, 5000))

    response = await harness.client.request(method, path, json=body, headers=harness.bearer())

    assert (response.status_code, response.json()["code"]) == (503, "UPSTREAM_TIMEOUT")
    assert response.headers["content-type"] == "application/problem+json"


@pytest.mark.parametrize(("method", "path", "body", "subject"), RPC_ROUTES)
async def test_every_rpc_route_maps_a_missing_responder_to_503_upstream_unavailable(
    harness: Any, method: str, path: str, body: Any, subject: str
) -> None:
    harness.rpc.will_reply(subject, RpcUnavailableError(subject, "no responder"))

    response = await harness.client.request(method, path, json=body, headers=harness.bearer())

    assert (response.status_code, response.json()["code"]) == (503, "UPSTREAM_UNAVAILABLE")


@pytest.mark.parametrize(("method", "path", "body", "subject"), RPC_ROUTES)
async def test_every_rpc_route_maps_an_unreadable_reply_to_503_upstream_unavailable_not_to_a_502(
    harness: Any, method: str, path: str, body: Any, subject: str
) -> None:
    harness.rpc.will_reply(subject, RpcProtocolError(subject, "garbage"))

    response = await harness.client.request(method, path, json=body, headers=harness.bearer())

    assert (response.status_code, response.json()["code"]) == (503, "UPSTREAM_UNAVAILABLE")


GENERIC_STATUS = {
    "VALIDATION_FAILED": (400, "VALIDATION_FAILED"),
    "NOT_FOUND": (404, "NOT_FOUND"),
    "CONFLICT": (409, "CONFLICT"),
    "PRECONDITION_FAILED": (409, "PRECONDITION_FAILED"),
    "ORDER_NOT_CANCELLABLE": (409, "ORDER_NOT_CANCELLABLE"),
    "STOCK_UNAVAILABLE": (409, "STOCK_UNAVAILABLE"),
    "INVOICE_NOT_PAYABLE": (409, "INVOICE_NOT_PAYABLE"),
    "PAYMENT_MISMATCH": (422, "PAYMENT_MISMATCH"),
    "DOMAIN_ERROR": (422, "DOMAIN_ERROR"),
    "INTERNAL_ERROR": (500, "INTERNAL_ERROR"),
    "UNAVAILABLE": (503, "UPSTREAM_UNAVAILABLE"),
    "TIMEOUT": (503, "UPSTREAM_TIMEOUT"),
}


def test_the_literal_table_below_covers_exactly_the_classifiers_rows() -> None:
    assert set(GENERIC_STATUS) == set(GENERIC)


@pytest.mark.parametrize("rpc_code", sorted(GENERIC_STATUS))
async def test_every_rpc_error_code_a_responder_can_answer_has_its_http_status(
    harness: Any, rpc_code: str
) -> None:
    harness.rpc.will_reply("fulfillment.stock.list", RpcRemoteError("s", rpc_code, "no", None))

    response = await harness.client.get("/stock", headers=harness.bearer())

    status, code = GENERIC_STATUS[rpc_code]
    assert (response.status_code, response.json()["code"]) == (status, code)


async def test_an_error_code_nobody_defined_is_a_500_that_forwards_none_of_its_text(
    harness: Any,
) -> None:
    harness.rpc.will_reply(
        "fulfillment.stock.list",
        RpcRemoteError("s", "SOMETHING_NEW", "select * from secrets where id = 1", None),
    )

    response = await harness.client.get("/stock", headers=harness.bearer())

    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert "secrets" not in response.text


async def test_an_internal_error_never_forwards_the_responders_text(harness: Any) -> None:
    harness.rpc.will_reply(
        "fulfillment.stock.list",
        RpcRemoteError("s", "INTERNAL_ERROR", "/srv/app/orders.py line 3: boom", None),
    )

    response = await harness.client.get("/stock", headers=harness.bearer())

    assert "orders.py" not in response.text


async def test_a_bug_in_a_handler_is_a_500_problem_with_no_exception_text(
    harness: Any,
) -> None:
    def explode(call: Any) -> Any:
        return 1 / 0

    harness.rpc.will_reply("fulfillment.stock.list", explode)

    response = await harness.client.get("/stock", headers=harness.bearer())

    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert "division" not in response.text


async def test_a_refusal_that_names_an_amount_is_forwarded_as_the_owner_rendered_it(
    harness: Any,
) -> None:
    """#8 id 102 (a Problem `detail` that read money as minor units): the Gateway renders NO
    amount of its own. The owning context renders its messages with the ISO 4217 exponent table
    (SA-5) where it raises them, and a 4xx carries that text to the client verbatim; the Gateway's
    own titles carry no figure at all."""
    message = "Payment of 1.242,50 EUR does not equal the invoice total of 1.240,00 EUR"
    harness.rpc.will_reply("fulfillment.stock.list", RpcRemoteError("s", "DOMAIN_ERROR", message))

    response = await harness.client.get("/stock", headers=harness.bearer())

    assert response.status_code == 422
    assert response.json()["detail"] == message
    assert not any(ch.isdigit() for ch in response.json()["title"])


async def test_a_known_outage_is_logged_as_one_warning_and_an_unforeseen_failure_with_its_traceback(
    harness: Any, caplog: pytest.LogCaptureFixture
) -> None:
    harness.rpc.will_reply("fulfillment.stock.list", RpcUnavailableError("s", "no responder"))
    await harness.client.get("/stock", headers=harness.bearer())
    outage = [r for r in caplog.records if r.name == "otc_gateway.presentation.asgi"]
    caplog.clear()

    def explode(call: Any) -> Any:
        return 1 / 0

    harness.rpc.replies.clear()
    harness.rpc.will_reply("fulfillment.stock.list", explode)
    await harness.client.get("/stock", headers=harness.bearer())
    bug = [r for r in caplog.records if r.name == "otc_gateway.presentation.asgi"]

    assert [(r.levelname, r.exc_info is None) for r in outage] == [("WARNING", True)]
    assert "UPSTREAM_UNAVAILABLE" in outage[0].getMessage()
    assert [(r.levelname, r.exc_info is None) for r in bug] == [("ERROR", False)]
