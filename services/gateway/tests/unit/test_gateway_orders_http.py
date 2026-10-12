"""`POST /orders`, `GET /orders`, `GET /orders/{id}`, `POST /orders/{id}/cancel` (R54, R55, R62) and
the field-by-field assertions of E1 (#8's `GET /orders/{id}` money fields were unasserted: a
transposition of two totals stayed green).

Every fixture value below is distinct from every other value of the same document, so a field
copied from the wrong source cannot satisfy its assertion by accident: the three totals are
124250, 5000 and 119250 (and the raw minor-unit integer of one is never the number of another);
the retailer and the company differ in code, name and GLN; the order id, the event ids and the
causation ids are all different UUIDs.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from otc_contracts.generated import asyncapi, openapi
from otc_gateway.application.errors import RpcRemoteError, RpcUnavailableError
from otc_gateway.application.ports.order_read_model import (
    ReadModelEvent,
    ReadModelItem,
    ReadModelOrder,
    ReadModelParty,
    ReadModelReferences,
    ReadModelSummary,
    ReadModelTotals,
)

ORDER_ID = UUID("11111111-1111-4111-8111-111111111111")
REQUEST_KEY = UUID("22222222-2222-4222-8222-222222222222")
EVENT_A = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
EVENT_B = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
CAUSE = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
PLACED_AT = datetime(2026, 8, 18, 10, 15, 0, 100000, tzinfo=UTC)
UPDATED_AT = datetime(2026, 8, 18, 10, 20, 5, 700000, tzinfo=UTC)
EVENT_AT = datetime(2026, 8, 18, 10, 16, 1, 250000, tzinfo=UTC)

PLACE_BODY = {
    "retailerCode": "CarrefourEs",
    "companyCode": "IBERFOODS",
    "currency": "EUR",
    "lines": [
        {"productCode": "PRD-0001", "quantity": 5, "unitPrice": 24999, "lineDiscount": 250},
        {"productCode": "PRD-0007", "quantity": 25},
    ],
    "orderDiscount": 5000,
    "notes": "demo - compensation path",
}


def created_reply() -> asyncapi.OrdersCreateReplyPayload:
    return asyncapi.OrdersCreateReplyPayload(
        order_id=ORDER_ID,
        order_reference="ORD-000042",
        status="placed",
        currency="EUR",
        initial_amount=124250,
        initial_discount=5000,
        total_amount=119250,
        order_date=PLACED_AT,
    )


def document(*, complete: bool = True) -> ReadModelOrder:
    party = ReadModelParty("RET-ES-01", "Carrefour Espana", "8412345000013")
    company = ReadModelParty("IBERFOODS", "Iberfoods SA", "8412345000020")
    empty = ReadModelParty(None, None, None)
    return ReadModelOrder(
        header=ReadModelSummary(
            order_id=ORDER_ID,
            order_reference="ORD-000042" if complete else None,
            order_date=PLACED_AT if complete else None,
            retailer=party if complete else empty,
            company=company if complete else empty,
            status="stock_reserved",
            cancellation_reason=None,
            currency="EUR" if complete else None,
            totals=(
                ReadModelTotals(124250, 5000, 119250)
                if complete
                else ReadModelTotals(None, None, None)
            ),
            updated_at=UPDATED_AT,
        ),
        items=(
            ReadModelItem("PRD-0001", "Aceite 1L", 5, 24999, 250),
            ReadModelItem("PRD-0007", None, 25, 70, 0),
        ),
        references=ReadModelReferences("DES-000031", None, "PAY-2026-08-18-000019"),
        events=(
            ReadModelEvent(
                EVENT_A, CAUSE, "stock.reserved.v1", EVENT_AT, "5 units reserved", {"units": 5}
            ),
            ReadModelEvent(EVENT_B, None, "order.placed.v1", PLACED_AT, "Order placed", None),
        ),
        header_complete=complete,
    )


# ------------------------------------------------------------------------------ POST /orders


async def test_place_order_answers_201_with_each_amount_from_its_own_field_and_the_order_headers(
    harness: Any,
) -> None:
    harness.rpc.will_reply("orders.create", created_reply())

    response = await harness.client.post(
        "/orders",
        json=PLACE_BODY,
        headers={**harness.bearer(), "Idempotency-Key": str(REQUEST_KEY)},
    )

    assert response.status_code == 201
    assert response.headers["location"] == f"/orders/{ORDER_ID}"
    assert response.headers["x-correlation-id"] == str(ORDER_ID)  # the order id, not a fresh one
    assert response.json() == {
        "orderId": str(ORDER_ID),
        "orderReference": "ORD-000042",
        "status": "placed",
        "currency": "EUR",
        "initialAmount": 124250,
        "initialDiscount": 5000,
        "totalAmount": 119250,
        "orderDate": "2026-08-18T10:15:00.100Z",
        "projectionPending": True,
    }
    openapi.PlaceOrderResponse.model_validate_json(response.content, by_alias=True)


async def test_place_order_sends_the_contracts_payload_with_the_idempotency_key_as_request_id(
    harness: Any,
) -> None:
    harness.rpc.will_reply("orders.create", created_reply())

    await harness.client.post(
        "/orders",
        json=PLACE_BODY,
        headers={**harness.bearer(), "Idempotency-Key": str(REQUEST_KEY)},
    )

    [call] = harness.rpc.calls
    assert call.subject == "orders.create"
    assert call.wire == {
        "requestId": str(REQUEST_KEY),
        "retailerCode": "CarrefourEs",
        "companyCode": "IBERFOODS",
        "currency": "EUR",
        "lines": [
            {"productCode": "PRD-0001", "quantity": 5, "unitPrice": 24999, "lineDiscount": 250},
            {"productCode": "PRD-0007", "quantity": 25},
        ],
        "orderDiscount": 5000,
        "notes": "demo - compensation path",
    }
    # the transport's request id names THIS attempt: never the idempotency key
    assert call.request_id != REQUEST_KEY
    assert call.correlation_id == call.request_id  # the order does not exist yet


async def test_place_order_without_an_idempotency_key_sends_no_request_id(harness: Any) -> None:
    harness.rpc.will_reply("orders.create", created_reply())

    await harness.client.post("/orders", json=PLACE_BODY, headers=harness.bearer())

    assert "requestId" not in harness.rpc.calls[0].wire


async def test_place_order_refuses_an_idempotency_key_that_is_not_a_uuid(harness: Any) -> None:
    response = await harness.client.post(
        "/orders", json=PLACE_BODY, headers={**harness.bearer(), "Idempotency-Key": "not-a-uuid"}
    )

    assert response.status_code == 400
    assert response.json()["errors"][0]["field"] == "Idempotency-Key"
    assert harness.rpc.calls == []


async def test_place_order_records_the_id_so_the_detail_answers_pending_not_unknown(
    harness: Any,
) -> None:
    harness.rpc.will_reply("orders.create", created_reply())
    await harness.client.post("/orders", json=PLACE_BODY, headers=harness.bearer())

    response = await harness.client.get(f"/orders/{ORDER_ID}", headers=harness.bearer())

    assert response.status_code == 202
    assert response.headers["retry-after"] == "2"
    assert response.json() == {
        "orderId": str(ORDER_ID),
        "status": "projection_pending",
        "message": "The order was accepted and is not projected yet. "
        "Subscribe to /orders/stream or retry.",
        "retryAfterMs": 2000,
    }


async def test_place_order_integers_are_strict_a_float_or_a_string_quantity_is_a_400(
    harness: Any,
) -> None:
    for bad in (2.0, "2", True, 0):
        body = {**PLACE_BODY, "lines": [{"productCode": "PRD-0001", "quantity": bad}]}
        response = await harness.client.post("/orders", json=body, headers=harness.bearer())
        assert response.status_code == 400, bad
        assert response.json()["errors"][0]["field"] == "lines.0.quantity", bad
    assert harness.rpc.calls == []


async def test_place_order_with_no_lines_is_a_400_naming_the_field(harness: Any) -> None:
    response = await harness.client.post(
        "/orders", json={**PLACE_BODY, "lines": []}, headers=harness.bearer()
    )

    assert response.status_code == 400
    assert response.json()["errors"][0]["field"] == "lines"


async def test_place_order_with_a_body_that_is_not_json_is_a_400(harness: Any) -> None:
    response = await harness.client.post(
        "/orders",
        content=b"{not json",
        headers={**harness.bearer(), "Content-Type": "application/json"},
    )

    assert response.status_code == 400
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "VALIDATION_FAILED"


async def test_place_order_stock_unavailable_is_a_409_problem_that_names_the_short_lines(
    harness: Any,
) -> None:
    harness.rpc.will_reply(
        "orders.create",
        RpcRemoteError(
            "orders.create",
            "STOCK_UNAVAILABLE",
            "insufficient stock",
            {"shortages": [{"productCode": "PRD-0007", "requested": 25, "available": 3}]},
        ),
    )

    response = await harness.client.post("/orders", json=PLACE_BODY, headers=harness.bearer())

    assert response.status_code == 409
    body = openapi.StockUnavailableProblem.model_validate_json(response.content, by_alias=True)
    assert body.code == "STOCK_UNAVAILABLE"
    assert body.shortages is not None
    assert [(s.product_code, s.requested, s.available) for s in body.shortages] == [
        ("PRD-0007", 25, 3)
    ]


async def test_place_order_when_nobody_answers_is_a_503_and_nothing_is_recorded(
    harness: Any,
) -> None:
    harness.rpc.will_reply("orders.create", RpcUnavailableError("orders.create", "no responder"))

    response = await harness.client.post("/orders", json=PLACE_BODY, headers=harness.bearer())

    assert response.status_code == 503
    assert response.json()["code"] == "UPSTREAM_UNAVAILABLE"
    assert len(harness.window) == 0


# ------------------------------------------------------------------------------ GET /orders/{id}


async def test_e1_get_order_returns_every_field_of_the_document_each_from_its_own_source(
    harness: Any,
) -> None:
    harness.read_model.orders[ORDER_ID] = document()

    response = await harness.client.get(f"/orders/{ORDER_ID}", headers=harness.bearer())

    assert response.status_code == 200
    assert response.json() == {
        "orderId": str(ORDER_ID),
        "orderReference": "ORD-000042",
        "orderDate": "2026-08-18T10:15:00.100Z",
        "retailer": {"code": "RET-ES-01", "name": "Carrefour Espana", "gln": "8412345000013"},
        "company": {"code": "IBERFOODS", "name": "Iberfoods SA", "gln": "8412345000020"},
        "status": "stock_reserved",
        "cancellationReason": None,  # declared nullable: an explicit null, not an absent key
        "currency": "EUR",
        "totals": {"initialAmount": 124250, "initialDiscount": 5000, "totalAmount": 119250},
        "items": [
            {
                "productCode": "PRD-0001",
                "name": "Aceite 1L",
                "quantity": 5,
                "unitPrice": 24999,
                "lineDiscount": 250,
            },
            {"productCode": "PRD-0007", "quantity": 25, "unitPrice": 70, "lineDiscount": 0},
        ],
        "references": {
            "despatchReference": "DES-000031",
            "invoiceReference": None,
            "paymentReference": "PAY-2026-08-18-000019",
        },
        "events": [
            {
                "eventId": str(EVENT_A),
                "causationId": str(CAUSE),
                "eventType": "stock.reserved.v1",
                "occurredAt": "2026-08-18T10:16:01.250Z",
                "summary": "5 units reserved",
                "detail": {"units": 5},
            },
            {
                "eventId": str(EVENT_B),
                "eventType": "order.placed.v1",
                "occurredAt": "2026-08-18T10:15:00.100Z",
                "summary": "Order placed",
            },
        ],
        "headerComplete": True,
        "updatedAt": "2026-08-18T10:20:05.700Z",
    }


async def test_e1_the_detail_keeps_the_stored_event_order_it_was_given(harness: Any) -> None:
    harness.read_model.orders[ORDER_ID] = document()

    body = (await harness.client.get(f"/orders/{ORDER_ID}", headers=harness.bearer())).json()

    # A (10:16:01) is listed before B (10:15:00): the projector owns the order (R50); the Gateway
    # neither re-sorts nor reverses it.
    assert [e["eventId"] for e in body["events"]] == [str(EVENT_A), str(EVENT_B)]


async def test_get_order_of_a_placeholder_is_a_200_with_header_complete_false_and_no_header(
    harness: Any,
) -> None:
    harness.read_model.orders[ORDER_ID] = document(complete=False)

    response = await harness.client.get(f"/orders/{ORDER_ID}", headers=harness.bearer())

    assert response.status_code == 200
    body = response.json()
    assert body["headerComplete"] is False
    for absent in ("orderReference", "orderDate", "retailer", "company", "currency", "totals"):
        assert absent not in body, absent
    assert body["status"] == "stock_reserved"
    assert len(body["events"]) == 2  # the timeline is real


async def test_get_order_for_an_id_nobody_handed_out_is_a_404_problem(harness: Any) -> None:
    response = await harness.client.get(f"/orders/{ORDER_ID}", headers=harness.bearer())

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "NOT_FOUND"


async def test_r55_the_pending_answer_lasts_for_the_window_and_then_it_is_a_genuine_404(
    harness: Any,
) -> None:
    harness.window.record(ORDER_ID)
    assert (
        await harness.client.get(f"/orders/{ORDER_ID}", headers=harness.bearer())
    ).status_code == 202

    harness.clock.mono_ms += 300_001  # past GATEWAY_ISSUED_ORDER_WINDOW_TTL_MS

    assert (
        await harness.client.get(f"/orders/{ORDER_ID}", headers=harness.bearer())
    ).status_code == 404


async def test_get_order_once_projected_wins_over_the_window(harness: Any) -> None:
    harness.window.record(ORDER_ID)
    harness.read_model.orders[ORDER_ID] = document()

    response = await harness.client.get(f"/orders/{ORDER_ID}", headers=harness.bearer())

    assert response.status_code == 200
    assert response.json()["headerComplete"] is True


async def test_get_order_with_an_id_that_is_not_a_uuid_is_a_400(harness: Any) -> None:
    response = await harness.client.get("/orders/not-a-uuid", headers=harness.bearer())

    assert response.status_code == 400
    assert response.json()["errors"][0]["field"] == "id"


# ------------------------------------------------------------------------------ GET /orders


async def test_list_orders_returns_each_summary_field_and_the_page_info(harness: Any) -> None:
    harness.read_model.headers_in_list = [document()]
    harness.read_model.list_total = 57

    response = await harness.client.get("/orders?page=3&pageSize=10", headers=harness.bearer())

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "orderId": str(ORDER_ID),
                "orderReference": "ORD-000042",
                "orderDate": "2026-08-18T10:15:00.100Z",
                "retailer": {
                    "code": "RET-ES-01",
                    "name": "Carrefour Espana",
                    "gln": "8412345000013",
                },
                "company": {"code": "IBERFOODS", "name": "Iberfoods SA", "gln": "8412345000020"},
                "status": "stock_reserved",
                "cancellationReason": None,
                "currency": "EUR",
                "totals": {"initialAmount": 124250, "initialDiscount": 5000, "totalAmount": 119250},
                "updatedAt": "2026-08-18T10:20:05.700Z",
            }
        ],
        "page": {"page": 3, "pageSize": 10, "total": 57},
    }


async def test_list_orders_passes_each_filter_to_the_read_model_from_its_own_parameter(
    harness: Any,
) -> None:
    await harness.client.get(
        "/orders?status=placed&status=confirmed&retailerCode=RET-A&companyCode=CMP-B"
        "&orderReference=ORD-000099&page=2&pageSize=7",
        headers=harness.bearer(),
    )

    [seen] = harness.read_model.list_calls
    assert seen.statuses == ("placed", "confirmed")
    assert seen.retailer_code == "RET-A"
    assert seen.company_code == "CMP-B"
    assert seen.order_reference == "ORD-000099"
    assert (seen.page, seen.page_size) == (2, 7)


async def test_list_orders_defaults_and_refuses_what_the_contract_refuses(harness: Any) -> None:
    await harness.client.get("/orders", headers=harness.bearer())
    assert (harness.read_model.list_calls[0].page, harness.read_model.list_calls[0].page_size) == (
        1,
        25,
    )

    for query in (
        "page=0",
        "page=abc",
        "pageSize=0",
        "pageSize=201",
        "pageSize=1.5",
        "status=nope",
        "orderReference=X-1",
    ):
        response = await harness.client.get(f"/orders?{query}", headers=harness.bearer())
        assert response.status_code == 400, query


async def test_list_orders_never_calls_the_rpc_client(harness: Any) -> None:
    harness.read_model.headers_in_list = [document()]

    await harness.client.get("/orders", headers=harness.bearer())
    await harness.client.get(f"/orders/{ORDER_ID}", headers=harness.bearer())

    assert harness.rpc.calls == []


# ------------------------------------------------------------------------------ cancel


def cancelled_reply() -> asyncapi.OrdersCancelReplyPayload:
    return asyncapi.OrdersCancelReplyPayload(
        order_id=ORDER_ID,
        order_reference="ORD-000042",
        status=asyncapi.OrderStatus.credit_approved,
        compensation_planned=[
            asyncapi.CompensationPlannedEnum.stock_release,
            asyncapi.CompensationPlannedEnum.credit_release,
        ],
    )


async def test_cancel_order_answers_202_and_sends_the_order_id_as_the_correlation(
    harness: Any,
) -> None:
    harness.rpc.will_reply("orders.cancel", cancelled_reply())

    response = await harness.client.post(
        f"/orders/{ORDER_ID}/cancel", json={"note": "customer rang"}, headers=harness.bearer()
    )

    assert response.status_code == 202
    assert response.json() == {
        "orderId": str(ORDER_ID),
        "orderReference": "ORD-000042",
        "status": "credit_approved",
        "compensationPlanned": ["stock_release", "credit_release"],
    }
    [call] = harness.rpc.calls
    assert call.subject == "orders.cancel"
    assert call.wire == {
        "orderId": str(ORDER_ID),
        "reason": "operator_cancelled",
        "note": "customer rang",
    }
    assert call.correlation_id == ORDER_ID  # every fact of this order's saga carries it
    assert call.request_id != ORDER_ID


async def test_cancel_order_needs_no_body(harness: Any) -> None:
    harness.rpc.will_reply("orders.cancel", cancelled_reply())

    response = await harness.client.post(f"/orders/{ORDER_ID}/cancel", headers=harness.bearer())

    assert response.status_code == 202
    assert "note" not in harness.rpc.calls[0].wire


async def test_cancel_order_mapped_refusals_are_the_contracts_statuses(harness: Any) -> None:
    for code, status in (("ORDER_NOT_CANCELLABLE", 409), ("NOT_FOUND", 404)):
        harness.rpc.replies.clear()
        harness.rpc.will_reply("orders.cancel", RpcRemoteError("orders.cancel", code, "no", None))
        response = await harness.client.post(f"/orders/{ORDER_ID}/cancel", headers=harness.bearer())
        assert response.status_code == status, code
        assert response.json()["code"] == code


async def test_cancel_order_passes_the_responders_own_cancellation_reason_through(
    harness: Any,
) -> None:
    harness.rpc.will_reply(
        "orders.cancel",
        asyncapi.OrdersCancelReplyPayload(
            order_id=ORDER_ID,
            order_reference="ORD-000042",
            status=asyncapi.OrderStatus.cancelled,
            cancellation_reason=asyncapi.CancellationReason.operator_cancelled,
            compensation_planned=[],
        ),
    )

    response = await harness.client.post(f"/orders/{ORDER_ID}/cancel", headers=harness.bearer())

    assert response.status_code == 202
    assert response.json()["cancellationReason"] == "operator_cancelled"
    assert response.json()["compensationPlanned"] == []  # nothing had been acquired


async def test_cancel_order_refuses_a_reply_naming_a_reason_the_contract_does_not_allow(
    harness: Any,
) -> None:
    harness.rpc.will_reply(
        "orders.cancel",
        asyncapi.OrdersCancelReplyPayload(
            order_id=ORDER_ID,
            order_reference="ORD-000042",
            status=asyncapi.OrderStatus.cancelled,
            cancellation_reason=asyncapi.CancellationReason.stock_rejected,
            compensation_planned=[],
        ),
    )

    response = await harness.client.post(f"/orders/{ORDER_ID}/cancel", headers=harness.bearer())

    assert (response.status_code, response.json()["code"]) == (503, "UPSTREAM_UNAVAILABLE")


async def test_place_order_with_a_malformed_body_never_reaches_the_rpc_client(
    harness: Any,
) -> None:
    for body in ({**PLACE_BODY, "lines": []}, {**PLACE_BODY, "currency": "eur"}, {}):
        response = await harness.client.post("/orders", json=body, headers=harness.bearer())
        assert response.status_code == 400, body

    assert harness.rpc.calls == []
