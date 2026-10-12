"""#8 defect D1: the Gateway's RPC subjects and request payloads are asserted AGAINST
`specs/shared/asyncapi.yaml`, never against themselves.

* Subjects: the set of `address:` lines whose channel summary names the Gateway as the caller
  (`Caller — gateway`) is read from the YAML and must equal `rpc_subjects`' eight constants, in
  both directions: a constant the contract does not declare, and a declared Gateway-called
  subject with no constant, each fail by name.
* Payloads: every handler is driven with EVERY optional field supplied, and the keys of the body the
  fake responder receives must equal the `properties` of the request schema in the YAML, in both
  directions (a key the Gateway sends that the contract does not declare; a declared key it drops).
"""

import re
from pathlib import Path
from typing import Any
from uuid import UUID

import yaml

from otc_contracts.generated import asyncapi
from otc_gateway.application import rpc_subjects

ASYNCAPI = yaml.safe_load(
    (Path(__file__).resolve().parents[4] / "specs/shared/asyncapi.yaml").read_text(encoding="utf-8")
)
SUBJECT_CONSTANTS = {
    name: value
    for name, value in vars(rpc_subjects).items()
    if name.isupper() and isinstance(value, str)
}


def gateway_called_addresses() -> set[str]:
    return {
        channel["address"]
        for channel in ASYNCAPI["channels"].values()
        if channel.get("address")
        and re.search(r"Caller\s*[\u2014-]+\s*gateway", channel.get("summary", ""))
    }


# A declared key the Gateway deliberately does not send, with the reason. `billing.payment.register`
# takes the invoice as `invoiceId` OR `invoiceReference` (one is required: `payment_wire.py`); the
# path of `POST /invoices/{id}/payments` carries the id, so the reference is the unused alternative.
# Likewise `orders.cancel` (`orderId` OR `orderReference`; the path carries the id).
NOT_SENT = {
    "billing.payment.register": {"invoiceReference"},
    "orders.cancel": {"orderReference"},
}


def declared_keys(schema: dict[str, Any]) -> set[str]:
    """The property names of a schema: its own, plus those of every `allOf` member (a `$ref` is
    followed), as `StockListRequestPayload = PageRequest + {companyCode, ...}` needs."""
    if "$ref" in schema:
        return declared_keys(ASYNCAPI["components"]["schemas"][schema["$ref"].rsplit("/", 1)[-1]])
    keys = set(schema.get("properties", {}))
    for member in schema.get("allOf", []):
        keys |= declared_keys(member)
    return keys


def request_schema(address: str) -> dict[str, Any]:
    for channel in ASYNCAPI["channels"].values():
        if channel.get("address") == address:
            message = ASYNCAPI["components"]["messages"][
                channel["messages"]["request"]["$ref"].rsplit("/", 1)[-1]
            ]
            name = message["payload"]["$ref"].rsplit("/", 1)[-1]
            schema: dict[str, Any] = ASYNCAPI["components"]["schemas"][name]
            return schema
    raise AssertionError(f"{address} is not a channel of asyncapi.yaml")


def test_the_gateways_subjects_are_exactly_the_channels_the_contract_says_it_calls() -> None:
    assert set(SUBJECT_CONSTANTS.values()) == gateway_called_addresses()
    assert len(SUBJECT_CONSTANTS) == len(gateway_called_addresses()) == 8


def test_the_contract_says_gateway_for_exactly_the_channels_the_gateway_calls() -> None:
    """The population is read by a phrase: a channel summary reworded would drop out of it, so the
    expected addresses are also a literal here."""
    assert gateway_called_addresses() == {
        "orders.create",
        "orders.cancel",
        "fulfillment.stock.list",
        "fulfillment.stock.replenish",
        "billing.credit.list",
        "billing.invoice.list",
        "billing.payment.register",
        "catalog.reference.list",
    }


async def test_every_request_the_gateway_sends_carries_exactly_the_contracts_keys(
    harness: Any,
) -> None:
    from datetime import UTC, datetime

    order_id = UUID("11111111-1111-4111-8111-111111111111")
    harness.read_model.by_reference["ORD-000042"] = order_id
    page = asyncapi.PageInfo(page=1, page_size=1, total=0)
    harness.rpc.will_reply(
        "orders.create",
        asyncapi.OrdersCreateReplyPayload(
            order_id=order_id,
            order_reference="ORD-000042",
            status="placed",
            currency="EUR",
            total_amount=1,
            order_date=datetime.now(UTC),
        ),
    )
    harness.rpc.will_reply(
        "orders.cancel",
        asyncapi.OrdersCancelReplyPayload(
            order_id=order_id,
            order_reference="ORD-000042",
            status=asyncapi.OrderStatus.placed,
            compensation_planned=[],
        ),
    )
    harness.rpc.will_reply(
        "fulfillment.stock.list", asyncapi.StockListReplyPayload(items=[], page=page)
    )
    harness.rpc.will_reply(
        "fulfillment.stock.replenish", asyncapi.StockReplenishReplyPayload(items=[])
    )
    harness.rpc.will_reply(
        "billing.credit.list", asyncapi.CreditListReplyPayload(items=[], page=page)
    )
    harness.rpc.will_reply(
        "billing.invoice.list",
        asyncapi.InvoiceListReplyPayload(
            items=[
                asyncapi.InvoiceView(
                    invoice_id=UUID(int=7),
                    invoice_reference="INV-000027",
                    invoice_date=datetime.now(UTC),
                    order_reference="ORD-000042",
                    retailer_code="R",
                    company_code="C",
                    currency="EUR",
                    amount=1,
                    discount=0,
                    total_amount=1,
                    status=asyncapi.InvoiceStatus.issued,
                )
            ],
            page=page,
        ),
    )
    harness.rpc.will_reply(
        "billing.payment.register",
        asyncapi.PaymentRegisterReplyPayload(
            outcome=asyncapi.Outcome3.accepted,
            payment_reference="P",
            invoice_reference="INV-000027",
            invoice_status=asyncapi.InvoiceStatus.paid,
        ),
    )
    harness.rpc.will_reply(
        "catalog.reference.list", asyncapi.CatalogReferenceListReplyPayload(products=[])
    )
    bearer = harness.bearer()
    full_order = {
        "retailerCode": "R",
        "companyCode": "C",
        "currency": "EUR",
        "lines": [{"productCode": "P", "quantity": 1, "unitPrice": 5, "lineDiscount": 1}],
        "orderDiscount": 1,
        "notes": "n",
    }
    requests = [
        ("POST", "/orders", full_order, {"Idempotency-Key": str(order_id)}),
        ("POST", f"/orders/{order_id}/cancel", {"note": "n"}, {}),
        (
            "GET",
            "/stock?companyCode=C&productCode=P&belowThreshold=true&page=1&pageSize=1",
            None,
            {},
        ),
        (
            "POST",
            "/stock/replenish",
            {"companyCode": "C", "lines": [{"productCode": "P", "units": 1}]},
            {},
        ),
        ("GET", "/credits?retailerCode=R&companyCode=C&page=1&pageSize=1", None, {}),
        (
            "GET",
            "/invoices?status=issued&retailerCode=R&companyCode=C&orderReference=ORD-000042"
            "&issuedBeforeMinutes=1&page=1&pageSize=1",
            None,
            {},
        ),
        (
            "POST",
            f"/invoices/{UUID(int=7)}/payments",
            {
                "paymentReference": "P",
                "amount": {"amount": 1, "currency": "EUR"},
                "valueDate": "2026-08-18T11:02:00.000Z",
                "source": "robot",
            },
            {},
        ),
        ("GET", "/catalog/products?includeDisabled=true", None, {}),
    ]
    for method, path, body, extra in requests:
        response = await harness.client.request(
            method, path, json=body, headers={**bearer, **extra}
        )
        assert response.status_code < 500 or path.endswith("/payments"), (path, response.text)

    seen = {c.subject: c for c in harness.rpc.calls if c.subject != "billing.invoice.list"}
    invoice_lists = [c for c in harness.rpc.calls if c.subject == "billing.invoice.list"]
    seen["billing.invoice.list"] = invoice_lists[0]  # the GET /invoices call, the first
    assert set(seen) == gateway_called_addresses()
    for subject, call in sorted(seen.items()):
        declared = declared_keys(request_schema(subject))
        unsent = NOT_SENT.get(subject, set())
        assert unsent <= declared, f"{subject}: {sorted(unsent - declared)} is not a declared key"
        expected = declared - unsent
        assert set(call.wire) == expected, (
            f"{subject}: sent {sorted(call.wire)}, declared {sorted(expected)}"
        )


def test_sentinel_a_property_renamed_in_the_contract_is_seen_by_the_keys_comparison() -> None:
    """#8's `G5_TheGuardFailsAgainstAScratchCopy...`: the comparison above can say no. A scratch
    copy of the contract with `invoiceId` renamed no longer matches what the Gateway sends."""
    import copy

    schema = copy.deepcopy(request_schema("billing.payment.register"))
    schema["properties"]["invoiceIdentifier"] = schema["properties"].pop("invoiceId")
    sent = {"invoiceId", "paymentReference", "amount", "valueDate", "source"}

    assert declared_keys(request_schema("billing.payment.register")) - {"invoiceReference"} == sent
    assert declared_keys(schema) - {"invoiceReference"} != sent
