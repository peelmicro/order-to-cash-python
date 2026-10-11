# ruff: noqa: E501 - the template literals are one email line each; wrapping them would change the text
"""`payment.received.v1` (`domain-model.md` 7.2, row 11).

`PaymentReceivedPayload` carries no `retailerCode`, so the recipient is synthesised from the
`orderReference`, the best available identifier for this one fact (#7 and #8 made the same choice).
`paymentReference` is the one value supplied from outside the system (the remittance path), which
is why every HTML interpolation is escaped unconditionally.
"""

from otc_contracts.generated.asyncapi import PaymentReceivedEvent
from otc_notifications.application.ports.notification_sender import NotificationMessage
from otc_notifications.application.templates.format import (
    escape_html,
    instant_text,
    money_text,
    recipient_for,
    subject_with_correlation_id,
)


def render_payment_received(event: PaymentReceivedEvent) -> NotificationMessage:
    payload = event.payload
    amount = money_text(payload.amount, payload.currency)
    value_date = instant_text(payload.value_date)
    subject = subject_with_correlation_id(
        f"Payment received for invoice {payload.invoice_reference}", event.correlation_id
    )
    text = "\n".join(
        [
            f"Payment {payload.payment_reference} has been received for invoice {payload.invoice_reference} (order {payload.order_reference}).",
            f"Amount: {amount}",
            f"Value date: {value_date}",
            f"Source: {payload.source}",
            f"Correlation id: {event.correlation_id}",
        ]
    )
    html = "\n".join(
        [
            f"<p>Payment <strong>{escape_html(payload.payment_reference)}</strong> has been received for invoice {escape_html(payload.invoice_reference)} (order {escape_html(payload.order_reference)}).</p>",
            "<ul>",
            f"<li>Amount: {escape_html(amount)}</li>",
            f"<li>Value date: {escape_html(value_date)}</li>",
            f"<li>Source: {escape_html(str(payload.source))}</li>",
            "</ul>",
            f"<p>Correlation id: {escape_html(str(event.correlation_id))}</p>",
        ]
    )
    return NotificationMessage(recipient_for(payload.order_reference), subject, text, html)
