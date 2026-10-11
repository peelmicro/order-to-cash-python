# ruff: noqa: E501 - the template literals are one email line each; wrapping them would change the text
"""`order.cancelled.v1` (`domain-model.md` 7.2, row 13)."""

from otc_contracts.generated.asyncapi import OrderCancelledEvent
from otc_notifications.application.ports.notification_sender import NotificationMessage
from otc_notifications.application.templates.format import (
    escape_html,
    instant_text,
    recipient_for,
    subject_with_correlation_id,
)


def render_order_cancelled(event: OrderCancelledEvent) -> NotificationMessage:
    payload = event.payload
    compensation_summary = (
        ", ".join(str(step.step) for step in payload.compensation_steps)
        if payload.compensation_steps
        else "none"
    )
    cancelled_at = instant_text(payload.cancelled_at)
    subject = subject_with_correlation_id(
        f"Order {payload.order_reference} cancelled", event.correlation_id
    )
    text = "\n".join(
        [
            f"Order {payload.order_reference} has been cancelled.",
            f"Reason: {payload.cancellation_reason}",
            f"Retailer: {payload.retailer_code}",
            f"Company: {payload.company_code}",
            f"Cancelled at: {cancelled_at}",
            f"Compensation steps: {compensation_summary}",
            f"Correlation id: {event.correlation_id}",
        ]
    )
    html = "\n".join(
        [
            f"<p>Order <strong>{escape_html(payload.order_reference)}</strong> has been cancelled.</p>",
            "<ul>",
            f"<li>Reason: {escape_html(str(payload.cancellation_reason))}</li>",
            f"<li>Retailer: {escape_html(payload.retailer_code)}</li>",
            f"<li>Company: {escape_html(payload.company_code)}</li>",
            f"<li>Cancelled at: {escape_html(cancelled_at)}</li>",
            f"<li>Compensation steps: {escape_html(compensation_summary)}</li>",
            "</ul>",
            f"<p>Correlation id: {escape_html(str(event.correlation_id))}</p>",
        ]
    )
    return NotificationMessage(recipient_for(payload.retailer_code), subject, text, html)
