"""Feature 28, acceptance item 4 - R56's composed-stack half, R57.

ONE trace identifier spans every request, command, transaction and fact of one order across the
real services. The caller chooses it: the inbound Gateway requests (placing the order, then
registering its payment) carry an explicit `traceparent` of a trace id this test makes up. The
population, written as LITERALS (never derived from the property under test):

* the nine facts of the happy path, each as an outbox row of its producing service
  (`outbox.trace_parent` of Orders, Fulfillment and Billing) AND as a record on its fact topic
  (the Kafka `traceparent` header), and
* the saga command rows Orders owes this order (`saga_commands.trace_parent`).

Every one of the 9 + 9 + 4 observations must carry the chosen trace id, and the observed set of
(source, kind) pairs must EQUAL the literal one. The fast path's hand-off (design.md L7, 11) is
inside this population: a `saga_commands` row or a downstream fact in another trace fails here
with the two ids side by side.
"""

import json
import uuid
from typing import Any

import pytest

pytestmark = pytest.mark.integration

TRACE_ID = "0af7651916cd43dd8448eb211c80319c"
CALLER_SPAN = "b7ad6b7169203331"
TRACEPARENT = f"00-{TRACE_ID}-{CALLER_SPAN}-01"

FACTS = [
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
COMMANDS = ["stock.reserve", "credit.hold", "despatch.create", "invoice.issue"]
TOPICS = {
    "orders": "otc.orders.facts.v1",
    "fulfillment": "otc.fulfillment.facts.v1",
    "billing": "otc.billing.facts.v1",
}


def trace_of(traceparent: str | bytes | None) -> str:
    """The trace id of a W3C `traceparent` ('<none>' when absent, so a missing context fails as a
    differing id rather than as a KeyError)."""
    if traceparent is None:
        return "<none>"
    text = traceparent.decode("ascii") if isinstance(traceparent, bytes) else traceparent
    return text.split("-")[1]


async def test_item4_r56_every_request_command_row_and_fact_of_one_order_carries_the_one_trace_id(
    fleet: Any,
) -> None:
    placed = await fleet.place(
        [{"productCode": "PRD-0002", "quantity": 3, "lineDiscount": 125}], traceparent=TRACEPARENT
    )
    assert placed.status_code == 201, placed.text
    order_id, reference = placed.json()["orderId"], placed.json()["orderReference"]
    await fleet.wait_status(order_id, "invoiced")
    paid = await fleet.pay(reference, "E2E-TRACE-0001", traceparent=TRACEPARENT)
    assert paid.status_code == 201, paid.text
    await fleet.wait_status(order_id, "completed")
    await fleet.facts_reach(order_id, FACTS)

    uid = uuid.UUID(order_id)
    observed: dict[tuple[str, str, str], str] = {}  # (kind, source, name) -> trace id
    for source in ("orders", "fulfillment", "billing"):
        for row in await fleet.rows(
            source, "SELECT event_type, trace_parent FROM outbox WHERE correlation_id = $1", uid
        ):
            observed[("outbox row", source, row["event_type"])] = trace_of(row["trace_parent"])
        for record in await fleet.records(TOPICS[source], order_id):
            name = json.loads(record.value)["eventType"]
            observed[("kafka header", source, name)] = trace_of(record.headers.get("traceparent"))
    for row in await fleet.rows(
        "orders", "SELECT command, trace_parent FROM saga_commands WHERE order_id = $1", uid
    ):
        observed[("saga command row", "orders", row["command"])] = trace_of(row["trace_parent"])

    expected = (
        {("outbox row", source, name) for source, name in FACTS}
        | {("kafka header", source, name) for source, name in FACTS}
        | {("saga command row", "orders", name) for name in COMMANDS}
    )
    assert set(observed) == expected, "the population observed is exactly the literal one"
    assert len(expected) == 9 + 9 + 4
    differing = {key: trace for key, trace in observed.items() if trace != TRACE_ID}
    assert differing == {}, (
        f"expected every observation in trace {TRACE_ID}, differing: {differing}"
    )
