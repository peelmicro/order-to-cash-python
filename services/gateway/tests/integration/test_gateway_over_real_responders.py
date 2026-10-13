"""The Gateway against the REAL responders (`docs/lessons.md:123`: #7's first gateway
rejection was a stub that shared the Gateway's assumption of the wire; #8's record says six of
its eight subjects were exercised only against stubs).

A seeded stack (the real seed, PostgreSQL, MongoDB, NATS) with the real Orders, Fulfillment and
Billing hosts and the real Gateway host, all in this test's loop, no stub on the wire. Proven here,
each through the Gateway's HTTP surface:

* `orders.create` (Orders, with Fulfillment's real `stock.check` behind it): a 201 whose every
  figure equals the ROW Orders stored; a stock shortage refused 409 with the shortages Fulfillment
  computed; an unknown product refused 404 by Orders' own `NOT_FOUND`;
* `billing.invoice.list`, `billing.credit.list` and `fulfillment.stock.list`: the Gateway's page
  equals the responder's own reply to the same question, key for key;
* `fulfillment.stock.replenish`: the stock row grew by the delta;
* `billing.payment.register`: the payment is sent under the invoice's ORDER id as
  `x-correlation-id` (acceptance item 6), proved by what Billing WROTE (the correlation id of the
  `payment.received.v1` and `credit.released.v1` outbox rows), and every refusal Billing really
  answers arrives as the status of `openapi.yaml:673-675` (acceptance item 7): already paid ->
  409 `INVOICE_ALREADY_PAID`, an amount or a currency mismatch -> 422 `PAYMENT_MISMATCH`, a reused
  reference -> 409 `PAYMENT_REFERENCE_REUSED`;
* an invoice whose order the read model does not hold -> a retryable 503, and nothing was paid;
* the catalog routes run against the real responder in
  services/orders/tests/integration/test_catalog_through_gateway.py, and the cancel route in
  services/orders/tests/integration/saga/test_cancel_through_gateway.py, which also keeps the
  real-NATS, HTTP-level proof that a route whose subject nobody serves answers 503
  `UPSTREAM_UNAVAILABLE` (feature 41, acceptance item 6; this stack serves every subject the
  Gateway calls, so that proof needs a Gateway with no Orders host).
"""

import json
import uuid
from typing import Any

import asyncpg
import pytest
from pymongo import AsyncMongoClient

from otc_contracts import format_instant, parse_fact
from otc_projector.application.projection import project
from otc_projector.infrastructure.messaging.idempotent_consumer import IdempotentConsumer
from otc_projector.infrastructure.persistence.mongo_read_model_writer import MongoReadModelWriter
from otc_projector.infrastructure.persistence.read_model_document import COLLECTION

pytestmark = pytest.mark.integration

ORDER = {
    "retailerCode": "AldiEs",
    "companyCode": "SPANATURAL",
    "currency": "EUR",
    "lines": [
        {"productCode": "PRD-0002", "quantity": 3, "lineDiscount": 125},
        {"productCode": "PRD-0008", "quantity": 2, "lineDiscount": 40},
    ],
    "notes": "gateway integration",
}
SECOND_ORDER = {
    "retailerCode": "LeroyMerlinFr",
    "companyCode": "OUTILFRANCE",
    "currency": "EUR",
    "lines": [{"productCode": "PRD-0004", "quantity": 4}],
}
PAYMENT_BASE = {"valueDate": "2026-10-12T08:30:00.000Z", "source": "test"}


def fact_document(row: asyncpg.Record) -> str:
    """An outbox row as the envelope the relay would publish (what the projector consumes)."""
    return json.dumps(
        {
            "eventId": str(row["event_id"]),
            "eventType": row["event_type"],
            "aggregateId": str(row["aggregate_id"]),
            "correlationId": str(row["correlation_id"]),
            "causationId": str(row["causation_id"]),
            "occurredAt": format_instant(row["occurred_at"]),
            "payload": json.loads(row["payload"]),
        }
    )


async def place(stack: Any, body: dict[str, Any], **headers: str) -> Any:
    return await stack.http.post("/orders", json=body, headers={**stack.auth, **headers})


async def project_order(stack: Any, order_id: str) -> None:
    """Project every fact Orders really wrote for this order through the REAL projector writer."""
    rows = await stack.rows(
        "orders", "SELECT * FROM outbox WHERE correlation_id = $1 ORDER BY seq", uuid.UUID(order_id)
    )
    assert [r["event_type"] for r in rows] == ["order.placed.v1"]
    client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(stack.databases.mongo.uri)
    try:
        collection = client.get_database(stack.databases.mongo.name).get_collection(COLLECTION)
        writer = MongoReadModelWriter(collection, IdempotentConsumer(collection))

        async def nothing(applied: Any) -> None:
            return None

        for row in rows:
            await writer.apply(project(parse_fact(fact_document(row))), after_applied=nothing)
    finally:
        await client.close()


def correlation(order_id: str) -> dict[str, str]:
    return {"x-correlation-id": order_id, "x-request-id": str(uuid.uuid4())}


async def issue_invoice(
    stack: Any, placed: dict[str, Any], order: dict[str, Any]
) -> dict[str, Any]:
    """The saga's two calls to Billing, made by hand over NATS with the order id as correlation:
    hold the credit, issue the invoice. (The Gateway has no route for either.)"""
    total = int(placed["totalAmount"])
    assert total % 100 != 99, "the credit simulator refuses a total ending in 99 (R42)"
    held = await stack.ask(
        "billing.credit.hold",
        {
            "orderReference": placed["orderReference"],
            "retailerCode": order["retailerCode"],
            "companyCode": order["companyCode"],
            "amount": {"amount": total, "currency": placed["currency"]},
        },
        correlation(placed["orderId"]),
    )
    assert held["outcome"] == "approved", held
    issued = await stack.ask(
        "billing.invoice.issue",
        {
            "orderReference": placed["orderReference"],
            "retailerCode": order["retailerCode"],
            "companyCode": order["companyCode"],
            "currency": placed["currency"],
            "lines": [
                {"productCode": line["productCode"], "units": line["quantity"], "unitPrice": price}
                for line, price in zip(order["lines"], placed["_prices"], strict=True)
            ],
            "discount": int(placed["initialDiscount"]),
        },
        correlation(placed["orderId"]),
    )
    assert issued["status"] == "issued", issued
    assert isinstance(issued, dict)
    return issued


async def unit_prices(stack: Any, order: dict[str, Any]) -> list[int]:
    rows = await stack.rows(
        "orders",
        "SELECT code, price FROM products WHERE code = ANY($1::text[])",
        [line["productCode"] for line in order["lines"]],
    )
    by_code = {r["code"]: int(r["price"]) for r in rows}
    return [by_code[line["productCode"]] for line in order["lines"]]


async def world(stack: Any, order: dict[str, Any]) -> dict[str, Any]:
    """Place `order` through the Gateway, project it, hold and issue its invoice at Billing."""
    response = await place(stack, order)
    assert response.status_code == 201, response.text
    placed: dict[str, Any] = response.json()
    placed["_prices"] = await unit_prices(stack, order)
    await project_order(stack, placed["orderId"])
    invoice = await issue_invoice(stack, placed, order)
    placed["invoice"] = invoice
    return placed


# --------------------------------------------------------------------------- orders.create


async def test_post_orders_is_a_201_whose_every_figure_equals_the_row_orders_stored(
    stack: Any,
) -> None:
    response = await place(stack, ORDER, **{"Idempotency-Key": str(uuid.uuid4())})

    assert response.status_code == 201, response.text
    body = response.json()
    [row] = await stack.rows(
        "orders",
        "SELECT o.*, c.code AS currency_code FROM orders o"
        " JOIN currencies c ON c.id = o.currency_id WHERE o.order_reference = $1",
        body["orderReference"],
    )
    assert body["orderId"] == str(row["id"])
    assert response.headers["x-correlation-id"] == body["orderId"]
    assert response.headers["location"] == f"/orders/{body['orderId']}"
    assert body["orderReference"] == "ORD-000007"  # the seed owns 000001..000006
    assert body["status"] == row["status"] == "placed"
    assert body["currency"] == row["currency_code"]
    # three different amounts, each from its own column of the stored row
    assert body["initialAmount"] == int(row["initial_amount"])
    assert body["initialDiscount"] == int(row["initial_discount"])
    assert body["totalAmount"] == int(row["total_amount"])
    assert len({body["initialAmount"], body["initialDiscount"], body["totalAmount"]}) == 3
    assert body["initialAmount"] == 3 * 1849 + 2 * 1489  # 8525, from the seeded product prices
    assert body["initialDiscount"] == 125 + 40  # the line discounts (Orders refuses orderDiscount)
    assert body["totalAmount"] == 8525 - 165
    assert body["projectionPending"] is True


async def test_an_idempotency_key_is_forwarded_and_a_repeat_returns_the_original_order(
    stack: Any,
) -> None:
    """The Gateway's half of R62 (feature 27, S2): `Idempotency-Key` travels as the payload's
    `requestId` (`tests/unit/test_gateway_orders_http.py` reads it off the wire) and Orders replays:
    the repeat returns the ORIGINAL order, no second row. This test used to pin the opposite (a
    repeat placed a second order while Orders stored NULL); feature 27 built the replay, as its
    docstring said it would, and the pin is rewritten to assert the original order returns."""
    key = {"Idempotency-Key": str(uuid.uuid4())}

    first = await place(stack, ORDER, **key)
    second = await place(stack, ORDER, **key)

    assert first.status_code == second.status_code == 201
    assert first.json()["orderId"] == second.json()["orderId"]
    assert first.json() == second.json(), "the replay answers the original order, field by field"
    [count] = await stack.rows("orders", "SELECT count(*) AS n FROM orders")
    assert count["n"] == 7  # the six seeded and ONE new order
    [stored] = await stack.rows(
        "orders", "SELECT count(request_id) AS n FROM orders WHERE order_reference > 'ORD-000006'"
    )
    assert stored["n"] == 1


async def test_a_stock_shortage_is_a_409_with_the_shortages_fulfillment_computed(
    stack: Any,
) -> None:
    [stock] = await stack.rows(
        "fulfillment",
        "SELECT units, reserved_units FROM stock WHERE company_code = 'SPANATURAL'"
        " AND product_code = 'PRD-0002'",
    )
    available = int(stock["units"]) - int(stock["reserved_units"])
    demanded = available + 7
    body = {**ORDER, "lines": [{"productCode": "PRD-0002", "quantity": demanded}]}

    response = await place(stack, body)

    assert response.status_code == 409
    assert response.headers["content-type"] == "application/problem+json"
    problem = response.json()
    assert problem["code"] == "STOCK_UNAVAILABLE"
    assert problem["shortages"] == [
        {"productCode": "PRD-0002", "requested": demanded, "available": available}
    ]
    [count] = await stack.rows("orders", "SELECT count(*) AS n FROM orders")
    assert count["n"] == 6  # nothing was created


async def test_an_unknown_product_is_a_404_by_orders_own_not_found(stack: Any) -> None:
    body = {**ORDER, "lines": [{"productCode": "PRD-9999", "quantity": 1}]}

    response = await place(stack, body)

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


async def test_post_orders_with_a_non_integer_quantity_never_reaches_orders(stack: Any) -> None:
    body = {**ORDER, "lines": [{"productCode": "PRD-0002", "quantity": 2.5}]}

    response = await place(stack, body)

    assert response.status_code == 400
    [count] = await stack.rows("orders", "SELECT count(*) AS n FROM orders")
    assert count["n"] == 6


# --------------------------------------------------------------------------- the read halves


async def test_a_placed_order_is_pending_until_the_projector_has_written_it(stack: Any) -> None:
    placed = (await place(stack, ORDER)).json()

    pending = await stack.http.get(f"/orders/{placed['orderId']}", headers=stack.auth)
    assert pending.status_code == 202
    assert pending.json()["status"] == "projection_pending"
    assert pending.headers["retry-after"] == "2"

    await project_order(stack, placed["orderId"])

    found = await stack.http.get(f"/orders/{placed['orderId']}", headers=stack.auth)
    assert found.status_code == 200
    detail = found.json()
    assert detail["headerComplete"] is True
    assert detail["status"] == "placed"
    assert detail["orderReference"] == placed["orderReference"]
    assert detail["totals"] == {
        "initialAmount": placed["initialAmount"],
        "initialDiscount": placed["initialDiscount"],
        "totalAmount": placed["totalAmount"],
    }
    assert [e["eventType"] for e in detail["events"]] == ["order.placed.v1"]


# --------------------------------------------------------------------------- list routes


async def test_stock_credits_and_invoices_equal_the_responders_own_reply(stack: Any) -> None:
    headers = {"x-correlation-id": str(uuid.uuid4()), "x-request-id": str(uuid.uuid4())}
    cases = [
        (
            "/stock?companyCode=SPANATURAL&pageSize=5",
            "fulfillment.stock.list",
            {"companyCode": "SPANATURAL", "page": 1, "pageSize": 5},
        ),
        (
            "/credits?retailerCode=AldiEs&pageSize=3",
            "billing.credit.list",
            {"retailerCode": "AldiEs", "page": 1, "pageSize": 3},
        ),
        ("/invoices?pageSize=4", "billing.invoice.list", {"page": 1, "pageSize": 4}),
    ]
    for path, subject, request in cases:
        direct = await stack.ask(subject, request, headers)
        response = await stack.http.get(path, headers=stack.auth)
        assert response.status_code == 200, (path, response.text)
        assert response.json() == direct, path
        assert response.json()["items"], f"{path}: an empty page proves nothing"


async def test_replenish_adds_the_delta_to_the_stock_row(stack: Any) -> None:
    sql = "SELECT units FROM stock WHERE company_code = 'SPANATURAL' AND product_code = 'PRD-0005'"
    [before] = await stack.rows("fulfillment", sql)

    response = await stack.http.post(
        "/stock/replenish",
        json={"companyCode": "SPANATURAL", "lines": [{"productCode": "PRD-0005", "units": 37}]},
        headers=stack.auth,
    )

    assert response.status_code == 200, response.text
    [after] = await stack.rows("fulfillment", sql)
    assert int(after["units"]) == int(before["units"]) + 37
    [item] = response.json()["items"]
    assert (item["productCode"], item["units"]) == ("PRD-0005", int(after["units"]))


async def test_an_unknown_stock_item_is_refused_404_by_fulfillment(stack: Any) -> None:
    response = await stack.http.post(
        "/stock/replenish",
        json={"companyCode": "SPANATURAL", "lines": [{"productCode": "PRD-9999", "units": 1}]},
        headers=stack.auth,
    )

    assert response.status_code == 404


# --------------------------------------------------------------------------- payments (R47 - R49)


async def test_the_payment_is_sent_under_the_orders_id_and_billing_wrote_the_facts_under_it(
    stack: Any,
) -> None:
    placed = await world(stack, ORDER)
    invoice = placed["invoice"]
    invoice_id = invoice["invoiceId"]
    assert len({placed["orderId"], invoice_id}) == 2
    payment = {
        **PAYMENT_BASE,
        "paymentReference": "BANK-GW-0001",
        "amount": {"amount": invoice["totalAmount"], "currency": "EUR"},
    }

    response = await stack.http.post(
        f"/invoices/{invoice_id}/payments", json=payment, headers=stack.auth
    )

    assert response.status_code == 201, response.text
    assert response.headers["x-correlation-id"] == placed["orderId"]
    assert response.json()["outcome"] == "accepted"
    assert response.json()["invoiceStatus"] == "paid"
    assert response.json()["orderReference"] == placed["orderReference"]
    facts = await stack.rows(
        "billing",
        "SELECT event_type, correlation_id, causation_id FROM outbox"
        " WHERE event_type IN ('payment.received.v1', 'credit.released.v1')"
        " AND correlation_id = $1 ORDER BY seq",
        uuid.UUID(placed["orderId"]),
    )
    assert [f["event_type"] for f in facts] == ["payment.received.v1", "credit.released.v1"]
    for fact in facts:
        assert str(fact["correlation_id"]) == placed["orderId"]  # not the invoice id
        assert str(fact["causation_id"]) not in (placed["orderId"], invoice_id)  # the request id
    [paid] = await stack.rows(
        "billing", "SELECT status FROM invoices WHERE id = $1", uuid.UUID(invoice_id)
    )
    assert paid["status"] == "paid"


async def test_a_replay_is_a_200_duplicate_and_emits_no_second_fact(stack: Any) -> None:
    placed = await world(stack, ORDER)
    invoice = placed["invoice"]
    payment = {
        **PAYMENT_BASE,
        "paymentReference": "BANK-GW-0002",
        "amount": {"amount": invoice["totalAmount"], "currency": "EUR"},
    }
    path = f"/invoices/{invoice['invoiceId']}/payments"
    first = await stack.http.post(path, json=payment, headers=stack.auth)
    [before] = await stack.rows("billing", "SELECT count(*) AS n FROM outbox")

    replay = await stack.http.post(path, json=payment, headers=stack.auth)

    assert (first.status_code, replay.status_code) == (201, 200)
    assert replay.headers["idempotent-replay"] == "true"
    assert replay.json()["outcome"] == "duplicate"
    [after] = await stack.rows("billing", "SELECT count(*) AS n FROM outbox")
    assert after["n"] == before["n"]


async def test_every_refusal_billing_answers_arrives_as_the_status_the_contract_declares(
    stack: Any,
) -> None:
    first = await world(stack, ORDER)
    second = await world(stack, SECOND_ORDER)
    one, two = first["invoice"], second["invoice"]
    assert one["totalAmount"] != two["totalAmount"]

    def pay(invoice: dict[str, Any], reference: str, **amount: Any) -> dict[str, Any]:
        return {
            **PAYMENT_BASE,
            "paymentReference": reference,
            "amount": {"amount": invoice["totalAmount"], "currency": "EUR", **amount},
        }

    async def post(invoice: dict[str, Any], body: dict[str, Any]) -> Any:
        return await stack.http.post(
            f"/invoices/{invoice['invoiceId']}/payments", json=body, headers=stack.auth
        )

    wrong_amount = await post(two, pay(two, "BANK-GW-0010", amount=two["totalAmount"] + 1))
    wrong_currency = await post(two, pay(two, "BANK-GW-0011", currency="USD"))
    assert (wrong_amount.status_code, wrong_amount.json()["code"]) == (422, "PAYMENT_MISMATCH")
    assert (wrong_currency.status_code, wrong_currency.json()["code"]) == (422, "PAYMENT_MISMATCH")

    assert (await post(one, pay(one, "BANK-GW-0020"))).status_code == 201
    other_reference = await post(one, pay(one, "BANK-GW-0021"))
    assert (other_reference.status_code, other_reference.json()["code"]) == (
        409,
        "INVOICE_ALREADY_PAID",
    )

    reused = await post(two, pay(two, "BANK-GW-0020"))  # the reference invoice ONE was paid with
    assert (reused.status_code, reused.json()["code"]) == (409, "PAYMENT_REFERENCE_REUSED")
    [still_issued] = await stack.rows(
        "billing", "SELECT status FROM invoices WHERE id = $1", uuid.UUID(two["invoiceId"])
    )
    assert still_issued["status"] == "issued"  # none of the refusals changed anything


async def test_an_invoice_that_does_not_exist_is_a_404_and_one_whose_order_is_not_projected_a_503(
    stack: Any,
) -> None:
    unknown = await stack.http.post(
        f"/invoices/{uuid.uuid4()}/payments",
        json={
            **PAYMENT_BASE,
            "paymentReference": "BANK-GW-0030",
            "amount": {"amount": 1, "currency": "EUR"},
        },
        headers=stack.auth,
    )
    assert (unknown.status_code, unknown.json()["code"]) == (404, "NOT_FOUND")

    # an order placed but never projected: its invoice exists at Billing, its order is not in Mongo
    response = await place(stack, SECOND_ORDER)
    placed = response.json()
    placed["_prices"] = await unit_prices(stack, SECOND_ORDER)
    invoice = await issue_invoice(stack, placed, SECOND_ORDER)
    payments_before = await stack.rows("billing", "SELECT count(*) AS n FROM payments")

    unprojected = await stack.http.post(
        f"/invoices/{invoice['invoiceId']}/payments",
        json={
            **PAYMENT_BASE,
            "paymentReference": "BANK-GW-0031",
            "amount": {"amount": invoice["totalAmount"], "currency": "EUR"},
        },
        headers=stack.auth,
    )

    assert unprojected.status_code == 503
    assert unprojected.headers["retry-after"] == "2"
    assert await stack.rows("billing", "SELECT count(*) AS n FROM payments") == payments_before
