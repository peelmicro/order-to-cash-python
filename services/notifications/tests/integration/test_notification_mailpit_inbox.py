"""Acceptance 1: a REAL email in the Mailpit inbox, through its HTTP API, for each of the seven
notified facts, driven end to end: the fact's bytes on the real Kafka topic of its producing
context, the REAL host (`otc_notifications.main` lifespan, SMTP adapter, durable ledger), a REAL
Mailpit. Everything asserted is read back from the inbox API and the ledger table, never from a
call's return value.

Loop scope: function (the host, the engine, the Kafka producer and the HTTP client all live and die
in the test's loop). Each test has its own unique consumer group and a fresh migrated database.
"""

from typing import Any

import pytest

from otc_contracts import format_instant

DOMAIN = "retailer.order-to-cash.example"

# eventType -> (recipient local part, subject summary, exact text lines in order)
EXPECTED = {
    "order.placed.v1": (
        "acme",
        "Order ORD-000101 placed",
        [
            "Order ORD-000101 has been placed.",
            "Retailer: ACME",
            "Company: GLOBEX",
            "Total: 1 242.50 EUR",
            "Order date: 2026-03-04T05:14:25.123Z",
        ],
    ),
    "order.confirmed.v1": (
        "bigmart",
        "Order ORD-000102 confirmed",
        [
            "Order ORD-000102 has been confirmed — stock reserved and credit approved.",
            "Retailer: BIGMART",
            "Company: INITECH",
            "Total: 5 000 JPY",
            "Confirmed at: 2026-03-05T06:15:26.234Z",
        ],
    ),
    "order.despatched.v1": (
        "megaco",
        "Order ORD-000103 despatched (DES-000203)",
        [
            "Order ORD-000103 has been despatched.",
            "Despatch reference: DES-000203",
            "Despatch date: 2026-03-06T07:16:27.345Z",
            "Retailer: MEGACO",
            "Company: UMBRELLA",
            "Lines: GADGET-A1 x2, GADGET-A2 x5",
        ],
    ),
    "invoice.issued.v1": (
        "cornershop",
        "Invoice INV-000304 issued",
        [
            "Invoice INV-000304 has been issued for order ORD-000104.",
            "Retailer: CORNERSHOP",
            "Company: HOOLI",
            "Total: 116.667 KWD",
            "Invoice date: 2026-03-07T08:17:28.456Z",
        ],
    ),
    "payment.received.v1": (
        "ord-000105",
        "Payment received for invoice INV-000305",
        [
            "Payment PAY-A-5001 has been received for invoice INV-000305 (order ORD-000105).",
            "Amount: 1 166.67 EUR",
            "Value date: 2026-03-08T09:18:29.567Z",
            "Source: operator",
        ],
    ),
    "order.completed.v1": (
        "shoprite",
        "Order ORD-000106 completed",
        [
            "Order ORD-000106 is complete — despatched, invoiced and paid.",
            "Retailer: SHOPRITE",
            "Company: WAYNE",
            "Total: 9 876.50 USD",
            "Completed at: 2026-03-09T10:19:30.678Z",
        ],
    ),
    "order.cancelled.v1": (
        "foodco",
        "Order ORD-000107 cancelled",
        [
            "Order ORD-000107 has been cancelled.",
            "Reason: credit_rejected",
            "Retailer: FOODCO",
            "Company: STARK",
            "Cancelled at: 2026-03-10T11:20:31.789Z",
            "Compensation steps: stock_released, credit_released",
        ],
    ),
}


@pytest.mark.parametrize("event_type", sorted(EXPECTED))
async def test_a_real_email_for_the_notified_fact_lands_in_the_mailpit_inbox(
    notifications_host_factory: Any,
    publisher: Any,
    inbox: Any,
    facts: Any,
    topic_of: Any,
    ledger_rows: Any,
    event_type: str,
) -> None:
    local_part, summary, lines = EXPECTED[event_type]
    event = facts.event(event_type)
    assert await inbox.count() == 0, "the inbox starts empty (baseline)"

    async with notifications_host_factory() as host:
        assert host.runtime.subscriber.ready
        await publisher.publish(topic_of[event_type], event.correlation_id, facts.wire(event_type))
        [summary_row] = await inbox.wait_for_count(1)

    sent = await inbox.message(summary_row["ID"])
    assert [a["Address"] for a in sent["To"]] == [f"{local_part}@{DOMAIN}"]
    assert sent["From"]["Address"] == "no-reply@order-to-cash.example"
    assert sent["Subject"] == f"[order-to-cash] {summary} (correlationId: {event.correlation_id})"
    assert sent["MessageID"] == f"{event.event_id}@order-to-cash"
    text = sent["Text"].replace("\r\n", "\n").strip()  # SMTP carries CRLF
    assert text == "\n".join([*lines, f"Correlation id: {event.correlation_id}"])
    assert "Correlation id: " + str(event.correlation_id) + "\n" not in sent["HTML"] + "\n"
    assert f"<p>Correlation id: {event.correlation_id}</p>" in sent["HTML"]
    assert format_instant(event.occurred_at) not in sent["Text"]
    assert await ledger_rows() == [(event.event_id, "notifications")]
