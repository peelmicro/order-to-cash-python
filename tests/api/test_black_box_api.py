# ruff: noqa: E501 - test names are the sentences the acceptance items use
"""Feature 31, acceptance items 1, 2, 3, 4 and 5: `api/black-box-api.spec`, `api/payment-idempotency.spec`
and `api/payment-rejection.spec` of the test matrix, against the composed fleet (`conftest.py`).

The ONLY client of the system under test is `httpx` over a real socket to the Gateway (`api`). The
databases and the topics are read as evidence, never used to drive. The port of #7's assertions is
inventoried row by row in `progress/impl_api_tests.md` section 2; each test names its scenario.
"""

import sys
import uuid
from typing import Any

import httpx
import pytest

pytestmark = pytest.mark.integration
support: Any = sys.modules["api_support"]

HAPPY_TYPES = sorted(
    [
        "order.placed.v1",
        "stock.reserved.v1",
        "credit.approved.v1",
        "order.confirmed.v1",
        "order.despatched.v1",
        "invoice.issued.v1",
        "payment.received.v1",
        "credit.released.v1",
        "order.completed.v1",
    ]
)
COMPENSATION_TYPES = sorted(
    [
        "order.placed.v1",
        "stock.reserved.v1",
        "credit.rejected.v1",
        "stock.released.v1",
        "order.cancelled.v1",
    ]
)


# What "Billing's own database" is made of: the invoice (invoices, invoice_items), the payments, the
# credit ledger (credits, credit_items), the outbox (the facts), processed_events (idempotency of the
# consumers), the invoice number counter and the migration marker. A table added later fails here.
BILLING_TABLES = frozenset(
    {
        "alembic_version",
        "credit_items",
        "credits",
        "invoice_items",
        "invoice_number_sequences",
        "invoices",
        "outbox",
        "payments",
        "processed_events",
    }
)


def reference(prefix: str) -> str:
    """A payment reference unique to this call (the column holds 30 characters)."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


async def settled_timeline(
    api: Any, order_id: str, status: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The order's detail once it shows `status` AND as many timeline entries as the services
    published facts for it (the read model is eventually consistent), with those facts."""
    detail = await api.wait_order(order_id, status)

    async def complete() -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
        facts = await api.facts(order_id)
        current = await api.wait_order(order_id, status)
        return (current, facts) if len(current["events"]) == len(facts) else None

    assert detail["status"] == status
    settled: tuple[dict[str, Any], list[dict[str, Any]]] = await support.poll(
        complete, f"the timeline of {order_id} holds one entry per published fact"
    )
    return settled


def type_pairs(edges: list[tuple[int, int]], types: list[str]) -> list[tuple[str, str]]:
    return sorted((types[cause], types[effect]) for cause, effect in edges)


def fact_type_pairs(facts: list[dict[str, Any]]) -> list[tuple[str, str]]:
    by_id = {f["eventId"]: f["eventType"] for f in facts}
    return sorted(
        (by_id[f["causationId"]], f["eventType"]) for f in facts if f["causationId"] in by_id
    )


async def assert_timeline_is_causally_ordered(
    events: list[dict[str, Any]], facts: list[dict[str, Any]], *, floor: int
) -> None:
    """R24 + #8 id 105. The edges the timeline must resolve are the ones the SERVICES published
    (`causationId` naming another fact's `eventId`, read from the topics), not a number written
    next to the assertion: the timeline must resolve exactly those type pairs, and `floor` (the
    count measured on a real run, 3 for the happy path) keeps the derivation itself from going
    vacuous."""
    expected = fact_type_pairs(facts)
    assert len(expected) >= floor, (
        f"the brokers' facts carry only {len(expected)} causal edge(s): {expected}"
    )
    types = [str(e["eventType"]) for e in events]
    actual = type_pairs(support.timeline_edges(events), types)
    assert actual == expected, (
        f"the timeline resolves {actual}, the published facts carry {expected}"
    )
    support.assert_causal_order(events, required_edges=len(expected))


# --------------------------------------------------------------------- scenario 1: happy path


async def test_scenario_1_a_placed_order_completes_after_a_payment_and_its_timeline_is_in_causal_order(
    api: Any,
) -> None:
    """Acceptance item 1 (happy path), item 4 (R24 API half, #8 id 105). #7 scenario 1."""
    placed = await api.place(unit_price=1500, quantity=2)  # 2 x 1500 = 3000, not a .99 total
    assert placed["totalAmount"] == 3000
    assert placed["projectionPending"] is True
    assert placed["status"] == "placed"

    invoiced = await api.wait_order(placed["orderId"], "invoiced")
    assert invoiced["references"]["invoiceReference"]
    invoice = await api.invoice_of(placed["orderReference"])
    assert invoice["totalAmount"] == 3000
    assert invoice["invoiceReference"] == invoiced["references"]["invoiceReference"]

    paid = await api.pay(invoice, reference("PAY-HAPPY"))
    assert paid.status_code == 201, paid.text
    assert paid.json()["outcome"] == "accepted"

    completed, facts = await settled_timeline(api, placed["orderId"], "completed")
    assert completed["status"] == "completed"
    events = completed["events"]
    types = [e["eventType"] for e in events]
    for triple in ("payment.received.v1", "credit.released.v1", "order.completed.v1"):
        assert triple in types, f"R24: {triple} missing from the timeline {types}"
    assert sorted(types) == HAPPY_TYPES
    assert sorted(f["eventType"] for f in facts) == HAPPY_TYPES, (
        "the brokers hold exactly the nine facts"
    )
    await assert_timeline_is_causally_ordered(events, facts, floor=3)


# ---------------------------------------------------------------- scenario 2: compensation


async def test_scenario_2_a_dot_99_order_is_cancelled_with_the_compensation_chain_in_causal_order_and_the_reservation_released(
    api: Any,
) -> None:
    """Acceptance item 2 (compensation path), R28/R42. #7 scenario 2."""
    placed = await api.place(unit_price=1099, quantity=1)
    assert placed["totalAmount"] % 100 == 99, "the fixture must total .99 (R42)"

    cancelled, facts = await settled_timeline(api, placed["orderId"], "cancelled")
    assert cancelled["cancellationReason"] == "credit_rejected"
    events = cancelled["events"]
    types = [e["eventType"] for e in events]
    assert sorted(types) == COMPENSATION_TYPES, "three distinct compensation entries, never merged"
    rejected, released, cancel = (
        types.index("credit.rejected.v1"),
        types.index("stock.released.v1"),
        types.index("order.cancelled.v1"),
    )
    assert rejected < released, f"credit.rejected.v1 must precede stock.released.v1: {types}"
    assert rejected < cancel, f"credit.rejected.v1 must precede order.cancelled.v1: {types}"
    assert released < cancel, f"R28: stock.released.v1 must precede order.cancelled.v1: {types}"
    # documentation of the tie (#7 review section 5): the cancellation reuses the release's own
    # instant, so the ARRAY ORDER above - never this equality - is the proof of causal order
    assert events[released]["occurredAt"] == events[cancel]["occurredAt"]
    await assert_timeline_is_causally_ordered(events, facts, floor=1)

    [reservation] = await api.fleet.rows(
        "fulfillment",
        "SELECT status FROM reservations WHERE order_reference = $1",
        placed["orderReference"],
    )
    assert reservation["status"] == "released"  # a row in Fulfillment's own database


# ------------------------------------------------------------- scenario 3: R48 idempotency


async def test_scenario_3_r48_the_same_payment_reference_twice_records_one_payment_and_one_fact(
    api: Any,
) -> None:
    """Acceptance item 1 of R48: 201 accepted then 200 duplicate (original outcome, replay header),
    exactly ONE `payments` row and ONE `payment.received.v1` fact for that invoice, counted in the
    table, in the outbox AND on the topic. A control order paid once under its own reference makes
    the table hold TWO new rows, so a count of one for the invoice cannot be 'the table has one row'."""
    control = await api.place(unit_price=2000, quantity=1)  # 2000, distinct from the order below
    control_invoice = await await_invoice(api, control, "invoiced")
    control_reference = reference("PAY-CONTROL")
    assert (await api.pay(control_invoice, control_reference)).status_code == 201

    placed = await api.place(unit_price=2499, quantity=3)  # 7497, not a .99 total
    invoice = await await_invoice(api, placed, "invoiced")
    payment_reference = reference("PAY-IDEMP")

    first = await api.pay(invoice, payment_reference)
    second = await api.pay(invoice, payment_reference)

    # the state first (the claim of R48), then the replies that describe it
    await api.wait_order(placed["orderId"], "completed")
    after = (await api.quiesce())["billing"]  # every outbox row published: the topic is complete
    mine = support.rows_where(after, "payments", invoice_id=uuid.UUID(invoice["invoiceId"]))
    assert [p["payment_reference"] for p in mine] == [payment_reference], "exactly one payment row"
    in_outbox = [
        r
        for r in after["outbox"]
        if r["event_type"] == "payment.received.v1"
        and support.parse_json(r["payload"])["invoiceReference"] == invoice["invoiceReference"]
    ]
    assert len(in_outbox) == 1, (
        "exactly one payment.received.v1 in Billing's outbox for the invoice"
    )
    outbox_payload = support.parse_json(in_outbox[0]["payload"])
    assert outbox_payload["paymentReference"] == payment_reference, (
        f"Billing's outbox row is not this payment's: {outbox_payload}"
    )
    assert outbox_payload["invoiceReference"] == invoice["invoiceReference"], outbox_payload
    assert outbox_payload["invoiceReference"] != control_invoice["invoiceReference"], outbox_payload
    on_topic = [
        f for f in await api.facts(placed["orderId"]) if f["eventType"] == "payment.received.v1"
    ]
    assert len(on_topic) == 1, f"exactly one payment.received.v1 on the topic: {on_topic}"
    assert on_topic[0]["payload"]["invoiceReference"] == invoice["invoiceReference"]
    assert on_topic[0]["payload"]["paymentReference"] == payment_reference
    seeded = [p for p in after["payments"] if p["payment_reference"].startswith("PAY-SEED-")]
    assert seeded, "control: the seed's own payments are in the table"
    assert len(after["payments"]) == len(seeded) + 2, (
        "control: the table holds the control's payment too"
    )

    assert first.status_code == 201, first.text
    assert first.json()["outcome"] == "accepted"
    assert second.status_code == 200, second.text
    assert second.json()["outcome"] == "duplicate"
    assert second.headers["idempotent-replay"] == "true"
    assert "idempotent-replay" not in first.headers
    assert second.json()["paymentReference"] == payment_reference
    assert second.json()["invoiceReference"] == first.json()["invoiceReference"]
    assert second.json()["orderReference"] == first.json()["orderReference"]


async def await_invoice(api: Any, placed: dict[str, Any], status: str) -> dict[str, Any]:
    await api.wait_order(placed["orderId"], status)
    invoice: dict[str, Any] = await api.invoice_of(placed["orderReference"])
    return invoice


# ------------------------------------------------------------------ R49: refusals, no change


async def refusal_world(
    api: Any, unit_price: int, *, paid: bool
) -> tuple[dict[str, Any], dict[str, Any]]:
    """An order with an invoice (and, when `paid`, a completed saga behind it), then the quiescent
    baseline of Billing's database and of the topics every R49 arm is compared with."""
    placed = await api.place(unit_price=unit_price, quantity=1)
    invoice = await await_invoice(api, placed, "invoiced")
    if paid:
        assert (await api.pay(invoice, reference("PAY-FIRST"))).status_code == 201
        await api.wait_order(placed["orderId"], "completed")
    baseline = await api.quiesce()
    return invoice, {
        "dumps": baseline,
        "facts": await api.all_fact_counts(),
        "order_id": placed["orderId"],
    }


async def assert_refused_and_nothing_changed(
    api: Any,
    response: httpx.Response,
    baseline: dict[str, Any],
    *,
    status: int,
    code: str,
) -> None:
    """EVERY row of EVERY table of Billing's database (the nine in `BILLING_TABLES`), read again once
    the three write models are quiescent, equals the baseline; so does the fact count of all
    three topics. Only then the refusal itself: status, problem media type, machine-readable code."""
    assert set(baseline["dumps"]["billing"]) == BILLING_TABLES, "a table the claim does not cover"
    after = await api.quiesce()
    assert support.diff_tables(baseline["dumps"]["billing"], after["billing"]) == [], (
        "R49: Billing's database changed"
    )
    assert await api.all_fact_counts() == baseline["facts"], "R49: a fact was published"
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    problem = response.json()
    assert problem["code"] == code, problem
    assert problem["status"] == status
    assert problem["correlationId"]


async def test_r49_a_mismatched_amount_is_refused_422_payment_mismatch_and_billings_database_is_unchanged(
    api: Any,
) -> None:
    invoice, baseline = await refusal_world(api, 1200, paid=False)
    billing = baseline["dumps"]["billing"]
    assert [
        r["status"] for r in billing["invoices"] if r["id"] == uuid.UUID(invoice["invoiceId"])
    ] == ["issued"]
    mine = uuid.UUID(invoice["invoiceId"])
    assert support.rows_where(billing, "payments", invoice_id=mine) == [], "control: no payment yet"
    assert len(billing["credit_items"]) >= 1, "control: the ledger holds the order's hold"

    for wrong in (invoice["totalAmount"] + 1, invoice["totalAmount"] - 1):
        response = await api.pay(invoice, reference("PAY-BADAMT"), amount=wrong)
        await assert_refused_and_nothing_changed(
            api, response, baseline, status=422, code="PAYMENT_MISMATCH"
        )


async def test_r49_a_mismatched_currency_is_refused_422_payment_mismatch_and_billings_database_is_unchanged(
    api: Any,
) -> None:
    invoice, baseline = await refusal_world(api, 1300, paid=False)
    assert invoice["currency"] == "EUR", "the mismatch below must be a genuine one"

    response = await api.pay(invoice, reference("PAY-BADCCY"), currency="USD")

    await assert_refused_and_nothing_changed(
        api, response, baseline, status=422, code="PAYMENT_MISMATCH"
    )
    mine = uuid.UUID(invoice["invoiceId"])
    assert support.rows_where(baseline["dumps"]["billing"], "payments", invoice_id=mine) == []


async def test_r49_a_different_reference_against_a_paid_invoice_is_refused_409_invoice_already_paid_and_billings_database_is_unchanged(
    api: Any,
) -> None:
    invoice, baseline = await refusal_world(api, 1400, paid=True)
    first = support.rows_where(
        baseline["dumps"]["billing"], "payments", invoice_id=uuid.UUID(invoice["invoiceId"])
    )
    assert len(first) == 1, "control: the first payment is there"

    response = await api.pay(invoice, reference("PAY-SECOND"))

    await assert_refused_and_nothing_changed(
        api, response, baseline, status=409, code="INVOICE_ALREADY_PAID"
    )


# ------------------------------------------------------------ scenario 4: auth and error shapes


async def test_scenario_4_no_token_is_401_a_malformed_order_id_is_400_and_an_unknown_one_is_404(
    api: Any,
) -> None:
    """#7 scenario 4, through the real socket: an unauthenticated client of the same server."""
    async with httpx.AsyncClient(base_url=str(api.http.base_url)) as anonymous:
        no_token = await anonymous.get("/orders")
    assert no_token.status_code == 401
    assert no_token.json()["code"] == "UNAUTHORIZED"

    malformed = await api.call("GET", "/orders/{id}", "/orders/not-a-uuid")
    assert malformed.status_code == 400
    assert malformed.json()["code"] == "VALIDATION_FAILED"

    unknown = await api.call("GET", "/orders/{id}", f"/orders/{uuid.uuid4()}")
    assert unknown.status_code == 404
    assert unknown.json()["code"] == "NOT_FOUND"
