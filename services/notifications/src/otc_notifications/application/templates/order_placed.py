# ruff: noqa: E501 - the template literals are one email line each; wrapping them would change the text
"""`order.placed.v1` (`domain-model.md` 7.2, row 1)."""

from otc_contracts.generated.asyncapi import OrderPlacedEvent
from otc_notifications.application.ports.notification_sender import NotificationMessage
from otc_notifications.application.templates.format import (
    escape_html,
    instant_text,
    money_text,
    recipient_for,
    subject_with_correlation_id,
)


def render_order_placed(event: OrderPlacedEvent) -> NotificationMessage:
    payload = event.payload
    total = money_text(payload.total_amount, payload.currency)
    order_date = instant_text(payload.order_date)
    subject = subject_with_correlation_id(
        f"Order {payload.order_reference} placed", event.correlation_id
    )
    text = "\n".join(
        [
            f"Order {payload.order_reference} has been placed.",
            f"Retailer: {payload.retailer_code}",
            f"Company: {payload.company_code}",
            f"Total: {total}",
            f"Order date: {order_date}",
            f"Correlation id: {event.correlation_id}",
        ]
    )
    html = "\n".join(
        [
            f"<p>Order <strong>{escape_html(payload.order_reference)}</strong> has been placed.</p>",
            "<ul>",
            f"<li>Retailer: {escape_html(payload.retailer_code)}</li>",
            f"<li>Company: {escape_html(payload.company_code)}</li>",
            f"<li>Total: {escape_html(total)}</li>",
            f"<li>Order date: {escape_html(order_date)}</li>",
            "</ul>",
            f"<p>Correlation id: {escape_html(str(event.correlation_id))}</p>",
        ]
    )
    return NotificationMessage(recipient_for(payload.retailer_code), subject, text, html)
