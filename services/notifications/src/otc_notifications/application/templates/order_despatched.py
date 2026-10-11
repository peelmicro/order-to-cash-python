# ruff: noqa: E501 - the template literals are one email line each; wrapping them would change the text
"""`order.despatched.v1` (`domain-model.md` 7.2, row 9)."""

from otc_contracts.generated.asyncapi import OrderDespatchedEvent
from otc_notifications.application.ports.notification_sender import NotificationMessage
from otc_notifications.application.templates.format import (
    escape_html,
    instant_text,
    recipient_for,
    subject_with_correlation_id,
)


def render_order_despatched(event: OrderDespatchedEvent) -> NotificationMessage:
    payload = event.payload
    line_summary = ", ".join(f"{line.product_code} x{line.units}" for line in payload.lines)
    despatch_date = instant_text(payload.despatch_date)
    subject = subject_with_correlation_id(
        f"Order {payload.order_reference} despatched ({payload.despatch_reference})",
        event.correlation_id,
    )
    text = "\n".join(
        [
            f"Order {payload.order_reference} has been despatched.",
            f"Despatch reference: {payload.despatch_reference}",
            f"Despatch date: {despatch_date}",
            f"Retailer: {payload.retailer_code}",
            f"Company: {payload.company_code}",
            f"Lines: {line_summary}",
            f"Correlation id: {event.correlation_id}",
        ]
    )
    html = "\n".join(
        [
            f"<p>Order <strong>{escape_html(payload.order_reference)}</strong> has been despatched.</p>",
            "<ul>",
            f"<li>Despatch reference: {escape_html(payload.despatch_reference)}</li>",
            f"<li>Despatch date: {escape_html(despatch_date)}</li>",
            f"<li>Retailer: {escape_html(payload.retailer_code)}</li>",
            f"<li>Company: {escape_html(payload.company_code)}</li>",
            f"<li>Lines: {escape_html(line_summary)}</li>",
            "</ul>",
            f"<p>Correlation id: {escape_html(str(event.correlation_id))}</p>",
        ]
    )
    return NotificationMessage(recipient_for(payload.retailer_code), subject, text, html)
