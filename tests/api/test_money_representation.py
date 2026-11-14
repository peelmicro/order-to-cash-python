# ruff: noqa: E501 - test names are the sentences the acceptance items use
"""Feature 31, acceptance item 6: R1's API half, `api/money-representation.spec` of the test matrix.

"Every monetary field of every response is an integer accompanied by a currency code", found by
SHAPE (`api_support.sweep_for_money_fields`, the port of #8's `MoneyFieldSweep`), over responses
the Gateway really sent on a real socket (`api.seen`), never over a list of field names.

The POPULATION is derived, not listed: `money_bearing_cells` walks `specs/shared/openapi.yaml`
(and the served app's own generated document) and finds every (method, path, status) whose
response schema reaches `MinorUnits` or `Money`. The expected set below is a literal; the test
fails on any difference in either direction. Every other cell of the contract is either DRIVEN
(and must sweep to nothing: no money where none is declared) or in `NOT_DRIVEN`, a literal with a
reason per group; `ALL cells - MONEY - DRIVEN - NOT_DRIVEN` must be empty.
"""

import re
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.integration
support: Any = sys.modules["api_support"]

OPENAPI = Path(__file__).resolve().parents[2] / "specs" / "shared" / "openapi.yaml"

MONEY_BEARING = frozenset(
    {
        "POST /orders 201",
        "GET /orders 200",
        "GET /orders/{id} 200",
        "GET /invoices 200",
        "GET /credits 200",
        "GET /catalog/products 200",
    }
)
# Driven and swept; the schema declares no money, so the sweep must find none.
DRIVEN_WITHOUT_MONEY = frozenset(
    {
        "POST /auth/login 200",
        "POST /auth/login 400",
        "POST /auth/login 401",
        "GET /auth/me 200",
        "GET /auth/me 401",
        "POST /orders 400",
        "POST /orders 409",
        "GET /orders 400",
        "GET /orders/{id} 404",
        "GET /orders/{id} default",
        "POST /orders/{id}/cancel 404",
        "POST /orders/{id}/cancel 409",
        "GET /stock 200",
        "POST /stock/replenish 200",
        "POST /stock/replenish 400",
        "POST /stock/replenish 404",
        "POST /invoices/{id}/payments 201",
        "POST /invoices/{id}/payments 200",
        "POST /invoices/{id}/payments 400",
        "POST /invoices/{id}/payments 404",
        "POST /invoices/{id}/payments 409",
        "POST /invoices/{id}/payments 422",
        "GET /catalog/retailers 200",
        "GET /catalog/companies 200",
        "GET /health/live 200",
        "GET /health/ready 200",
    }
)
NOT_DRIVEN = frozenset(
    {
        # needs a dependency to be down or the login limit to be exhausted: the degraded-mode and throttle suites own them (features 22, 25, 27); their bodies are Problems, whose schemas reach no MinorUnits
        "POST /auth/login 429",
        "POST /orders 503",
        "POST /orders/{id}/cancel 503",
        "GET /stock 503",
        "POST /stock/replenish 503",
        "GET /invoices 503",
        "POST /invoices/{id}/payments 503",
        "GET /credits 503",
        "GET /catalog/products 503",
        "GET /catalog/retailers 503",
        "GET /catalog/companies 503",
        "GET /health/ready 503",
        # statuses outside the declared list: not driven here (the 404/400 problems that map to `default` are driven below)
        "POST /auth/login default",
        "GET /auth/me default",
        "POST /orders default",
        "GET /orders default",
        "POST /orders/{id}/cancel default",
        "GET /stock default",
        "POST /stock/replenish default",
        "GET /invoices default",
        "POST /invoices/{id}/payments default",
        "GET /credits default",
        "GET /catalog/products default",
        "GET /catalog/retailers default",
        "GET /catalog/companies default",
        "GET /health/live default",
        "GET /health/ready default",
        # the 401 is the same middleware answer on every protected operation: driven once on GET /auth/me and once on GET /orders (scenario 4)
        "POST /orders 401",
        "GET /orders 401",
        "GET /orders/{id} 401",
        "POST /orders/{id}/cancel 401",
        "GET /stock 401",
        "POST /stock/replenish 401",
        "GET /invoices 401",
        "POST /invoices/{id}/payments 401",
        "GET /credits 401",
        "GET /catalog/products 401",
        "GET /catalog/retailers 401",
        "GET /catalog/companies 401",
        # POST /orders 422 is not reachable from outside (the aggregate refuses earlier with 400/404, measured), GET /orders/{id} 202 and POST .../cancel 202 race the saga; none of their schemas reaches MinorUnits
        "POST /orders 422",
        "GET /orders/{id} 202",
        "POST /orders/{id}/cancel 202",
        # text/event-stream, not JSON: frames are OrderStreamUpdate (eventId, orderId, status, occurredAt), no MinorUnits in the schema; owned by feature 26
        "GET /orders/stream 200",
        "GET /orders/stream 401",
        "GET /orders/stream default",
        # HTML (Swagger UI), not JSON
        "GET /docs 200",
        "GET /docs default",
    }
)
# The fewest money fields one response of the kind always carries, per item, from the schema
# (`openapi.yaml`): PlaceOrderResponse 3 (initialAmount, initialDiscount, totalAmount); OrderSummary
# 3 (`totals`); OrderDetail 3 + 3 per line (unitPrice, lineDiscount and, by the sweep's disclosed over-inclusion, quantity); Invoice 3 (amount, discount,
# totalAmount); Credit 4 (creditLimit, activeHolds, openExposure, availableCredit); Product 1 (price).
PER_ITEM_MINIMUM = {
    "POST /orders 201": (None, 3),
    "GET /orders 200": ("items", 3),
    "GET /orders/{id} 200": (None, 6),  # one line: 3 totals + unitPrice, lineDiscount, quantity
    "GET /invoices 200": ("items", 3),
    "GET /credits 200": ("items", 4),
    "GET /catalog/products 200": ("items", 1),
}
JSON_TYPES = ("application/json", "application/problem+json")


def cells_of(document: dict[str, Any]) -> set[str]:
    return {
        f"{method.upper()} {path} {status}"
        for path, operations in document["paths"].items()
        for method, operation in operations.items()
        if method in ("get", "post")
        for status in operation["responses"]
    }


def operations_of(document: dict[str, Any]) -> set[str]:
    return {
        f"{method.upper()} {path}"
        for path, operations in document["paths"].items()
        for method in operations
        if method in ("get", "post")
    }


def reaches_money(node: Any, document: dict[str, Any], seen: frozenset[str] = frozenset()) -> bool:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            if ref.endswith("/MinorUnits") or ref.endswith("/Money"):
                return True
            if ref in seen:
                return False
            target: Any = document
            for part in ref.removeprefix("#/").split("/"):
                target = target[part]
            return reaches_money(target, document, seen | {ref})
        return any(reaches_money(v, document, seen) for v in node.values())
    if isinstance(node, list):
        return any(reaches_money(v, document, seen) for v in node)
    return False


def money_bearing_cells(document: dict[str, Any]) -> set[str]:
    return {
        f"{method.upper()} {path} {status}"
        for path, operations in document["paths"].items()
        for method, operation in operations.items()
        if method in ("get", "post")
        for status, response in operation["responses"].items()
        if reaches_money(response, document)
    }


def test_r1_the_money_bearing_responses_of_the_contract_are_exactly_the_literal_set_and_every_other_cell_is_accounted_for() -> (
    None
):
    document = yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))

    derived = money_bearing_cells(document)

    assert derived - MONEY_BEARING == set(), (
        f"a response reaches MinorUnits but is not in the literal: {derived - MONEY_BEARING}"
    )
    assert MONEY_BEARING - derived == set(), (
        f"the literal names a response that reaches no MinorUnits: {MONEY_BEARING - derived}"
    )
    every = cells_of(document)
    assert len(every) == 79, "the contract's (method, path, status) cells"
    assert every == MONEY_BEARING | DRIVEN_WITHOUT_MONEY | NOT_DRIVEN
    assert every - MONEY_BEARING - DRIVEN_WITHOUT_MONEY - NOT_DRIVEN == set(), (
        "a cell nobody accounted for"
    )
    assert (
        (MONEY_BEARING & DRIVEN_WITHOUT_MONEY)
        == (MONEY_BEARING & NOT_DRIVEN)
        == (DRIVEN_WITHOUT_MONEY & NOT_DRIVEN)
        == set()
    )
    assert not any(c.startswith("GET /orders/stream") for c in derived), (
        "the SSE frames carry no money"
    )


async def drive_every_operation(api: Any) -> dict[str, Any]:
    """Send the requests whose cells the two literals above promise; return the ids the arms use."""
    anonymous = await api.call("GET", "/auth/me", headers={"Authorization": ""})
    assert anonymous.status_code == 401
    assert (await api.call("GET", "/auth/me")).status_code == 200
    login = {"username": "operator", "password": "wrong-password"}
    assert (await api.call("POST", "/auth/login", json=login)).status_code == 401
    assert (await api.call("POST", "/auth/login", json={"username": "operator"})).status_code == 400
    good = await api.call(
        "POST", "/auth/login", json={"username": "operator", "password": api.operator_password}
    )
    assert good.status_code == 200

    placed = await api.place(unit_price=1500, quantity=2)
    await api.wait_order(placed["orderId"], "invoiced")
    invoice = await api.invoice_of(placed["orderReference"])
    reference = f"PAY-SWEEP-{uuid.uuid4().hex[:10]}"
    assert (await api.pay(invoice, reference)).status_code == 201
    assert (await api.pay(invoice, reference)).status_code == 200
    assert (await api.pay(invoice, f"PAY-OTHER-{uuid.uuid4().hex[:10]}")).status_code == 409
    other = await api.place(unit_price=1700, quantity=1)
    await api.wait_order(other["orderId"], "invoiced")
    other_invoice = await api.invoice_of(other["orderReference"])
    assert (
        await api.pay(other_invoice, f"PAY-BAD-{uuid.uuid4().hex[:10]}", amount=1)
    ).status_code == 422
    assert (
        await api.call(
            "POST",
            "/invoices/{id}/payments",
            f"/invoices/{uuid.uuid4()}/payments",
            json={
                "paymentReference": "PAY-NOBODY-0001",
                "amount": {"amount": 1, "currency": "EUR"},
                "valueDate": "2026-10-13T08:30:00.000Z",
                "source": "test",
            },
        )
    ).status_code == 404
    assert (
        await api.call(
            "POST", "/invoices/{id}/payments", f"/invoices/{invoice['invoiceId']}/payments", json={}
        )
    ).status_code == 400
    assert (
        await api.call("POST", "/orders/{id}/cancel", f"/orders/{other['orderId']}/cancel", json={})
    ).status_code == 409
    assert (
        await api.call("POST", "/orders/{id}/cancel", f"/orders/{uuid.uuid4()}/cancel", json={})
    ).status_code == 404
    done = await api.wait_order(placed["orderId"], "completed")

    body = {"retailerCode": "AldiEs", "companyCode": "SPANATURAL", "currency": "EUR"}
    assert (await api.call("POST", "/orders", json={**body, "lines": []})).status_code == 400
    short = await api.call(
        "POST", "/orders", json={**body, "lines": [{"productCode": "PRD-0002", "quantity": 999999}]}
    )
    assert short.status_code == 409
    assert (await api.call("GET", "/orders", "/orders?page=0")).status_code == 400
    assert (await api.call("GET", "/orders/{id}", f"/orders/{uuid.uuid4()}")).status_code == 404
    assert (await api.call("GET", "/orders/{id}", "/orders/not-a-uuid")).status_code == 400
    for template in (
        "/orders",
        "/invoices",
        "/credits",
        "/stock",
        "/catalog/products",
        "/catalog/retailers",
        "/catalog/companies",
        "/health/live",
        "/health/ready",
    ):
        assert (await api.call("GET", template)).status_code == 200
    assert (
        await api.call("GET", "/orders/{id}", f"/orders/{placed['orderId']}")
    ).status_code == 200
    replenish = {"companyCode": "SPANATURAL", "lines": [{"productCode": "PRD-0002", "units": 5}]}
    assert (await api.call("POST", "/stock/replenish", json=replenish)).status_code == 200
    assert (
        await api.call("POST", "/stock/replenish", json={**replenish, "lines": []})
    ).status_code == 400
    unknown = {**replenish, "lines": [{"productCode": "NOPE-0000", "units": 5}]}
    assert (await api.call("POST", "/stock/replenish", json=unknown)).status_code == 404
    return {
        "detail_text": next(
            s.text
            for s in reversed(api.seen)
            if s.template == "/orders/{id}" and s.status == 200 and "completed" in s.text
        ),
        "done": done,
    }


DETAIL_MINIMUM = PER_ITEM_MINIMUM["GET /orders/{id} 200"][1]


def sweep(label: str, text: str, minimum: int) -> list[Any]:
    body = support.parse_json(text)
    findings = support.sweep_for_money_fields(body)
    support.check_money_findings(label, findings, minimum=minimum)
    assert support.find_decimal_numbers(body) == [], f"{label}: a decimal number on the wire"
    return list(findings)


def minimum_for(cell: str, body: Any) -> int:
    if cell == "GET /orders/{id} 200" and body.get("headerComplete") is False:
        # R50: facts may arrive before `order.placed.v1`; the projection then has no header, so no
        # currency and no totals YET (found as a one-in-six flake: the poll saw such a document)
        return 0
    key, per_item = PER_ITEM_MINIMUM[cell]
    return per_item * (len(body[key]) if key else 1)


async def test_r1_every_monetary_field_of_every_gateway_response_is_an_integer_accompanied_by_a_currency_code(
    api: Any,
) -> None:
    served = api.fleet.gateway.openapi()
    contract = yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))
    assert operations_of(served) == operations_of(contract), (
        "the served route table is the contract's 18 operations"
    )
    # (the served document inlines MinorUnits as `integer`, so money is derived from the contract;
    # the served table is what proves the contract's cells are routes this app really serves)
    assert cells_of(served) >= MONEY_BEARING, "a money-bearing response the app does not serve"

    driven_info = await drive_every_operation(api)
    # the R50 exemption below is for poll-time documents only: the COMPLETED order's detail is
    # complete by construction, and it meets its minimum whatever the response says of itself
    completed_detail = support.parse_json(driven_info["detail_text"])
    assert completed_detail.get("headerComplete") is not False, "the completed order has no header"
    sweep("GET /orders/{id} 200 (the completed order)", driven_info["detail_text"], DETAIL_MINIMUM)

    allowed = {r["code"] for r in await api.fleet.rows("orders", "SELECT code FROM currencies")}
    assert "EUR" in allowed
    contract_cells = cells_of(contract)
    driven: set[str] = set()
    money_seen: dict[str, int] = {}
    observed_currencies: set[str] = set()
    for seen in api.seen:
        cell = f"{seen.method} {seen.template} {seen.status}"
        if cell not in contract_cells:
            cell = f"{seen.method} {seen.template} default"  # a status the operation does not list
        if not seen.content_type.startswith(JSON_TYPES):
            continue
        body = support.parse_json(seen.text)
        findings = support.sweep_for_money_fields(body)
        if cell in MONEY_BEARING:
            minimum = minimum_for(cell, body)
            sweep(f"{cell}", seen.text, minimum)
            money_seen[cell] = money_seen.get(cell, 0) + len(findings)
            observed_currencies |= {f.currency for f in findings}
        else:
            assert findings == [], (
                f"{cell}: money found where the contract declares none: {[f.path for f in findings]}"
            )
            assert support.find_decimal_numbers(body) == [], f"{cell}: a decimal number on the wire"
        driven.add(cell)

    assert driven >= MONEY_BEARING, f"money-bearing cells never driven: {MONEY_BEARING - driven}"
    assert driven >= DRIVEN_WITHOUT_MONEY, (
        f"cells promised but never driven: {DRIVEN_WITHOUT_MONEY - driven}"
    )
    assert set(money_seen) == MONEY_BEARING
    assert observed_currencies <= allowed, (
        f"a currency no service holds: {observed_currencies - allowed}"
    )
    assert {"EUR", "GBP", "USD"} <= observed_currencies, (
        "the seeded lists carry more than one currency"
    )


async def test_r1_a_wrong_shape_currency_or_a_non_integer_amount_injected_into_a_real_response_fails_naming_the_field_path(
    api: Any,
) -> None:
    """The arms of acceptance item 6, on bytes the Gateway really sent: GET /orders/{id} of a
    completed order (totals one level down, items two levels down in an array)."""
    placed = await api.place(unit_price=1500, quantity=2)
    await api.wait_order(placed["orderId"], "invoiced")
    real = (await api.call("GET", "/orders/{id}", f"/orders/{placed['orderId']}")).text
    assert len(sweep("real GET /orders/{id}", real, DETAIL_MINIMUM)) == DETAIL_MINIMUM, (
        "control: the unmodified response passes"
    )

    def injected(label: str, text: str, *must_name: str) -> None:
        assert text != real, f"{label}: the injection changed nothing"
        with pytest.raises(AssertionError) as failure:
            sweep(label, text, DETAIL_MINIMUM)
        for fragment in must_name:
            assert fragment in str(failure.value), (
                f"{label}: the failure does not name {fragment!r}: {failure.value}"
            )

    for wrong in ("eur", "EURO", "EU", "", "EUR\\n", " EUR"):
        injected(
            f"currency {wrong!r}",
            real.replace('"currency":"EUR"', f'"currency":"{wrong}"'),
            "$.totals.totalAmount",
            "currency",
        )
    injected(
        "currency null",
        real.replace('"currency":"EUR"', '"currency":null'),
        "$.totals.totalAmount",
        "currency",
    )
    injected(
        "currency number",
        real.replace('"currency":"EUR"', '"currency":978'),
        "$.items[0].unitPrice",
        "currency",
    )
    for decimal in ("3000.0", "3000.50", "3e3", "3E+3", "-0.0"):
        injected(
            f"totalAmount {decimal}",
            re.sub(r'"totalAmount":\d+', f'"totalAmount":{decimal}', real),
            "$.totals.totalAmount",
            "integer",
        )
    # a string or a bool under a key other than `amount` is not a JSON number, so the SHAPE sweep
    # cannot name it (#7 and #8 share this limit); the tight per-kind minimum catches the field
    # that stopped being a number (6 expected, 5 found)
    injected(
        "unitPrice string",
        real.replace('"unitPrice":1500', '"unitPrice":"15.00"'),
        "fewer than",
        "vacuous",
    )
    injected("unitPrice true", real.replace('"unitPrice":1500', '"unitPrice":true'), "fewer than")
    injected(
        "initialAmount beyond bigint",
        real.replace('"initialAmount":3000', '"initialAmount":9223372036854775808'),
        "$.totals.initialAmount",
        "bigint",
    )
    injected(
        "the currency is dropped", real.replace('"currency":"EUR",', "", 1), "fewer than", "vacuous"
    )
