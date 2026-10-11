# ruff: noqa: E501 - the expected emails are written out line by line, as the templates emit them
"""Every template's recipient, subject and body, field by field (acceptance 4; #8 ids 58, 59).

The expected text is WRITTEN OUT here from the fixture's values (`tests/conftest.py`), never built by
calling anything in the template package, and every value of a fixture differs from every other
(`test_fact_fixtures_do_not_collide.py`), so a template that renders the wrong field, a sibling
field, an envelope id, the raw minor-unit integer or the wire timestamp fails by the value it
rendered. Each template has: its recipient, its subject, its exact text body, its exact HTML body,
and a test that none of the plausible wrong values (listed per template) appears anywhere.

Plausible wrong values, per assertion class (the expected value differs from every one):
* a recipient or code: the same payload's OTHER code (`retailerCode` vs `companyCode`), the order
  reference, the buyer GLN;
* the correlation id: `eventId`, `aggregateId`, `causationId` of the envelope (all different);
* money: the raw integer (`124250`), another amount of the same payload (`initialAmount`), the
  amount formatted with another currency's exponent;
* an instant: the envelope's `occurredAt`, another instant of the same payload, `str(datetime)` and
  `isoformat()` (`+00:00`, microseconds), the right instant with the wrong millisecond.
"""

from datetime import datetime
from typing import Any

from otc_contracts import format_instant
from otc_notifications.application.ports.notification_sender import NotificationMessage
from otc_notifications.application.templates.invoice_issued import render_invoice_issued
from otc_notifications.application.templates.order_cancelled import render_order_cancelled
from otc_notifications.application.templates.order_completed import render_order_completed
from otc_notifications.application.templates.order_confirmed import render_order_confirmed
from otc_notifications.application.templates.order_despatched import render_order_despatched
from otc_notifications.application.templates.order_placed import render_order_placed
from otc_notifications.application.templates.payment_received import render_payment_received

DOMAIN = "retailer.order-to-cash.example"


def envelope_wrong_values(event: Any) -> list[str]:
    """Everything of the envelope a template must NOT put in the message."""
    return [
        str(event.event_id),
        str(event.aggregate_id),
        str(event.causation_id),
        format_instant(event.occurred_at),
    ]


def wrong_instant_forms(value: datetime) -> list[str]:
    return [str(value), value.isoformat(), value.isoformat().replace("+00:00", "Z")]


def assert_absent(message: NotificationMessage, values: list[str]) -> None:
    for value in values:
        assert value not in message.subject, f"subject carries {value!r}"
        assert value not in message.text_body, f"text carries {value!r}"
        assert value not in message.html_body, f"html carries {value!r}"


# ----------------------------------------------------------------------------- order.placed.v1


def test_order_placed_recipient_is_the_retailer_code_lowercased(facts: Any) -> None:
    message = render_order_placed(facts.event("order.placed.v1"))
    assert message.to == f"acme@{DOMAIN}", "not companyCode (globex), not the order reference"


def test_order_placed_subject_names_the_order_and_the_correlation_id(facts: Any) -> None:
    event = facts.event("order.placed.v1")
    assert render_order_placed(event).subject == (
        f"[order-to-cash] Order ORD-000101 placed (correlationId: {event.correlation_id})"
    )


def test_order_placed_text_body_is_exactly_the_documented_lines(facts: Any) -> None:
    event = facts.event("order.placed.v1")
    assert render_order_placed(event).text_body == "\n".join(
        [
            "Order ORD-000101 has been placed.",
            "Retailer: ACME",
            "Company: GLOBEX",
            "Total: 1 242.50 EUR",
            "Order date: 2026-03-04T05:14:25.123Z",
            f"Correlation id: {event.correlation_id}",
        ]
    )


def test_order_placed_html_body_is_exactly_the_documented_markup(facts: Any) -> None:
    event = facts.event("order.placed.v1")
    assert render_order_placed(event).html_body == "\n".join(
        [
            "<p>Order <strong>ORD-000101</strong> has been placed.</p>",
            "<ul>",
            "<li>Retailer: ACME</li>",
            "<li>Company: GLOBEX</li>",
            "<li>Total: 1 242.50 EUR</li>",
            "<li>Order date: 2026-03-04T05:14:25.123Z</li>",
            "</ul>",
            f"<p>Correlation id: {event.correlation_id}</p>",
        ]
    )


def test_order_placed_renders_none_of_the_plausible_wrong_values(facts: Any) -> None:
    event = facts.event("order.placed.v1")
    payload = event.payload
    assert_absent(
        render_order_placed(event),
        [
            *envelope_wrong_values(event),
            "124250",  # the raw minor-unit integer
            "130000",  # initialAmount: another amount of the same payload
            "5750",  # initialDiscount
            "1 300.00 EUR",
            "1 242.5 EUR",
            payload.buyer_gln,
            payload.supplier_gln,
            "WIDGET-A1",
            "alpha",
            *wrong_instant_forms(payload.order_date),
        ],
    )


# -------------------------------------------------------------------------- order.confirmed.v1


def test_order_confirmed_recipient_is_the_retailer_code_lowercased(facts: Any) -> None:
    message = render_order_confirmed(facts.event("order.confirmed.v1"))
    assert message.to == f"bigmart@{DOMAIN}", "not companyCode (initech)"


def test_order_confirmed_subject_names_the_order_and_the_correlation_id(facts: Any) -> None:
    event = facts.event("order.confirmed.v1")
    assert render_order_confirmed(event).subject == (
        f"[order-to-cash] Order ORD-000102 confirmed (correlationId: {event.correlation_id})"
    )


def test_order_confirmed_text_body_is_exactly_the_documented_lines(facts: Any) -> None:
    event = facts.event("order.confirmed.v1")
    assert render_order_confirmed(event).text_body == "\n".join(
        [
            "Order ORD-000102 has been confirmed — stock reserved and credit approved.",
            "Retailer: BIGMART",
            "Company: INITECH",
            "Total: 5 000 JPY",
            "Confirmed at: 2026-03-05T06:15:26.234Z",
            f"Correlation id: {event.correlation_id}",
        ]
    )


def test_order_confirmed_html_body_is_exactly_the_documented_markup(facts: Any) -> None:
    event = facts.event("order.confirmed.v1")
    assert render_order_confirmed(event).html_body == "\n".join(
        [
            "<p>Order <strong>ORD-000102</strong> has been confirmed — stock reserved and credit approved.</p>",
            "<ul>",
            "<li>Retailer: BIGMART</li>",
            "<li>Company: INITECH</li>",
            "<li>Total: 5 000 JPY</li>",
            "<li>Confirmed at: 2026-03-05T06:15:26.234Z</li>",
            "</ul>",
            f"<p>Correlation id: {event.correlation_id}</p>",
        ]
    )


def test_order_confirmed_renders_none_of_the_plausible_wrong_values(facts: Any) -> None:
    event = facts.event("order.confirmed.v1")
    assert_absent(
        render_order_confirmed(event),
        [
            *envelope_wrong_values(event),
            "5000 JPY",  # no grouping
            "50.00 JPY",  # the exponent of a two-decimal currency
            "5 000.00 JPY",
            *wrong_instant_forms(event.payload.confirmed_at),
        ],
    )


# ------------------------------------------------------------------------ order.despatched.v1


def test_order_despatched_recipient_is_the_retailer_code_lowercased(facts: Any) -> None:
    message = render_order_despatched(facts.event("order.despatched.v1"))
    assert message.to == f"megaco@{DOMAIN}", "not companyCode (umbrella)"


def test_order_despatched_subject_names_the_order_the_despatch_and_the_correlation_id(
    facts: Any,
) -> None:
    event = facts.event("order.despatched.v1")
    assert render_order_despatched(event).subject == (
        f"[order-to-cash] Order ORD-000103 despatched (DES-000203) (correlationId: {event.correlation_id})"
    )


def test_order_despatched_text_body_is_exactly_the_documented_lines(facts: Any) -> None:
    event = facts.event("order.despatched.v1")
    assert render_order_despatched(event).text_body == "\n".join(
        [
            "Order ORD-000103 has been despatched.",
            "Despatch reference: DES-000203",
            "Despatch date: 2026-03-06T07:16:27.345Z",
            "Retailer: MEGACO",
            "Company: UMBRELLA",
            "Lines: GADGET-A1 x2, GADGET-A2 x5",
            f"Correlation id: {event.correlation_id}",
        ]
    )


def test_order_despatched_html_body_is_exactly_the_documented_markup(facts: Any) -> None:
    event = facts.event("order.despatched.v1")
    assert render_order_despatched(event).html_body == "\n".join(
        [
            "<p>Order <strong>ORD-000103</strong> has been despatched.</p>",
            "<ul>",
            "<li>Despatch reference: DES-000203</li>",
            "<li>Despatch date: 2026-03-06T07:16:27.345Z</li>",
            "<li>Retailer: MEGACO</li>",
            "<li>Company: UMBRELLA</li>",
            "<li>Lines: GADGET-A1 x2, GADGET-A2 x5</li>",
            "</ul>",
            f"<p>Correlation id: {event.correlation_id}</p>",
        ]
    )


def test_order_despatched_renders_none_of_the_plausible_wrong_values(facts: Any) -> None:
    event = facts.event("order.despatched.v1")
    assert_absent(
        render_order_despatched(event),
        [
            *envelope_wrong_values(event),
            "GADGET-A1 x5",  # a line's code with another line's units
            "GADGET-A2 x2",
            *wrong_instant_forms(event.payload.despatch_date),
        ],
    )


# -------------------------------------------------------------------------- invoice.issued.v1


def test_invoice_issued_recipient_is_the_retailer_code_lowercased(facts: Any) -> None:
    message = render_invoice_issued(facts.event("invoice.issued.v1"))
    assert message.to == f"cornershop@{DOMAIN}", "not companyCode (hooli)"


def test_invoice_issued_subject_names_the_invoice_and_the_correlation_id(facts: Any) -> None:
    event = facts.event("invoice.issued.v1")
    assert render_invoice_issued(event).subject == (
        f"[order-to-cash] Invoice INV-000304 issued (correlationId: {event.correlation_id})"
    )


def test_invoice_issued_text_body_is_exactly_the_documented_lines(facts: Any) -> None:
    event = facts.event("invoice.issued.v1")
    assert render_invoice_issued(event).text_body == "\n".join(
        [
            "Invoice INV-000304 has been issued for order ORD-000104.",
            "Retailer: CORNERSHOP",
            "Company: HOOLI",
            "Total: 116.667 KWD",
            "Invoice date: 2026-03-07T08:17:28.456Z",
            f"Correlation id: {event.correlation_id}",
        ]
    )


def test_invoice_issued_html_body_is_exactly_the_documented_markup(facts: Any) -> None:
    event = facts.event("invoice.issued.v1")
    assert render_invoice_issued(event).html_body == "\n".join(
        [
            "<p>Invoice <strong>INV-000304</strong> has been issued for order ORD-000104.</p>",
            "<ul>",
            "<li>Retailer: CORNERSHOP</li>",
            "<li>Company: HOOLI</li>",
            "<li>Total: 116.667 KWD</li>",
            "<li>Invoice date: 2026-03-07T08:17:28.456Z</li>",
            "</ul>",
            f"<p>Correlation id: {event.correlation_id}</p>",
        ]
    )


def test_invoice_issued_renders_none_of_the_plausible_wrong_values(facts: Any) -> None:
    event = facts.event("invoice.issued.v1")
    assert_absent(
        render_invoice_issued(event),
        [
            *envelope_wrong_values(event),
            "116667",  # raw integer
            "123456",  # amount: another amount of the same payload
            "123.456 KWD",
            "6789",  # discount
            "6.789 KWD",
            "1 166.67 KWD",  # the exponent of a two-decimal currency
            "PART-A1",
            *wrong_instant_forms(event.payload.invoice_date),
        ],
    )


# ------------------------------------------------------------------------ payment.received.v1


def test_payment_received_recipient_is_the_order_reference_lowercased(facts: Any) -> None:
    """The payload carries no `retailerCode`: the order reference is the best identifier (#7, #8)."""
    message = render_payment_received(facts.event("payment.received.v1"))
    assert message.to == f"ord-000105@{DOMAIN}", "not the invoice or payment reference"


def test_payment_received_subject_names_the_invoice_and_the_correlation_id(facts: Any) -> None:
    event = facts.event("payment.received.v1")
    assert render_payment_received(event).subject == (
        f"[order-to-cash] Payment received for invoice INV-000305 (correlationId: {event.correlation_id})"
    )


def test_payment_received_text_body_is_exactly_the_documented_lines(facts: Any) -> None:
    event = facts.event("payment.received.v1")
    assert render_payment_received(event).text_body == "\n".join(
        [
            "Payment PAY-A-5001 has been received for invoice INV-000305 (order ORD-000105).",
            "Amount: 1 166.67 EUR",
            "Value date: 2026-03-08T09:18:29.567Z",
            "Source: operator",
            f"Correlation id: {event.correlation_id}",
        ]
    )


def test_payment_received_html_body_is_exactly_the_documented_markup(facts: Any) -> None:
    event = facts.event("payment.received.v1")
    assert render_payment_received(event).html_body == "\n".join(
        [
            "<p>Payment <strong>PAY-A-5001</strong> has been received for invoice INV-000305 (order ORD-000105).</p>",
            "<ul>",
            "<li>Amount: 1 166.67 EUR</li>",
            "<li>Value date: 2026-03-08T09:18:29.567Z</li>",
            "<li>Source: operator</li>",
            "</ul>",
            f"<p>Correlation id: {event.correlation_id}</p>",
        ]
    )


def test_payment_received_renders_none_of_the_plausible_wrong_values(facts: Any) -> None:
    event = facts.event("payment.received.v1")
    assert_absent(
        render_payment_received(event),
        [
            *envelope_wrong_values(event),
            "116667",
            "1 166.670 EUR",
            "source: operator",
            "robot",
            *wrong_instant_forms(event.payload.value_date),
        ],
    )


def test_payment_received_escapes_an_externally_supplied_reference(facts: Any) -> None:
    """`paymentReference` is the one value supplied from outside the system (the remittance path)."""
    data = facts.event_dict("payment.received.v1")
    data["payload"]["payment_reference"] = "A&B<script>\"x'"
    message = render_payment_received(facts.event_from("payment.received.v1", data))
    assert "<script>" not in message.html_body
    assert "<strong>A&amp;B&lt;script&gt;&quot;x&#39;</strong>" in message.html_body
    assert "Payment A&B<script>\"x' has been received" in message.text_body, "text is not escaped"


# ------------------------------------------------------------------------ order.completed.v1


def test_order_completed_recipient_is_the_retailer_code_lowercased(facts: Any) -> None:
    message = render_order_completed(facts.event("order.completed.v1"))
    assert message.to == f"shoprite@{DOMAIN}", "not companyCode (wayne)"


def test_order_completed_subject_names_the_order_and_the_correlation_id(facts: Any) -> None:
    event = facts.event("order.completed.v1")
    assert render_order_completed(event).subject == (
        f"[order-to-cash] Order ORD-000106 completed (correlationId: {event.correlation_id})"
    )


def test_order_completed_text_body_is_exactly_the_documented_lines(facts: Any) -> None:
    event = facts.event("order.completed.v1")
    assert render_order_completed(event).text_body == "\n".join(
        [
            "Order ORD-000106 is complete — despatched, invoiced and paid.",
            "Retailer: SHOPRITE",
            "Company: WAYNE",
            "Total: 9 876.50 USD",
            "Completed at: 2026-03-09T10:19:30.678Z",
            f"Correlation id: {event.correlation_id}",
        ]
    )


def test_order_completed_html_body_is_exactly_the_documented_markup(facts: Any) -> None:
    event = facts.event("order.completed.v1")
    assert render_order_completed(event).html_body == "\n".join(
        [
            "<p>Order <strong>ORD-000106</strong> is complete — despatched, invoiced and paid.</p>",
            "<ul>",
            "<li>Retailer: SHOPRITE</li>",
            "<li>Company: WAYNE</li>",
            "<li>Total: 9 876.50 USD</li>",
            "<li>Completed at: 2026-03-09T10:19:30.678Z</li>",
            "</ul>",
            f"<p>Correlation id: {event.correlation_id}</p>",
        ]
    )


def test_order_completed_renders_none_of_the_plausible_wrong_values(facts: Any) -> None:
    event = facts.event("order.completed.v1")
    assert_absent(
        render_order_completed(event),
        [
            *envelope_wrong_values(event),
            "987650",
            "9876.50",
            "9 876.5 USD",
            *wrong_instant_forms(event.payload.completed_at),
        ],
    )


# ------------------------------------------------------------------------ order.cancelled.v1


def test_order_cancelled_recipient_is_the_retailer_code_lowercased(facts: Any) -> None:
    message = render_order_cancelled(facts.event("order.cancelled.v1"))
    assert message.to == f"foodco@{DOMAIN}", "not companyCode (stark)"


def test_order_cancelled_subject_names_the_order_and_the_correlation_id(facts: Any) -> None:
    event = facts.event("order.cancelled.v1")
    assert render_order_cancelled(event).subject == (
        f"[order-to-cash] Order ORD-000107 cancelled (correlationId: {event.correlation_id})"
    )


def test_order_cancelled_text_body_is_exactly_the_documented_lines(facts: Any) -> None:
    event = facts.event("order.cancelled.v1")
    assert render_order_cancelled(event).text_body == "\n".join(
        [
            "Order ORD-000107 has been cancelled.",
            "Reason: credit_rejected",
            "Retailer: FOODCO",
            "Company: STARK",
            "Cancelled at: 2026-03-10T11:20:31.789Z",
            "Compensation steps: stock_released, credit_released",
            f"Correlation id: {event.correlation_id}",
        ]
    )


def test_order_cancelled_html_body_is_exactly_the_documented_markup(facts: Any) -> None:
    event = facts.event("order.cancelled.v1")
    assert render_order_cancelled(event).html_body == "\n".join(
        [
            "<p>Order <strong>ORD-000107</strong> has been cancelled.</p>",
            "<ul>",
            "<li>Reason: credit_rejected</li>",
            "<li>Retailer: FOODCO</li>",
            "<li>Company: STARK</li>",
            "<li>Cancelled at: 2026-03-10T11:20:31.789Z</li>",
            "<li>Compensation steps: stock_released, credit_released</li>",
            "</ul>",
            f"<p>Correlation id: {event.correlation_id}</p>",
        ]
    )


def test_order_cancelled_renders_none_of_the_plausible_wrong_values(facts: Any) -> None:
    """#8's survivor: the template rendered `step.EventType` instead of `step.Step` and 65/65 stayed
    green because `credit.release` was a prefix of `credit.released.v1`. The wrong values here are
    the steps' OTHER fields: `eventType`, `summary`, `occurredAt`, `eventId`."""
    event = facts.event("order.cancelled.v1")
    steps = event.payload.compensation_steps
    assert_absent(
        render_order_cancelled(event),
        [
            *envelope_wrong_values(event),
            "operator_cancelled",
            "operator note A",
            "stock.released.v1",
            "credit.released.v1",
            "released stock",
            "released credit",
            *[str(step.event_id) for step in steps],
            *[format_instant(step.occurred_at) for step in steps],
            *wrong_instant_forms(event.payload.cancelled_at),
        ],
    )


def test_order_cancelled_with_no_compensation_says_none(facts: Any) -> None:
    data = facts.event_dict("order.cancelled.v1")
    data["payload"]["compensation_steps"] = []
    event = facts.event_from("order.cancelled.v1", data)
    message = render_order_cancelled(event)
    assert "Compensation steps: none\n" in message.text_body + "\n"
    assert "<li>Compensation steps: none</li>" in message.html_body


def test_order_cancelled_renders_a_single_step_without_a_separator(facts: Any) -> None:
    data = facts.event_dict("order.cancelled.v1")
    data["payload"]["compensation_steps"] = data["payload"]["compensation_steps"][1:]
    message = render_order_cancelled(facts.event_from("order.cancelled.v1", data))
    assert "Compensation steps: credit_released\n" in message.text_body + "\n"
