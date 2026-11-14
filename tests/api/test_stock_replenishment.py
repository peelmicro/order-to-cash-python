# ruff: noqa: E501 - test names are the sentences the acceptance items use
"""Feature 31, acceptance item 7: R61's API half, `api/stock-replenishment.spec` of the test matrix.

A replenish through the real Gateway socket adds on-hand `units` and nothing else.

Why the open reservation is made over NATS and not by an order: through the Gateway an order's
reservation is CONSUMED by its despatch within ~100 ms (measured: the order is `invoiced` with
`reserved_units` back at 0), so no state reachable through the Gateway holds a reservation open.
The fixture therefore asks the real Fulfillment responder to reserve, on the subject and with the
headers the saga itself uses (`fulfillment.stock.reserve`), for an order reference Orders has never
heard of (Orders records the fact as ignored, `unknown_order`, and moves nothing). The replenish
itself, the claim under test, goes through the Gateway only. "Nothing else" is
every row of every table of all three write models, the three fact topics and the order itself,
read before and after, with one expected difference: the `units` (and `updated_at`) of the replenished
stock rows. The fixture holds a live reservation (an order that reached `invoiced`), so 'the
reservation is unchanged' compares a real row, and the replenished product is the reserved one.
"""

import json
import sys
import uuid
from typing import Any

import nats
import pytest

pytestmark = pytest.mark.integration
support: Any = sys.modules["api_support"]

COMPANY = "SPANATURAL"
RESERVED_PRODUCT = "PRD-0002"  # the order below reserves 3 units of it
UNTOUCHED_BY_ORDER = "PRD-0001"
ADDED = {RESERVED_PRODUCT: 25, UNTOUCHED_BY_ORDER: 7}
OPEN_RESERVATION_REFERENCE = "ORD-900001"
OPEN_RESERVATION_UNITS = 4


async def open_a_reservation(api: Any, nats_url: str) -> None:
    """Ask Fulfillment's real responder to reserve, then wait (bounded, paced) until Orders has
    taken the resulting fact (recorded as ignored) so the baseline below is quiescent."""
    client = await nats.connect(nats_url)
    try:
        reply = await client.request(
            "fulfillment.stock.reserve",
            json.dumps(
                {
                    "orderReference": OPEN_RESERVATION_REFERENCE,
                    "retailerCode": "AldiEs",
                    "companyCode": COMPANY,
                    "lines": [{"productCode": RESERVED_PRODUCT, "units": OPEN_RESERVATION_UNITS}],
                }
            ).encode(),
            timeout=15,
            headers={"x-correlation-id": str(uuid.uuid4()), "x-request-id": str(uuid.uuid4())},
        )
    finally:
        await client.close()
    assert json.loads(reply.data)["outcome"] == "accepted", reply.data

    async def ignored() -> bool:
        rows = await api.fleet.rows(
            "orders", "SELECT 1 FROM saga_ignored_facts WHERE marker = 'unknown_order'"
        )
        return bool(rows)

    await support.poll(ignored, "Orders took the reservation fact and ignored it")


async def stock_page(api: Any, product: str) -> dict[str, Any]:
    response = await api.call(
        "GET", "/stock", f"/stock?companyCode={COMPANY}&productCode={product}"
    )
    assert response.status_code == 200, response.text
    [item] = response.json()["items"]
    found: dict[str, Any] = item
    return found


async def test_r61_a_replenish_through_the_gateway_raises_units_and_changes_no_reservation_no_order_and_publishes_no_fact(
    api: Any, nats_server: Any
) -> None:
    placed = await api.place(unit_price=1500, quantity=3)
    invoiced = await api.wait_order(placed["orderId"], "invoiced")
    await open_a_reservation(api, nats_server.url)
    before = await api.quiesce()
    facts_before = await api.all_fact_counts()
    reserved_before = await stock_page(api, RESERVED_PRODUCT)
    other_before = await stock_page(api, UNTOUCHED_BY_ORDER)

    # controls: a reservation really exists and the stock row really carries it
    [open_one] = support.rows_where(
        before["fulfillment"], "reservations", order_reference=OPEN_RESERVATION_REFERENCE
    )
    assert (open_one["status"], open_one["units"], open_one["product_code"]) == (
        "reserved",
        OPEN_RESERVATION_UNITS,
        RESERVED_PRODUCT,
    )
    [consumed] = support.rows_where(
        before["fulfillment"], "reservations", order_reference=placed["orderReference"]
    )
    assert consumed["status"] == "consumed", "the order's own reservation: its despatch consumed it"
    assert reserved_before["reservedUnits"] == OPEN_RESERVATION_UNITS, (
        "reservedUnits is non-zero, so 'unchanged' is not 0 == 0"
    )
    assert reserved_before["units"] not in ADDED.values(), (
        "a delta cannot equal the level by accident"
    )
    assert ADDED[RESERVED_PRODUCT] != ADDED[UNTOUCHED_BY_ORDER], "distinct deltas per product"

    response = await api.call(
        "POST",
        "/stock/replenish",
        json={
            "companyCode": COMPANY,
            "lines": [{"productCode": p, "units": n} for p, n in ADDED.items()],
        },
    )

    assert response.status_code == 200, response.text
    answered = {i["productCode"]: i for i in response.json()["items"]}
    for product, before_item in (
        (RESERVED_PRODUCT, reserved_before),
        (UNTOUCHED_BY_ORDER, other_before),
    ):
        item = answered[product]
        assert item["units"] == before_item["units"] + ADDED[product], (
            f"{product}: units up by exactly the delta"
        )
        assert item["reservedUnits"] == before_item["reservedUnits"], (
            f"{product}: reservedUnits untouched"
        )
        assert item["availableUnits"] == item["units"] - item["reservedUnits"]
    # and GET /stock now says the same (the write is durable, not an echo)
    assert (await stock_page(api, RESERVED_PRODUCT))["units"] == reserved_before["units"] + ADDED[
        RESERVED_PRODUCT
    ]

    after = await api.quiesce()
    # 1. every table of the three databases is identical, except Fulfillment's `stock`
    for service in support.SERVICES:
        for name in after[service]:
            if (service, name) == ("fulfillment", "stock"):
                continue
            assert after[service][name] == before[service][name], f"R61: {service}.{name} changed"
    # 2. in `stock`: exactly the two replenished rows differ, and only in units and updated_at
    old = {r["id"]: r for r in before["fulfillment"]["stock"]}
    new = {r["id"]: r for r in after["fulfillment"]["stock"]}
    assert old.keys() == new.keys(), "R61: a stock row appeared or vanished"
    changed = {i for i in old if old[i] != new[i]}
    assert {new[i]["product_code"] for i in changed} == set(ADDED)
    for stock_id in changed:
        row_before, row_after = old[stock_id], new[stock_id]
        differing = {k for k in row_before if row_before[k] != row_after[k]}
        assert differing == {"units", "updated_at"}, (
            f"R61: {row_after['product_code']} changed {differing}"
        )
        assert row_after["units"] == row_before["units"] + ADDED[row_after["product_code"]]
        assert row_after["reserved_units"] == row_before["reserved_units"]
    # 3. no fact on any topic (all outboxes were published by the quiesce above)
    assert await api.all_fact_counts() == facts_before, "R61: a fact was published"
    # 4. and no order moved, as the API itself reports it
    detail = await api.call("GET", "/orders/{id}", f"/orders/{placed['orderId']}")
    assert detail.json()["status"] == "invoiced"
    assert detail.json()["events"] == invoiced["events"]
    listed = await api.call("GET", "/orders", f"/orders?orderReference={placed['orderReference']}")
    assert [o["status"] for o in listed.json()["items"]] == ["invoiced"]
    assert uuid.UUID(placed["orderId"])
