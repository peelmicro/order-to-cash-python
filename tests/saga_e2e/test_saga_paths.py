# ruff: noqa: E501 - test names are the sentences the acceptance items use
"""Feature 28, acceptance items 1 and 2, through the composed fleet (`conftest.py`): an order is
placed at the Gateway and everything after it is the services' own work over real Kafka and NATS.

* item 1 (R1 / R9 saga completes): the happy path reaches `completed`, in Orders' write model AND
  in the read model the Gateway serves, and the brokers hold exactly the nine facts of the path;
* item 2 (R42 / R43 compensation): an order whose total ends in `.99` is refused by Billing's
  simulator and compensates visibly - asserted as THREE facts of THREE services (Billing's refusal
  and its reason, Fulfillment's real release of the reservation, Orders' cancellation), never the
  order's terminal status alone.
"""

import json
import uuid
from typing import Any

import pytest

pytestmark = pytest.mark.integration

HAPPY_FACTS = [
    ("orders", "order.placed.v1"),
    ("fulfillment", "stock.reserved.v1"),
    ("billing", "credit.approved.v1"),
    ("orders", "order.confirmed.v1"),
    ("fulfillment", "order.despatched.v1"),
    ("billing", "invoice.issued.v1"),
    ("billing", "payment.received.v1"),
    ("billing", "credit.released.v1"),
    ("orders", "order.completed.v1"),
]
COMPENSATION_FACTS = [
    ("orders", "order.placed.v1"),
    ("fulfillment", "stock.reserved.v1"),
    ("billing", "credit.rejected.v1"),
    ("fulfillment", "stock.released.v1"),
    ("orders", "order.cancelled.v1"),
]
PASTA = 1849  # PRD-0002's seeded unit price, minor units


async def test_item1_a_placed_order_reaches_completed_after_a_payment_and_the_brokers_hold_exactly_the_nine_facts(
    fleet: Any,
) -> None:
    placed = await fleet.place([{"productCode": "PRD-0002", "quantity": 3, "lineDiscount": 125}])
    assert placed.status_code == 201, placed.text
    order_id, reference = placed.json()["orderId"], placed.json()["orderReference"]
    assert placed.json()["totalAmount"] == 3 * PASTA - 125

    await fleet.wait_status(order_id, "invoiced")  # the saga ran with nobody driving it
    paid = await fleet.pay(reference, "E2E-HAPPY-0001")
    assert paid.status_code == 201, paid.text
    await fleet.wait_status(order_id, "completed")

    await fleet.facts_reach(order_id, HAPPY_FACTS)

    async def projected() -> dict[str, object] | None:
        found = await fleet.http.get(f"/orders/{order_id}")
        body: dict[str, object] = found.json()
        return body if found.status_code == 200 and body["status"] == "completed" else None

    detail = await fleet.eventually(projected, "the read model shows the order completed")
    events = detail["events"]
    assert isinstance(events, list)
    assert sorted(str(e["eventType"]) for e in events) == sorted(t for _, t in HAPPY_FACTS)
    [stock] = await fleet.rows(
        "fulfillment",
        "SELECT status FROM reservations WHERE order_reference = $1",
        reference,
    )
    assert stock["status"] == "consumed"  # the despatch consumed the reservation


async def test_item2_a_dot_99_order_compensates_visibly_in_billing_fulfillment_and_orders(
    fleet: Any,
) -> None:
    placed = await fleet.place(
        [{"productCode": "PRD-0002", "quantity": 1, "lineDiscount": PASTA - 99}]
    )
    assert placed.status_code == 201, placed.text
    order_id, reference = placed.json()["orderId"], placed.json()["orderReference"]
    assert placed.json()["totalAmount"] == 99, "the fixture must total .99 (R42)"

    await fleet.wait_status(order_id, "cancelled")
    await fleet.facts_reach(order_id, COMPENSATION_FACTS)

    # (a) Billing: the refusal fact carries the SIMULATOR's reason, not the domain's closed set
    [rejected] = [
        json.loads(r.value) for r in await fleet.records("otc.billing.facts.v1", order_id)
    ]
    assert rejected["eventType"] == "credit.rejected.v1"
    assert rejected["payload"]["reason"] == "simulated_cents_rule"
    assert rejected["payload"]["requestedAmount"] == 99
    # (b) Fulfillment: the reservation it made was really given back (a row, not an inference)
    [reservation] = await fleet.rows(
        "fulfillment",
        "SELECT status, units FROM reservations WHERE order_reference = $1",
        reference,
    )
    assert (reservation["status"], reservation["units"]) == ("released", 1)
    # (c) Orders: the cancellation names the domain's reason, and the order is terminal
    [row] = await fleet.rows(
        "orders",
        "SELECT status, cancellation_reason FROM orders WHERE id = $1",
        uuid.UUID(order_id),
    )
    assert (row["status"], row["cancellation_reason"]) == ("cancelled", "credit_rejected")
    # and nothing downstream of a credit approval ever happened
    assert (
        await fleet.rows("billing", "SELECT 1 FROM invoices WHERE order_reference = $1", reference)
        == []
    )
    assert (
        await fleet.rows(
            "fulfillment", "SELECT 1 FROM despatches WHERE order_reference = $1", reference
        )
        == []
    )
