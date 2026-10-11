"""Small, pure formatting helpers shared by the seven templates.

* Money is text through the ISO 4217 exponent table (SA-5): `format_money` from the shared kernel,
  the implementation the Projector's timeline summaries use too, so an email and a timeline entry
  read alike for the same amount. Never a float, never Babel or `Intl`.
* An instant is the wire formatter's `YYYY-MM-DDTHH:MM:SS.mmmZ` (`otc_contracts.format_instant`),
  never `str(datetime)` or `isoformat()`.
* The recipient is synthesised from a business code: the domain model carries no email address for
  any party (#7 `notification-format.ts`, #8 `NotificationFormat.cs`, both the same address
  shape). Mailpit captures any address without delivering it.
"""

from datetime import datetime
from uuid import UUID

from otc_contracts import format_instant
from otc_shared_kernel import format_money

RECIPIENT_DOMAIN = "retailer.order-to-cash.example"

_HTML_ESCAPES = str.maketrans({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"})


def money_text(amount_minor_units: int, currency: str) -> str:
    return format_money(amount_minor_units, currency)


def instant_text(value: datetime) -> str:
    return format_instant(value)


def recipient_for(identifier: str) -> str:
    """`<identifier lower>@retailer.order-to-cash.example`. Normally the retailer's code;
    `payment.received.v1` carries no `retailerCode`, so its template passes `orderReference`."""
    return f"{identifier.lower()}@{RECIPIENT_DOMAIN}"


def subject_with_correlation_id(summary: str, correlation_id: UUID) -> str:
    """The correlation id is in the subject of every template: one formatter, so the wording
    cannot drift between the seven."""
    return f"[order-to-cash] {summary} (correlationId: {correlation_id})"


def escape_html(value: str) -> str:
    """Every payload-derived string inside an HTML body goes through this first: a business
    reference (`paymentReference` on the remittance path) is supplied from outside the system."""
    return value.translate(_HTML_ESCAPES)
