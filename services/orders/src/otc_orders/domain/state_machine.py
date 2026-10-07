"""Table T-1 of `domain-model.md` section 3.3 as immutable data.

Row 1 ((none) -> placed) is creation: it is `Order.place`, with no source to look up, so it is not
in the table (a creation row nothing consults is #7's review defect D1). `completed` and
`cancelled` occur only as targets, so terminality needs no code.
"""

from typing import NamedTuple

from otc_orders.domain.value_objects.order_status import OrderStatus

PLACED = OrderStatus.PLACED
STOCK_RESERVED = OrderStatus.STOCK_RESERVED
CREDIT_APPROVED = OrderStatus.CREDIT_APPROVED
CONFIRMED = OrderStatus.CONFIRMED
DESPATCHED = OrderStatus.DESPATCHED
INVOICED = OrderStatus.INVOICED
PAID = OrderStatus.PAID
COMPLETED = OrderStatus.COMPLETED
CANCELLED = OrderStatus.CANCELLED


class Edge(NamedTuple):
    source: OrderStatus
    target: OrderStatus


LEGAL_EDGES: frozenset[Edge] = frozenset(
    {
        Edge(PLACED, STOCK_RESERVED),  # T-1 row 2
        Edge(STOCK_RESERVED, CREDIT_APPROVED),  # T-1 row 3
        Edge(CREDIT_APPROVED, CONFIRMED),  # T-1 row 4
        Edge(CONFIRMED, DESPATCHED),  # T-1 row 5
        Edge(DESPATCHED, INVOICED),  # T-1 row 6
        Edge(INVOICED, PAID),  # T-1 row 7
        Edge(PAID, COMPLETED),  # T-1 row 8
        Edge(PLACED, CANCELLED),  # T-1 row 9
        Edge(STOCK_RESERVED, CANCELLED),  # T-1 row 10
        Edge(CREDIT_APPROVED, CANCELLED),  # T-1 row 11
        Edge(CONFIRMED, CANCELLED),  # T-1 row 12
    }
)


def is_legal(source: OrderStatus, target: OrderStatus) -> bool:
    return Edge(source, target) in LEGAL_EDGES
