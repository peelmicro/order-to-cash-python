# ruff: noqa: E501 - the template literals are one email line each; wrapping them would change the text
"""`invoice.issued.v1` (`domain-model.md` 7.2, row 10)."""

from otc_contracts.generated.asyncapi import InvoiceIssuedEvent
from otc_notifications.application.ports.notification_sender import NotificationMessage
from otc_notifications.application.templates.format import (
    escape_html,
    instant_text,
    money_text,
    recipient_for,
    subject_with_correlation_id,
)


def render_invoice_issued(event: InvoiceIssuedEvent) -> NotificationMessage:
    payload = event.payload
    total = money_text(payload.total_amount, payload.currency)
    invoice_date = instant_text(payload.invoice_date)
    subject = subject_with_correlation_id(
        f"Invoice {payload.invoice_reference} issued", event.correlation_id
    )
    text = "\n".join(
        [
            f"Invoice {payload.invoice_reference} has been issued for order {payload.order_reference}.",
            f"Retailer: {payload.retailer_code}",
            f"Company: {payload.company_code}",
            f"Total: {total}",
            f"Invoice date: {invoice_date}",
            f"Correlation id: {event.correlation_id}",
        ]
    )
    html = "\n".join(
        [
            f"<p>Invoice <strong>{escape_html(payload.invoice_reference)}</strong> has been issued for order {escape_html(payload.order_reference)}.</p>",
            "<ul>",
            f"<li>Retailer: {escape_html(payload.retailer_code)}</li>",
            f"<li>Company: {escape_html(payload.company_code)}</li>",
            f"<li>Total: {escape_html(total)}</li>",
            f"<li>Invoice date: {escape_html(invoice_date)}</li>",
            "</ul>",
            f"<p>Correlation id: {escape_html(str(event.correlation_id))}</p>",
        ]
    )
    return NotificationMessage(recipient_for(payload.retailer_code), subject, text, html)
