"""`OrderStatus`: the nine statuses of `domain-model.md` section 3.1, each with its stored token.

A plain `Enum` (not `StrEnum`): a raw `"placed"` read from a row never compares equal to
`OrderStatus.PLACED` and must be parsed. Tokens are written out, never derived from member names.
"""

from enum import Enum

from otc_orders.domain.errors import InvalidOrderSnapshotError


class OrderStatus(Enum):
    PLACED = "placed"
    STOCK_RESERVED = "stock_reserved"
    CREDIT_APPROVED = "credit_approved"
    CONFIRMED = "confirmed"
    DESPATCHED = "despatched"
    INVOICED = "invoiced"
    PAID = "paid"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


_BY_TOKEN: dict[str, OrderStatus] = {
    "placed": OrderStatus.PLACED,
    "stock_reserved": OrderStatus.STOCK_RESERVED,
    "credit_approved": OrderStatus.CREDIT_APPROVED,
    "confirmed": OrderStatus.CONFIRMED,
    "despatched": OrderStatus.DESPATCHED,
    "invoiced": OrderStatus.INVOICED,
    "paid": OrderStatus.PAID,
    "completed": OrderStatus.COMPLETED,
    "cancelled": OrderStatus.CANCELLED,
}


def parse_order_status(token: object) -> OrderStatus:
    """Exact, case- and whitespace-sensitive; a `str` subclass is refused (`type(...) is str`)."""
    if type(token) is not str or token not in _BY_TOKEN:
        raise InvalidOrderSnapshotError(f"{token!r} is not an order status")
    return _BY_TOKEN[token]
